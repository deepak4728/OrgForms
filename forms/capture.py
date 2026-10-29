"""Versioned, deterministic capture at the workspace's authoritative data home.

Browser and API input share this service. No provider/network call is required
for acceptance. The first transactional write serializes quota, retry, and edit
decisions on SQLite; select_for_update alone would not provide that guarantee.
"""
import copy
import hashlib
import json
import re
import secrets
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import UserPortfolio
from organizations.permissions import can_respond_to_form, require_form_records, require_membership
from orgforms.upload_validation import validate_private_document
from .models import CaptureReceipt, CollectionRevision, DynamicForm, FormSubmission, SubmissionAttachment, SubmissionRevision
from .services import _visible, normalize_schema, save_item_selections, validate_submission
from .legacy_history import snapshot_item_selections_v1

SCHEMA_DIALECT = "orgforms-fields-v1"


class CaptureError(ValidationError):
    def __init__(self, message, *, status=400, code="invalid_capture"):
        self.status = status
        self.error_code = code
        super().__init__({"detail": message})


def publish_revision(form, *, actor=None):
    """Called within DynamicForm.save's write transaction, never by a signal."""
    snapshot = {key: copy.deepcopy(getattr(form, key)) for key in ("title", "description", "purpose", "schema", "destination_schema_id", "field_mapping")}
    previous = form.current_revision
    if previous and all(getattr(previous, key) == value for key, value in snapshot.items()):
        return previous
    return CollectionRevision.objects.create(
        form=form, number=previous.number + 1 if previous else 1,
        schema_dialect=SCHEMA_DIALECT, created_by=actor or form.created_by,
        **snapshot,
    )


def _lock_form(form_id):
    DynamicForm.objects.filter(pk=form_id).update(capture_sequence=F("capture_sequence") + 1)
    return DynamicForm.objects.select_related("organization").get(pk=form_id)


def record_revision(submission, *, actor=None, event, source):
    return SubmissionRevision.objects.create(
        submission=submission, number=submission.version, data=copy.deepcopy(submission.data),
        respondent_name=submission.respondent_name, respondent_email=submission.respondent_email,
        status=submission.status, actor=actor if getattr(actor, "is_authenticated", False) else None,
        event=event, source=source,
        attachments=list(submission.current_attachments.values("id", "field_id", "original_name")),
        item_selections=snapshot_item_selections_v1(submission),
        record_snapshot={"id": str(submission.record_id), "version": submission.record_version} if submission.record_id else {},
    )


def _request_hash(payload, uploads):
    files = {}
    for field_id, upload in sorted(uploads.items()):
        error = validate_private_document(upload)
        if error:
            raise ValidationError({field_id: error})
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        files[field_id] = {"name": Path(upload.name).name, "sha256": digest.hexdigest()}
    # Include submitted values, not current catalog prices or the latest schema:
    # an already committed retry must survive a later definition/price change.
    content = {"data": payload.get("data", payload), "files": files}
    for key in ("respondent_name", "respondent_email", "edit_token", "revision_id", "expected_version", "record_id", "record_version"):
        content[key] = payload.get(key)
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _version_matches(value, expected):
    return not isinstance(value, bool) and str(value) == str(expected)


def _update_opted_in_portfolio(user, form, data, schema):
    if not getattr(user, "is_authenticated", False):
        return
    portfolio = UserPortfolio.objects.filter(user=user, auto_update_from_submissions=True).first()
    if not portfolio:
        return
    profile = portfolio.profile_data if isinstance(portfolio.profile_data, dict) else {}
    answers = {}
    for field in schema.get("fields", [])[:40]:
        value = data.get(field["id"])
        if field["type"] != "file" and value not in (None, "", [], {}) and isinstance(value, (str, int, float, bool)):
            answers[field["label"][:100]] = value[:160] if isinstance(value, str) else value
    if not answers:
        return
    prior = profile.get("submitted_details", {})
    prior = prior if isinstance(prior, dict) else {}
    prior[form.slug] = {"form": form.title, "updated": timezone.localdate().isoformat(), "answers": answers}
    profile["submitted_details"] = dict(list(prior.items())[-10:])
    while len(json.dumps(profile, ensure_ascii=False)) > 20000 and len(profile["submitted_details"]) > 1:
        profile["submitted_details"].pop(next(iter(profile["submitted_details"])))
    portfolio.profile_data = profile
    portfolio.save(update_fields=("profile_data", "updated_at"))


def capture_submission(*, form_id, user, owner_hash, payload, uploads=None,
                       edit_submission_id=None, request_key=None, source="browser"):
    if not isinstance(payload, dict) or not isinstance(payload.get("data", payload), dict):
        raise CaptureError("The response data must be a JSON object.")
    if source not in {"browser", "api"}:
        raise CaptureError("Unsupported capture source.")
    key = request_key or payload.get("request_id")
    if key is not None and (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key)):
        raise CaptureError("Use a request_id of up to 128 letters, digits, underscores, or hyphens.")
    uploads = uploads or {}
    try:
        fingerprint = _request_hash(payload, uploads)
    except (TypeError, ValueError):
        raise CaptureError("The response must contain valid finite JSON values.")
    new_files = []
    try:
        with transaction.atomic():
            form = _lock_form(form_id)
            if not can_respond_to_form(user, form):
                raise CaptureError("This account does not have access to this active form.", status=403, code="access_denied")
            if key:
                receipt = CaptureReceipt.objects.filter(form=form, owner_hash=owner_hash, key=key).first()
                if receipt:
                    if receipt.payload_hash != fingerprint:
                        raise CaptureError("This request_id was already used for different answers. Use a new request_id.", status=409, code="request_conflict")
                    return {**receipt.response, "replayed": True}
            submission = None
            if payload.get("edit_token"):
                submission = FormSubmission.objects.filter(pk=edit_submission_id, form=form, organization=form.organization).first()
                if not submission:
                    raise CaptureError("This response can no longer be edited. Submit a new response instead.", status=403, code="edit_denied")
                if payload.get("expected_version") is not None and not _version_matches(payload["expected_version"], submission.version):
                    raise CaptureError("This response changed in another window. Reload before editing.", status=409, code="version_conflict")
                if not submission.revisions.exists():
                    record_revision(submission, event="legacy_baseline", source="legacy")
                revision = submission.collection_revision
            else:
                revision = form.current_revision
                if form.response_limit is not None and form.submissions.count() >= form.response_limit:
                    raise CaptureError("This form has reached its response limit.", status=409, code="response_limit_reached")
            if revision is None:
                raise CaptureError("This form has no published definition.", status=409, code="definition_unavailable")
            if payload.get("revision_id") and str(payload["revision_id"]) != str(revision.pk):
                raise CaptureError("The form definition changed. Reload this page before submitting.", status=409, code="revision_conflict")
            schema = normalize_schema(revision.schema, form.organization)
            fields = {field["id"]: field for field in schema["fields"]}
            data = copy.deepcopy(payload.get("data", payload))
            known_file_fields = {field["id"] for field in schema["fields"] if field["type"] == "file"}
            if set(uploads) - known_file_fields:
                raise CaptureError("An attachment does not belong to this form definition.")
            existing_files = set(submission.current_attachments.values_list("field_id", flat=True)) if submission else set()
            accepted_uploads = {}
            for field in schema["fields"]:
                if field["type"] == "file":
                    field_id = field["id"]
                    if _visible(field, data, fields) and field_id in uploads:
                        accepted_uploads[field_id] = uploads[field_id]
                    data[field_id] = "Uploaded document" if field_id in accepted_uploads or field_id in existing_files else ""
            data = validate_submission(form, data, schema=schema)
            from datasets.services import validate_reference_values, project_submission
            validate_reference_values(schema, data, user, form.organization)
            creating = submission is None
            if creating:
                submission = FormSubmission(
                    form=form, organization=form.organization, collection_revision=revision,
                    submitted_by=user if getattr(user, "is_authenticated", False) else None,
                )
            else:
                submission.version += 1
            submission.data = data
            submission.respondent_name = str(payload.get("respondent_name", ""))[:200]
            submission.respondent_email = str(payload.get("respondent_email", ""))[:254]
            submission.save()
            selections = save_item_selections(form, submission, data, payload, schema=schema)
            if selections:
                submission.data = {**data, "order_id": selections[0].pk}
                submission.save(update_fields=("data",))
            # Keep previous attachment bytes and metadata for historical revisions.
            # Only current files appear in the ordinary response list.
            for field_id, upload in accepted_uploads.items():
                submission.attachments.filter(field_id=field_id, is_current=True).update(is_current=False)
                attachment = SubmissionAttachment(submission=submission, field_id=field_id, original_name=Path(upload.name).name[:255], file=upload)
                try:
                    attachment.save()
                finally:
                    if attachment.file.name and attachment.file._committed:
                        new_files.append(attachment.file.name)
            visible_file_ids = {field["id"] for field in schema["fields"] if field["type"] == "file" and _visible(field, data, fields)}
            submission.attachments.filter(is_current=True).exclude(field_id__in=visible_file_ids).update(is_current=False)
            linked_record = project_submission(submission, revision, data, user, payload)
            record_revision(submission, actor=user, event="created" if creating else "edited", source=source)
            _update_opted_in_portfolio(user, form, data, schema)
            editable = all(item.status == "pending" and item.payment_status == "pending" for item in submission.item_selections.all())
            response = {
                "success": True, "submission_id": submission.pk, "version": submission.version,
                "revision_id": str(revision.pk), "revision_number": revision.number,
                "created": creating, "replayed": False, "can_edit": editable,
                "record_id": str(linked_record.pk) if linked_record else None,
                "record_version": linked_record.version if linked_record else None,
                "edit_token": str(payload.get("edit_token") or secrets.token_urlsafe(32)) if editable else "",
            }
            if key:
                CaptureReceipt.objects.create(form=form, submission=submission, owner_hash=owner_hash, key=key, payload_hash=fingerprint, response=response)
            return response
    except Exception:
        for name in new_files:
            default_storage.delete(name)
        raise


def change_submission_status(*, submission_id, user, status, expected_version=None):
    if status not in dict(FormSubmission.STATUS_CHOICES):
        raise CaptureError("Choose a valid submission status.")
    identity = FormSubmission.objects.only("form_id").get(pk=submission_id)
    with transaction.atomic():
        form = _lock_form(identity.form_id)
        require_membership(user, form.organization, manage=True)
        require_form_records(user, form)
        if form.organization.is_archived:
            raise CaptureError("Restore this organization before reviewing responses.", status=409)
        submission = FormSubmission.objects.get(pk=submission_id, form=form, organization=form.organization)
        if expected_version is not None and not _version_matches(expected_version, submission.version):
            raise CaptureError("This response changed. Reload before reviewing it.", status=409, code="version_conflict")
        if submission.status != status:
            if not submission.revisions.exists():
                record_revision(submission, event="legacy_baseline", source="legacy")
            submission.status = status
            submission.version += 1
            submission.save(update_fields=("status", "version"))
            record_revision(submission, actor=user, event="status_changed", source="staff")
        return submission
