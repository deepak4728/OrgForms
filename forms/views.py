import csv
import hashlib
import io
import json
import re
import secrets
import zipfile
import xml.etree.ElementTree as ElementTree
from django import forms as django_forms
from datetime import timedelta
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, OperationalError
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework.response import Response
from django.db.models.functions import ExtractHour, TruncHour
from organizations.models import Organization, OrganizationMembership
from organizations.permissions import require_membership, visible_forms, require_form_manage, require_form_records, require_form_response, can_respond_to_form
from orgforms.upload_validation import validate_private_document
from forms.models import DynamicForm, FormSubmission, SubmissionAttachment, Catalog, CatalogItem
from forms.forms import FormAccessSettingsForm
from forms.capture import CaptureError, capture_submission, change_submission_status
from forms.serializers import DynamicFormSerializer, CatalogItemCreateSerializer
from ai_gateway.classification import classify_text
from forms.services import validate_form_schema, normalize_schema
from accounts.models import UserPortfolio
from ai_gateway.models import AIConfiguration
from ai_gateway.services import classify_remote, generate_json


class PublicClassificationThrottle(AnonRateThrottle):
    scope = "public_classify"


_MAX_XLSX_EXPANDED_SIZE = 24 * 1024 * 1024
_MAX_XLSX_ENTRY_SIZE = 12 * 1024 * 1024
_MAX_XLSX_ENTRIES = 5000
_MAX_XLSX_ROWS = 2000
_MAX_XLSX_COLUMNS = 100


def _safe_csv_cell(value):
    """Keep spreadsheet software from evaluating respondent supplied cells."""
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n"))
        or value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


@login_required
@xframe_options_sameorigin
def form_editor(request, org_slug, form_id=None):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    if organization.is_archived:
        messages.error(request, "Restore this organization before editing its forms.")
        return redirect("organizations:settings", org_slug=organization.slug)
    instance = get_object_or_404(DynamicForm, pk=form_id, organization=organization) if form_id else None
    can_manage_access = membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER)
    if instance:
        require_form_manage(request.user, instance)
    elif not can_manage_access:
        raise PermissionDenied("An organization manager or admin is required to create forms.")
    initial_schema = instance.schema if instance else {"fields": [{"id": "name", "label": "Name", "type": "text", "required": True}]}
    initial_access = {
        "visibility": instance.visibility if instance else DynamicForm.VISIBILITY_ORGANIZATION,
        "access_emails": "\n".join(instance.allowed_users.values_list("email", flat=True)) if instance else "",
        "access_departments": instance.allowed_departments.values_list("pk", flat=True) if instance else [],
    }
    from datasets.models import DatasetSchemaVersion, Record
    from datasets.permissions import visible_datasets, require_dataset, dataset_permissions
    dataset_choices = []
    lookup_choices = []
    for dataset in visible_datasets(request.user, organization):
        version = dataset.current_schema
        if can_manage_access and not dataset.is_archived:
            dataset_choices.append({"id": str(version.pk), "name": f"{dataset.name} · schema {version.number}", "fields": version.schema["fields"]})
        if dataset_permissions(request.user, dataset)["lookup"] and not dataset.is_archived:
            lookup_choices.append({"id": str(dataset.pk), "name": dataset.name})
    if can_manage_access and instance and instance.destination_schema_id and str(instance.destination_schema_id) not in {row["id"] for row in dataset_choices}:
        old = instance.destination_schema
        dataset_choices.append({"id": str(old.pk), "name": f"{old.dataset.name} · pinned schema {old.number}", "fields": old.schema["fields"]})
    access_settings = FormAccessSettingsForm(request.POST if request.method == "POST" and can_manage_access else None, initial=initial_access, organization=organization)
    def editor(error="", schema=None):
        revision = instance.current_revision if instance else None
        return render(request, "forms/form_editor.html", {
            "organization": organization, "form": instance,
            "schema_text": request.POST.get("schema", json.dumps(initial_schema, indent=2)),
            "schema_data": schema if schema is not None else initial_schema,
            "title_value": request.POST.get("title", instance.title if instance else ""),
            "description_value": request.POST.get("description", instance.description if instance else ""),
            "purpose_value": request.POST.get("purpose", instance.purpose if instance else ""),
            "slug_value": request.POST.get("slug", instance.slug if instance else ""),
            "status_value": request.POST.get("status", instance.status if instance else DynamicForm.STATUS_DRAFT),
            "response_limit_value": request.POST.get("response_limit", instance.response_limit or "" if instance else ""),
            "revision": revision,
            "base_revision_value": request.POST.get("base_revision", str(revision.pk) if revision else ""),
            "dataset_choices": dataset_choices, "lookup_choices": lookup_choices,
            "destination_value": request.POST.get("destination_schema", str(instance.destination_schema_id) if instance and instance.destination_schema_id else ""),
            "mapping_text": request.POST.get("field_mapping", json.dumps(instance.field_mapping if instance else {})),
            "restaurant_order": (request.POST.get("include_items") == "on" or request.POST.get("restaurant_order") == "on") if request.method == "POST" else any(field.get("type") == "item_cards" for field in initial_schema.get("fields", [])),
            "access_settings": access_settings, "error": error,
            "can_manage_access": can_manage_access,
            "embedded": request.GET.get("dialog") == "1",
            "base_template": "embedded.html" if request.GET.get("dialog") == "1" else "base.html",
        })
    if request.method != "POST":
        return editor()
    title = request.POST.get("title", "").strip()
    access_valid = access_settings.is_valid() if can_manage_access else True
    try:
        schema = json.loads(request.POST.get("schema", "{}"))
        validate_form_schema(schema)
        if (request.POST.get("include_items") == "on" or request.POST.get("restaurant_order") == "on"):
            schema.setdefault("items_field_id", "items")
            if not any(field.get("id") == schema["items_field_id"] for field in schema["fields"]):
                schema["fields"].append({"id": schema["items_field_id"], "label": "Items", "type": "item_cards", "required": True})
        else:
            schema.pop("restaurant_order", None)
            schema.pop("items_field_id", None)
        schema = normalize_schema(schema, organization)
    except (json.JSONDecodeError, ValidationError, TypeError, AttributeError) as exc:
        return editor(str(exc))
    if not access_valid:
        return editor("Check the sharing settings below.", schema)
    if not title or len(title) > 200:
        return editor("Enter a form title of up to 200 characters.", schema)
    try:
        response_limit = django_forms.IntegerField(min_value=1, max_value=2147483647, required=False).clean(request.POST.get("response_limit")) if can_manage_access else instance.response_limit
        destination = instance.destination_schema if instance else None
        mapping = instance.field_mapping if instance else {}
        if can_manage_access and "destination_schema" in request.POST:
            destination_id = request.POST.get("destination_schema")
            destination = DatasetSchemaVersion.objects.filter(pk=django_forms.UUIDField().clean(destination_id), dataset__organization=organization).first() if destination_id else None
            if destination_id and destination is None:
                raise ValidationError("Choose a destination dataset from this organization.")
            mapping = json.loads(request.POST.get("field_mapping", "{}"))
    except (ValidationError, ValueError, TypeError) as error:
        return editor(str(error), schema)
    form_slug = slugify(request.POST.get("slug", "") or title)[:180] or "form"
    if form_slug in {"settings", "people", "menu", "submissions", "forms", "data"}:
        return editor("Choose a different link name; this name is reserved for workspace pages.", schema)
    if organization.forms.filter(slug=form_slug).exclude(pk=instance.pk if instance else None).exists():
        return editor("That form URL is already used in this organization.", schema)
    try:
        with transaction.atomic():
            form = instance or DynamicForm(organization=organization, created_by=request.user)
            form.title = title
            form.slug = form_slug
            form.description = request.POST.get("description", "").strip()
            form.purpose = request.POST.get("purpose", "").strip()[:120]
            form.schema = schema
            form.status = request.POST.get("status", DynamicForm.STATUS_DRAFT)
            if form.status not in dict(DynamicForm.STATUS_CHOICES):
                form.status = DynamicForm.STATUS_DRAFT
            if can_manage_access:
                form.visibility = access_settings.cleaned_data["visibility"]
                form.response_limit = response_limit
                form.destination_schema = destination
                form.field_mapping = mapping
            form._expected_revision = request.POST.get("base_revision")
            form._revision_actor = request.user
            form.save()
            if can_manage_access:
                form.allowed_users.set(access_settings.allowed_accounts)
                form.allowed_departments.set(access_settings.cleaned_data["access_departments"])
    except ValidationError as error:
        return editor(str(error), schema)
    messages.success(request, "Form and sharing settings saved.")
    if request.GET.get("dialog") == "1":
        return render(request, "forms/form_saved.html", {"organization": organization})
    return redirect("organizations:detail", org_slug=organization.slug)


def _prepare_response_history(submissions):
    for submission in submissions:
        submission.display_respondent = submission.respondent_name or (submission.submitted_by.email if submission.submitted_by else "") or "Anonymous respondent"
        revision = submission.collection_revision
        labels = {field["id"]: field["label"] for field in (revision.schema if revision else {}).get("fields", [])}
        submission.answer_rows = [{"label": labels.get(key, key), "value": value} for key, value in submission.data.items()]
        submission.visible_attachments = [item for item in submission.attachments.all() if item.is_current]
        submission.history_entries = list(submission.revisions.all())
        for entry in submission.history_entries:
            entry.answer_rows = [{"label": labels.get(key, key), "value": value} for key, value in entry.data.items()]


@login_required
@xframe_options_sameorigin
def form_submissions(request, org_slug, form_id):
    organization = get_object_or_404(Organization, slug=org_slug)
    require_membership(request.user, organization)
    form = get_object_or_404(DynamicForm, organization=organization, pk=form_id)
    require_form_records(request.user, form)
    submissions = list(form.submissions.select_related("submitted_by", "collection_revision").prefetch_related("attachments", "revisions")[:200])
    _prepare_response_history(submissions)
    return render(request, "forms/submissions.html", {
        "organization": organization, "form": form, "submissions": submissions,
        "embedded": request.GET.get("dialog") == "1",
        "base_template": "embedded.html" if request.GET.get("dialog") == "1" else "base.html",
    })


@login_required
def menu_editor(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    require_membership(request.user, organization, manage=True)
    if organization.is_archived:
        messages.error(request, "Restore this organization before editing its menu.")
        return redirect("organizations:settings", org_slug=organization.slug)
    business = Catalog.for_organization(organization)
    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "availability":
            item = get_object_or_404(CatalogItem, catalog__organization=organization, pk=request.POST.get("item_id"))
            item.is_available = not item.is_available
            item.save(update_fields=("is_available", "updated_at"))
        else:
            serializer = CatalogItemCreateSerializer(data={
                "name": request.POST.get("name", "").strip(),
                "category": request.POST.get("category", "General").strip() or "General",
                "description": request.POST.get("description", "").strip(),
                "price": request.POST.get("price", "").strip(),
                "is_available": True,
            })
            if not serializer.is_valid():
                messages.error(request, "Enter a valid item name and non-negative price.")
            else:
                item = serializer.save(catalog=business)
                messages.success(request, f"{item.name} was added to the menu.")
        if request.POST.get("return_to") == "library":
            return redirect(f"{reverse('datasets:library', kwargs={'org_slug': organization.slug})}?view=items")
        return redirect("forms:menu", org_slug=organization.slug)
    return render(request, "forms/menu.html", {
        "organization": organization,
        "items": CatalogItem.objects.filter(catalog=business).order_by("category", "name"),
    })


def _capture_scope(request):
    if request.user.is_authenticated:
        identity = f"user:{request.user.pk}"
    else:
        identity = request.session.get("capture_owner")
        if not identity:
            identity = secrets.token_urlsafe(32)
            request.session["capture_owner"] = identity
    return hashlib.sha256(identity.encode()).hexdigest()


def _capture_response(request, form, *, source):
    try:
        if hasattr(request, "data"):
            raw = request.data
            payload = raw.dict() if hasattr(raw, "dict") else raw
            if isinstance(payload, dict):
                payload = {key: value for key, value in payload.items() if key not in request.FILES}
        else:
            payload = json.loads(request.body or b"{}") if request.content_type == "application/json" else request.POST.dict()
        if isinstance(payload, dict) and isinstance(payload.get("data"), str):
            payload["data"] = json.loads(payload["data"])
        if not isinstance(payload, dict):
            raise CaptureError("The response must be a JSON object.")
        sessions = request.session.get("public_form_edit_tokens", {})
        sessions = sessions if isinstance(sessions, dict) else {}
        result = capture_submission(
            form_id=form.pk, user=request.user, owner_hash=_capture_scope(request), payload=payload,
            uploads=request.FILES.dict(), source=source,
            edit_submission_id=sessions.get(str(payload.get("edit_token", ""))),
            request_key=request.headers.get("Idempotency-Key"),
        )
        if result["edit_token"]:
            sessions[result["edit_token"]] = result["submission_id"]
            request.session["public_form_edit_tokens"] = dict(list(sessions.items())[-20:])
        return JsonResponse(result, status=201 if result["created"] and not result["replayed"] else 200)
    except (json.JSONDecodeError, ValidationError) as error:
        return JsonResponse({"errors": getattr(error, "message_dict", {"detail": str(error)}),
                             "code": getattr(error, "error_code", "invalid_capture")}, status=getattr(error, "status", 400))
    except OperationalError:
        # No accepted receipt is returned when the database commit fails.
        response = JsonResponse({"errors": {"detail": "The response could not be committed. Retry with the same request_id."}, "code": "capture_unavailable"}, status=503)
        response["Retry-After"] = "1"
        return response


def public_form(request, org_slug, form_slug):
    organization = get_object_or_404(Organization, slug=org_slug, is_archived=False)
    form = get_object_or_404(DynamicForm, organization=organization, slug=form_slug, status=DynamicForm.STATUS_ACTIVE)
    if not can_respond_to_form(request.user, form):
        if not request.user.is_authenticated and request.method == "GET":
            return redirect_to_login(request.get_full_path())
        if request.content_type == "application/json":
            return JsonResponse({"errors": {"detail": "This account does not have access to this form."}}, status=403)
        return render(request, "forms/form_access_denied.html", {"organization": organization, "form": form}, status=403)
    if request.method == "POST":
        return _capture_response(request, form, source="browser")
    _capture_scope(request)  # Establish guest identity before a potentially lost POST response.
    revision = form.current_revision
    schema = normalize_schema(revision.schema, organization)
    initial_record = None
    if request.GET.get("record"):
        from datasets.models import Record
        from datasets.permissions import require_dataset
        if revision.destination_schema_id is None:
            raise Http404()
        dataset = revision.destination_schema.dataset
        require_dataset(request.user, dataset, "read")
        require_dataset(request.user, dataset, "write")
        try:
            identity = django_forms.UUIDField().clean(request.GET["record"])
        except ValidationError:
            raise Http404()
        record = get_object_or_404(Record, pk=identity, dataset=dataset, is_archived=False)
        if record.schema_version_id != revision.destination_schema_id or dataset.current_schema.pk != revision.destination_schema_id:
            return HttpResponse("The dataset definition changed. Review and republish the collection mapping before updating this record.", status=409)
        initial_record = {"id": str(record.pk), "version": record.version,
                          "data": {source: record.data[target] for source, target in revision.field_mapping.items() if target in record.data}}
    field_catalogs = {field["id"]: field["catalog_id"] for field in schema["fields"] if field["type"] == "item_cards"}
    menu_items = list(CatalogItem.objects.filter(catalog_id__in=field_catalogs.values(), catalog__organization=organization, is_available=True).values("id", "catalog_id", "name", "category", "description", "price"))
    return render(request, "forms/public_form.html", {
        "organization": organization, "form": form, "revision": revision,
        "initial_record": initial_record,
        "menu_items": menu_items, "field_catalogs": field_catalogs,
        "portfolio_assistance_enabled": bool(request.user.is_authenticated and UserPortfolio.objects.filter(user=request.user, use_for_form_assistance=True).exists()),
    })


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_forms(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    if request.method == "GET":
        require_membership(request.user, organization)
        forms = visible_forms(request.user, organization)
        return Response(DynamicFormSerializer(forms, many=True, context={"request": request}).data)
    require_membership(request.user, organization, manage=True)
    if organization.is_archived:
        return Response({"detail": "Restore this organization before changing forms."}, status=400)
    serializer = DynamicFormSerializer(data=request.data, context={"request": request, "organization": organization})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        form = serializer.save(organization=organization, created_by=request.user)
    return Response(DynamicFormSerializer(form, context={"request": request}).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_detail(request, form_id):
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    membership = require_form_manage(request.user, form)
    privileged = membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER)
    if not privileged and ({"visibility", "access_emails", "access_departments", "response_limit", "destination_schema", "field_mapping"} & set(request.data.keys())):
        return Response({"detail": "Only an organization manager or admin can change respondent access."}, status=403)
    if form.organization.is_archived:
        return Response({"detail": "Restore this organization before changing forms."}, status=400)
    if request.method == "DELETE":
        if not privileged:
            return Response({"detail": "Only an organization manager or admin can delete forms."}, status=403)
        if form.submissions.exists():
            return Response({"detail": "Archive forms with responses to preserve their records."}, status=409)
        form.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = DynamicFormSerializer(form, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        form = serializer.save()
    return Response(DynamicFormSerializer(form, context={"request": request}).data)


@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_editors(request, form_id):
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    membership = require_membership(request.user, form.organization)
    if membership.role not in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return Response({"detail": "Only an organization manager or admin can change form editors."}, status=403)
    if form.organization.is_archived:
        return Response({"detail": "Restore this organization before changing form editors."}, status=400)
    editor_ids = request.data.get("editors", [])
    if not isinstance(editor_ids, list) or len(editor_ids) > 100:
        return Response({"detail": "Choose up to 100 organization members as form editors."}, status=400)
    try:
        editor_ids = {int(editor_id) for editor_id in editor_ids}
    except (TypeError, ValueError):
        return Response({"detail": "Editor IDs must be valid account IDs."}, status=400)
    memberships = list(form.organization.memberships.filter(user__is_active=True, user_id__in=editor_ids).select_related("user"))
    if len(memberships) != len(editor_ids):
        return Response({"detail": "Every form editor must be an active member of this organization."}, status=400)
    form.editors.set([item.user for item in memberships])
    return Response({"success": True, "editors": [item.user.email or item.user.username for item in memberships]})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_transfer(request, form_id):
    """Reassign a form owner within its organization."""
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    source_membership = require_membership(request.user, form.organization)
    if source_membership.role != OrganizationMembership.ROLE_ADMIN:
        return Response({"detail": "Only an organization admin can transfer a form."}, status=403)
    if form.organization.is_archived:
        return Response({"detail": "Restore this organization before transferring forms."}, status=400)
    if request.data.get("organization") != form.organization.slug:
        return Response({"detail": "Choose an owner in this organization. Cross-organization moves are not available."}, status=403)
    target = get_object_or_404(Organization, slug=request.data.get("organization", ""), is_archived=False)
    target_membership = OrganizationMembership.objects.filter(
        organization=target, user=request.user, role=OrganizationMembership.ROLE_ADMIN
    ).first()
    if not target_membership:
        return Response({"detail": "You must be an admin of the destination organization."}, status=403)
    new_owner_membership = get_object_or_404(
        OrganizationMembership.objects.select_related("user"),
        pk=request.data.get("owner_membership"), organization=target,
        role__in=(OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER),
    )
    form.created_by = new_owner_membership.user
    form.save(update_fields=("created_by", "updated_at"))
    return Response({
        "success": True,
        "organization": target.name,
        "owner": new_owner_membership.user.email or new_owner_membership.user.username,
        "url": f"/org/{target.slug}/{form.slug}/",
    })


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_submissions(request, form_id):
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    if request.method == "POST":
        return _capture_response(request, form, source="api")
    require_form_records(request.user, form)
    data = [{"id": item.pk, "data": item.data, "submitted_at": item.created_at,
             "revision_id": item.collection_revision_id, "version": item.version}
            for item in form.submissions.all()[:500]]
    return Response(data)


@api_view(["GET"])
def api_collection_revisions(request, form_id):
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    require_form_records(request.user, form)
    return Response(list(form.revisions.values("id", "number", "schema_dialect", "title", "description", "purpose", "schema", "destination_schema_id", "field_mapping", "is_legacy_baseline", "created_at")[:200]))


@api_view(["GET"])
def api_submission_history(request, submission_id):
    submission = get_object_or_404(FormSubmission.objects.select_related("form__organization", "collection_revision"), pk=submission_id)
    require_form_records(request.user, submission.form)
    revision = submission.collection_revision
    return Response({
        "submission_id": submission.pk, "version": submission.version,
        "collection_revision": {"id": revision.pk, "number": revision.number, "schema": revision.schema, "schema_dialect": revision.schema_dialect, "is_legacy_baseline": revision.is_legacy_baseline} if revision else None,
        "history": list(submission.revisions.values("number", "data", "respondent_name", "respondent_email", "status", "attachments", "item_selections", "record_snapshot", "event", "source", "actor_id", "created_at")[:200]),
    })


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_classify(request):
    text = request.data.get("text", "")
    fields = request.data.get("fields", [])
    if not isinstance(fields, list) or not fields:
        return Response({"detail": "fields must be a non-empty list."}, status=400)
    result = classify_remote([str(text)], fields)
    return Response({"success": True, "model": "remote-system1", "classifications": result} if result else classify_text(text, fields))


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([])
@throttle_classes([PublicClassificationThrottle])
def api_public_classify(request, form_id):
    form = get_object_or_404(
        DynamicForm,
        pk=form_id,
        status=DynamicForm.STATUS_ACTIVE,
        organization__is_archived=False,
    )
    require_form_response(request.user, form)
    text = request.data.get("text", "")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return Response({"detail": "Enter a response of up to 2,000 characters."}, status=400)
    fields = form.schema.get("fields", [])
    if request.data.get("use_saved_profile") is True and request.user.is_authenticated:
        portfolio = UserPortfolio.objects.filter(user=request.user, use_for_form_assistance=True).first()
        if portfolio:
            # Only user-entered profile facts are used. Personal document files are never read here.
            facts = {"phone_number": portfolio.phone_number, **(portfolio.profile_data or {})}
            text += "\n" + "; ".join(f"{key.replace('_', ' ')}: {value}" for key, value in facts.items() if value not in (None, "", [], {}))
    return Response(classify_text(text, fields))


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_draft(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    if organization.is_archived:
        return Response({"detail": "Restore this organization before drafting forms."}, status=400)
    prompt = str(request.data.get("prompt", "")).strip()
    if not prompt:
        return Response({"detail": "Describe the form you want to create."}, status=400)
    mode = request.data.get("mode", "form")
    if mode not in {"form", "questions"}:
        return Response({"detail": "Unsupported drafting mode."}, status=400)
    form_id = request.data.get("form_id")
    if mode == "questions" and form_id:
        target_form = get_object_or_404(DynamicForm, pk=form_id, organization=organization)
        require_form_manage(request.user, target_form)
    elif membership.role not in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return Response({"detail": "An organization manager or admin is required to draft new forms."}, status=403)
    profile = AIConfiguration.for_organization(organization)
    category = organization.category_display
    existing_forms = []
    for existing_form in organization.forms.exclude(status=DynamicForm.STATUS_ARCHIVED).order_by("-updated_at")[:12]:
        existing_forms.append({
            "title": existing_form.title,
            "description": existing_form.description[:500],
            "purpose": existing_form.purpose,
            "fields": [
                {"label": field.get("label", ""), "type": field.get("type", "text")}
                for field in (existing_form.schema or {}).get("fields", [])[:30]
            ],
        })
    organization_context = {
        "name": organization.name,
        "category": category,
        "description": organization.description[:1000],
        "purpose": organization.purpose,
        "details": organization.profile_data or {},
        "existing_forms": existing_forms,
        "menu_items": [],
    }
    organization_context["menu_items"] = list(CatalogItem.objects.filter(catalog__organization=organization, is_available=True).values("id", "name", "category", "description", "price")[:50])
    for item in organization_context["menu_items"]:
        item["price"] = str(item["price"])
    request_context = {
        "request": prompt,
        "organization": organization_context,
    }
    if mode == "questions":
        current_form = request.data.get("current_form", {})
        if not isinstance(current_form, dict):
            current_form = {}
        request_context["current_form"] = {
            "title": str(current_form.get("title", ""))[:200],
            "description": str(current_form.get("description", ""))[:1000],
            "purpose": str(current_form.get("purpose", ""))[:200],
            "questions": [
                {"id": str(field.get("id", ""))[:80], "label": str(field.get("label", ""))[:200],
                 "type": str(field.get("type", "text"))[:30]}
                for field in current_form.get("questions", [])[:100]
                if isinstance(field, dict)
            ] if isinstance(current_form.get("questions", []), list) else [],
        }
    contextual_prompt = json.dumps(request_context, ensure_ascii=False, default=str)
    try:
        if mode == "questions":
            generated = generate_json(
                profile, contextual_prompt,
                "Suggest additional, context-specific form questions using the request, current form, and organization metadata. Treat form creation as one coherent set of questions: do not repeat existing questions, avoid generic Name/Details fields unless essential, and ask only for information needed for this specific workflow. Return JSON only: {fields}. Each field needs id, label, type, required. Allowed types: text, textarea, number, email, tel, select, radio, date, checkbox, rating.",
            )
            fields = generated.get("fields", [])
            validate_form_schema({"fields": fields})
            reserved = {str(field.get("id", "")) for field in request_context["current_form"]["questions"]}
            for field in fields:
                base_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(field["id"])).strip("_-") or "question"
                if not base_id[0].isalpha():
                    base_id = f"question_{base_id}"
                candidate, suffix = base_id[:80], 2
                while candidate in reserved:
                    tail = f"_{suffix}"
                    candidate = f"{base_id[:80-len(tail)]}{tail}"
                    suffix += 1
                field["id"] = candidate
                reserved.add(candidate)
            validate_form_schema({"fields": fields})
            return Response({"success": True, "form": {"fields": fields}})
        generated = generate_json(
            profile, contextual_prompt,
            "Draft a coherent, contextual intake form using the user's request and organization metadata. Use the organization's category, purpose, profile details, available menu items (including their names and prices), and existing forms when relevant. A form is a cohesive set of questions: avoid generic Name/Details fields unless essential, avoid duplicating existing forms, and do not invent organization facts or menu items. Return JSON only: {title, description, purpose, fields}. "
        "Each field needs id, label, type, required. Allowed types: text, textarea, number, email, tel, select, radio, date, checkbox, rating, file, item_cards.",
        )
        validate_form_schema({"fields": generated.get("fields", [])})
        return Response({"success": True, "form": generated})
    except Exception:
        if mode == "questions":
            return Response({"success": True, "source": "starter-questions", "form": {"fields": [
                {"id": "workflow_details", "label": f"Details for {category.lower()} request", "type": "textarea", "required": True},
            ]}})
        return Response({"success": True, "source": "deterministic-template", "form": {
            "title": prompt[:120], "description": prompt, "purpose": organization.purpose,
            "fields": [{"id": "name", "label": "Name", "type": "text", "required": True},
                       {"id": "details", "label": "Details", "type": "textarea", "required": True}],
        }})


def _xlsx_rows(upload):
    """Read the first worksheet of an .xlsx file using Python's standard library."""
    spreadsheet_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    document_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(upload) as archive:
        entries = archive.infolist()
        if (
            len(entries) > _MAX_XLSX_ENTRIES
            or sum(entry.file_size for entry in entries) > _MAX_XLSX_EXPANDED_SIZE
            or any(entry.file_size > _MAX_XLSX_ENTRY_SIZE for entry in entries)
        ):
            raise ValueError("The Excel file expands beyond the import size limits.")
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = ["".join(text.text or "" for text in item.findall(f".//{{{spreadsheet_ns}}}t")) for item in root.findall(f"{{{spreadsheet_ns}}}si")]
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find(f".//{{{spreadsheet_ns}}}sheet")
        if sheet is None:
            return []
        relationship_id = sheet.attrib.get(f"{{{document_ns}}}id")
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next((rel.attrib.get("Target") for rel in relationships.findall(f"{{{package_ns}}}Relationship") if rel.attrib.get("Id") == relationship_id), None)
        if not target:
            return []
        sheet_path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        root = ElementTree.fromstring(archive.read(sheet_path))
        rows = []
        for row_node in root.findall(f".//{{{spreadsheet_ns}}}sheetData/{{{spreadsheet_ns}}}row"):
            if len(rows) >= _MAX_XLSX_ROWS:
                raise ValueError(f"The Excel file can contain at most {_MAX_XLSX_ROWS} rows.")
            row = []
            for cell in row_node.findall(f"{{{spreadsheet_ns}}}c"):
                address = re.match(r"([A-Z]+)", cell.attrib.get("r", "A1"))
                column = 0
                for letter in address.group(1) if address else "A":
                    column = column * 26 + ord(letter) - 64
                column -= 1
                if column >= _MAX_XLSX_COLUMNS:
                    raise ValueError(f"The Excel file can contain at most {_MAX_XLSX_COLUMNS} columns.")
                while len(row) <= column:
                    row.append("")
                value_node = cell.find(f"{{{spreadsheet_ns}}}v")
                value = value_node.text if value_node is not None else ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared_strings[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(text.text or "" for text in cell.findall(f".//{{{spreadsheet_ns}}}t"))
                row[column] = value or ""
            rows.append(row)
        return rows


def _schema_from_table(rows):
    if not rows:
        raise ValueError("The uploaded file contains no questions.")
    normalized = [str(value or "").strip() for value in rows[0]]
    header_keys = {value.lower().replace(" ", "_"): index for index, value in enumerate(normalized)}
    has_headers = bool(set(header_keys) & {"label", "question", "name", "title", "type", "required", "options"})
    if has_headers:
        headers, data_rows = header_keys, rows[1:]
    else:
        headers, data_rows = {"label": 0}, rows
    fields = []
    used = set()
    for row in data_rows:
        if not row or not any(str(value or "").strip() for value in row):
            continue
        def cell(*keys, default=""):
            index = next((headers[key] for key in keys if key in headers), None)
            return str(row[index] if index is not None and index < len(row) else default).strip()
        label = cell("label", "question", "name", "title")
        if not label:
            continue
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_-") or "question"
        if not base[0].isalpha():
            base = f"question_{base}"
        field_id, suffix = base[:80], 2
        while field_id in used:
            tail = f"_{suffix}"
            field_id, suffix = f"{base[:80-len(tail)]}{tail}", suffix + 1
        used.add(field_id)
        kind = cell("type").lower() or "text"
        if kind not in {"text", "textarea", "number", "email", "tel", "select", "radio", "date", "checkbox", "rating", "file", "item_cards"}:
            kind = "text"
        required = cell("required").lower() in {"1", "true", "yes", "required"}
        field = {"id": field_id, "label": label[:200], "type": kind, "required": required}
        if kind in {"select", "radio"}:
            field["options"] = [option.strip() for option in re.split(r"[,;|]", cell("options")) if option.strip()]
        fields.append(field)
    schema = {"fields": fields}
    validate_form_schema(schema)
    return schema


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_schema_import(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    form_id = request.data.get("form_id")
    if form_id:
        target_form = get_object_or_404(DynamicForm, pk=form_id, organization=organization)
        require_form_manage(request.user, target_form)
    elif membership.role not in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return Response({"detail": "An organization manager or admin is required to import a new form schema."}, status=403)
    upload = request.FILES.get("file")
    if not upload or upload.size > 2 * 1024 * 1024:
        return Response({"detail": "Choose a CSV, Excel (.xlsx), or JSON schema file up to 2 MB."}, status=400)
    suffix = upload.name.lower().rsplit(".", 1)[-1] if "." in upload.name else ""
    try:
        if suffix == "json":
            payload = json.loads(upload.read().decode("utf-8-sig"))
            schema = payload if isinstance(payload, dict) else {"fields": payload}
            validate_form_schema(schema)
        elif suffix == "csv":
            rows = list(csv.reader(io.StringIO(upload.read().decode("utf-8-sig"))))
            schema = _schema_from_table(rows)
        elif suffix == "xlsx":
            schema = _schema_from_table(_xlsx_rows(upload))
        else:
            return Response({"detail": "Supported schema files are CSV, Excel (.xlsx), and JSON."}, status=400)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError, IndexError, zipfile.BadZipFile, ElementTree.ParseError, ValidationError) as error:
        message = error.messages[0] if isinstance(error, ValidationError) else str(error)
        return Response({"detail": message or "Could not read this schema file."}, status=400)
    return Response({"success": True, "schema": schema})


@login_required
def submission_attachment(request, attachment_id):
    attachment = get_object_or_404(SubmissionAttachment.objects.select_related("submission__form"), pk=attachment_id)
    require_form_records(request.user, attachment.submission.form)
    try:
        stream = attachment.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404
    return FileResponse(stream, as_attachment=True, filename=attachment.original_name)


@login_required
def organization_submissions(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug, is_archived=False)
    membership = require_membership(request.user, organization)
    can_review = membership.role in {OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER}
    now = timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    accessible_forms = visible_forms(request.user, organization)
    recent = organization.submissions.filter(form__in=accessible_forms)
    form_id = request.GET.get("form", "")
    selected_form = None
    if form_id:
        from uuid import UUID
        from django.http import Http404
        try:
            form_id = UUID(form_id)
        except (ValueError, TypeError):
            raise Http404
        selected_form = get_object_or_404(accessible_forms, pk=form_id)
        recent = recent.filter(form=selected_form)

    period = request.GET.get("period", "30d")
    if period not in {"24h", "7d", "30d", "90d"}:
        period = "30d"
    grain = request.GET.get("grain", "day")
    if grain not in {"hour", "day", "shift"}:
        grain = "day"
    selected_status = request.GET.get("status", "")
    valid_statuses = {value for value, _label in FormSubmission.STATUS_CHOICES}
    if selected_status not in valid_statuses:
        selected_status = ""

    if grain == "hour":
        period = "24h"
        recent = recent.filter(created_at__gte=now - timedelta(hours=24))
        period_label = "Past 24 hours"
    elif period == "24h":
        recent = recent.filter(created_at__gte=now - timedelta(hours=24))
        first_day = (local_now - timedelta(hours=24)).date()
        days = (today - first_day).days + 1
        period_label = "Past 24 hours"
    else:
        days = {"7d": 7, "30d": 30, "90d": 90}[period]
        first_day = today - timedelta(days=days - 1)
        recent = recent.filter(created_at__date__gte=first_day, created_at__date__lte=today)
        period_label = f"Past {days} days"
    pending_count = recent.filter(status=FormSubmission.STATUS_PENDING).count()
    if selected_status:
        recent = recent.filter(status=selected_status)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{organization.slug}-submissions.csv"'
        writer = csv.writer(response)
        writer.writerow(("Submission ID", "Received at", "Form", "Respondent", "Email", "Status", "Response JSON", "Collection revision", "Response version", "Definition provenance"))
        for item in recent.select_related("form", "submitted_by", "collection_revision").order_by("-created_at")[:5000]:
            writer.writerow((item.pk, timezone.localtime(item.created_at).isoformat(), _safe_csv_cell(item.collection_revision.title if item.collection_revision else item.form.title), _safe_csv_cell(item.respondent_name), _safe_csv_cell(item.respondent_email), item.get_status_display(), json.dumps(item.data, ensure_ascii=False), item.collection_revision.number if item.collection_revision else "", item.version, "Legacy baseline" if item.collection_revision and item.collection_revision.is_legacy_baseline else "Captured definition"))
        return response

    total_count = recent.count()
    identified = set()
    for submission_id, user_id, email in recent.values_list("pk", "submitted_by_id", "respondent_email"):
        email = (email or "").strip().lower()
        if email:
            identified.add(f"email:{email}")
        elif user_id:
            identified.add(f"user:{user_id}")

    if grain == "hour":
        start_hour = (local_now - timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
        points = []
        for offset in range(24):
            bucket = start_hour + timedelta(hours=offset)
            points.append({"key": bucket.isoformat(), "label": bucket.strftime("%H:%M"), "detail": bucket.strftime("%b %d, %H:00"), "count": 0})
        chart_description = "Hourly submissions over the past 24 hours"
    elif grain == "shift":
        points = [{"key": label, "label": label, "detail": f"{label} shift · {period_label.lower()}", "count": 0} for label in ("Morning", "Afternoon", "Evening")]
        chart_description = f"Submissions by shift · {period_label.lower()} (morning 06–12, afternoon 12–18, evening 18–06)"
    else:
        points = []
        for day_offset in range(days):
            day = first_day + timedelta(days=day_offset)
            points.append({"key": day.isoformat(), "label": day.strftime("%b %-d"), "detail": day.strftime("%b %d, %Y"), "count": 0})
        chart_description = "Daily submissions over the past 24 hours" if period == "24h" else f"Daily submissions over the past {days} days"

    # Build one trend per form so the chart remains useful when an organization
    # has several forms. Keep four named series and combine the rest as Other.
    form_totals = list(recent.values("form_id", "form__title").annotate(total=Count("pk")).order_by("-total", "form__title"))
    counts_by_form = {}
    if grain == "hour":
        buckets = recent.annotate(bucket=TruncHour("created_at")).values("form_id", "bucket").annotate(total=Count("pk"))
        for row in buckets:
            bucket = timezone.localtime(row["bucket"]).replace(minute=0, second=0, microsecond=0).isoformat()
            counts_by_form.setdefault(row["form_id"], {})[bucket] = row["total"]
    elif grain == "shift":
        buckets = recent.annotate(hour=ExtractHour("created_at")).values("form_id", "hour").annotate(total=Count("pk"))
        for row in buckets:
            hour = row["hour"]
            shift = "Morning" if 6 <= hour < 12 else "Afternoon" if 12 <= hour < 18 else "Evening"
            counts = counts_by_form.setdefault(row["form_id"], {})
            counts[shift] = counts.get(shift, 0) + row["total"]
    else:
        buckets = recent.annotate(bucket=TruncDate("created_at")).values("form_id", "bucket").annotate(total=Count("pk"))
        for row in buckets:
            counts_by_form.setdefault(row["form_id"], {})[row["bucket"].isoformat()] = row["total"]

    named_forms = form_totals[:4]
    chart_series = []
    for index, row in enumerate(named_forms):
        values = [counts_by_form.get(row["form_id"], {}).get(point["key"], 0) for point in points]
        chart_series.append({"name": row["form__title"], "values": values, "class_name": f"series-{index}"})
    if len(form_totals) > len(named_forms):
        other_ids = {row["form_id"] for row in form_totals[len(named_forms):]}
        values = [sum(counts_by_form.get(form_pk, {}).get(point["key"], 0) for form_pk in other_ids) for point in points]
        chart_series.append({"name": "Other forms", "values": values, "class_name": "series-other"})

    peak = max((value for series in chart_series for value in series["values"]), default=0)
    for point_index, point in enumerate(points):
        point["x"] = round(point_index * 1000 / max(len(points) - 1, 1))
        point["count"] = sum(series["values"][point_index] for series in chart_series)
    for series in chart_series:
        coordinates = []
        series["markers"] = []
        for point_index, point in enumerate(points):
            value = series["values"][point_index]
            y = 176 - round(value / peak * 148) if peak else 176
            coordinates.append(f"{point['x']},{y}")
            series["markers"].append({"x": point["x"], "y": y, "value": value, "detail": point["detail"]})
        series["svg_points"] = " ".join(coordinates)
    trend = points

    if request.method == "POST" and request.POST.get("action") == "update-status":
        if not can_review:
            raise PermissionDenied("Only organization admins and managers can update submission status.")
        submission = get_object_or_404(recent, pk=request.POST.get("submission_id"))
        status = request.POST.get("status", "")
        if status not in valid_statuses:
            messages.error(request, "Choose a valid submission status.")
        else:
            try:
                change_submission_status(submission_id=submission.pk, user=request.user, status=status, expected_version=request.POST.get("expected_version"))
            except ValidationError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, "Submission status updated.")
        query = request.GET.urlencode()
        url = reverse("forms:all-submissions", kwargs={"org_slug": organization.slug})
        return redirect(f"{url}?{query}" if query else url)

    export_params = request.GET.copy()
    export_params["export"] = "csv"
    records_mode = request.GET.get("view") == "records"
    pending_params = request.GET.copy()
    pending_params.pop("export", None)
    pending_params["status"] = FormSubmission.STATUS_PENDING
    if records_mode:
        pending_params["view"] = "records"
    submissions = list(recent.select_related("form", "submitted_by", "collection_revision").prefetch_related("attachments", "revisions").order_by("-created_at")[:250])
    _prepare_response_history(submissions)
    return render(request, "forms/all_submissions.html", {
        "organization": organization,
        "submissions": submissions,
        "total_count": total_count,
        "identified_respondents": len(identified),
        "active_forms_count": accessible_forms.filter(status="active").count(),
        "daily_rate": round(total_count / {"24h": 1, "7d": 7, "30d": 30, "90d": 90}[period], 2),
        "trend": trend,
        "chart_series": chart_series,
        "records_mode": records_mode,
        "view_query": "view=records" if records_mode else "",
        "chart_description": chart_description,
        "selected_period": period,
        "selected_grain": grain,
        "selected_status": selected_status,
        "period_label": period_label,
        "status_choices": FormSubmission.STATUS_CHOICES,
        "can_review": can_review,
        "form_choices": accessible_forms,
        "form_count": accessible_forms.count(),
        "selected_form": selected_form,
        "pending_count": pending_count,
        "pending_query": pending_params.urlencode(),
        "export_query": export_params.urlencode(),
    })


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def catalog_items(request):
    organization = get_object_or_404(Organization, slug=request.headers.get("X-Organization") or request.GET.get("org") or request.session.get("active_organization_slug"))
    require_membership(request.user, organization)
    from .serializers import CatalogItemSerializer
    return Response(CatalogItemSerializer(CatalogItem.objects.filter(catalog__organization=organization, is_available=True), many=True).data)
