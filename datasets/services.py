"""Dataset commands and collection projections at the existing local data home."""
import copy
import hashlib
import json
import re
import uuid
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.db.models.fields.json import KeyTextTransform

from forms.services import validate_form_schema, validate_submission
from .models import Dataset, DatasetGrant, Record, RecordCommandReceipt, RecordRevision
from .permissions import require_dataset

RECORD_TYPES = {"text", "textarea", "number", "email", "tel", "select", "radio", "date", "checkbox", "rating", "record_reference"}


def lookup_entries(dataset, user, query="", *, limit=50):
    require_dataset(user, dataset, "lookup")
    if dataset.is_archived or dataset.organization.is_archived:
        return []
    records = dataset.records.filter(is_archived=False).order_by("id")
    if dataset.label_field:
        records = records.annotate(lookup_label=KeyTextTransform(dataset.label_field, "data"))
        if query:
            records = records.filter(lookup_label__icontains=query[:100])
        return [{"id": str(row.pk), "label": str(row.lookup_label or row.pk)} for row in records[:limit]]
    if query:
        records = records.filter(pk=as_uuid(query, "record ID"))
    return [{"id": str(row.pk), "label": str(row.pk)} for row in records[:limit]]


def set_grants(dataset_id, user, rows):
    from organizations.models import OrganizationMembership
    if not isinstance(rows, list) or len(rows) > 100:
        raise DatasetError("Provide up to 100 dataset membership grants.")
    with transaction.atomic():
        dataset = lock_dataset(dataset_id)
        require_dataset(user, dataset, "manage")
        if dataset.organization.is_archived:
            raise DatasetError("Restore the organization before changing grants.", status=409)
        seen = set()
        memberships = []
        for row in rows:
            if not isinstance(row, dict) or set(row) - {"membership_id", "read", "write", "lookup"}:
                raise DatasetError("Use membership_id and read/write/lookup flags.")
            identity = row.get("membership_id")
            if isinstance(identity, bool) or not isinstance(identity, int) or identity in seen:
                raise DatasetError("Choose distinct valid memberships.")
            if any(not isinstance(row.get(action, False), bool) for action in ("read", "write", "lookup")):
                raise DatasetError("Dataset grant flags must be true or false.")
            membership = OrganizationMembership.objects.filter(pk=identity, organization=dataset.organization).first()
            if not membership:
                raise DatasetError("Choose memberships from this organization.")
            seen.add(identity)
            memberships.append((membership, row))
        dataset.grants.exclude(membership_id__in=seen).delete()
        for membership, row in memberships:
            DatasetGrant.objects.update_or_create(dataset=dataset, membership=membership, defaults={"can_" + action: row.get(action, False) for action in ("read", "write", "lookup")})


class DatasetError(ValidationError):
    def __init__(self, message, *, status=400, code="invalid_record"):
        self.status = status
        self.error_code = code
        super().__init__({"detail": message})


def as_uuid(value, label="identifier"):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise DatasetError(f"Choose a valid {label}.")


def validate_reference_schema(schema, organization):
    for field in schema["fields"]:
        if field["type"] == "record_reference":
            dataset_id = as_uuid(field.get("dataset_id"), "lookup dataset")
            if not Dataset.objects.filter(pk=dataset_id, organization=organization).exists():
                raise ValidationError({field["id"]: "Choose a lookup dataset from this organization."})


def validate_dataset_schema(schema, organization):
    validate_form_schema(schema)
    if any(field["type"] not in RECORD_TYPES for field in schema["fields"]):
        raise ValidationError("Dataset values support scalar fields and record references. Files and item-card behavior remain collection capabilities.")
    validate_reference_schema(schema, organization)
    return schema


def validate_binding(form):
    mapping = form.field_mapping
    if not isinstance(mapping, dict):
        raise ValidationError("Use a source-field to dataset-field mapping object.")
    if not form.destination_schema_id:
        if mapping:
            raise ValidationError("Choose a destination dataset before mapping fields.")
        return
    target = form.destination_schema
    if target.dataset.organization_id != form.organization_id:
        raise ValidationError("The destination dataset must belong to this organization.")
    source_fields = {field["id"]: field for field in form.schema.get("fields", [])}
    target_fields = {field["id"]: field for field in target.schema["fields"]}
    if not mapping:
        raise ValidationError("Map at least one collection field to the destination dataset.")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in mapping.items()):
        raise ValidationError("Mappings must contain field IDs as text.")
    if len(set(mapping.values())) != len(mapping):
        raise ValidationError("Map each destination field only once.")
    for source_id, target_id in mapping.items():
        source, destination = source_fields.get(source_id), target_fields.get(target_id)
        if not source or not destination:
            raise ValidationError("A mapped field is missing from the selected definitions.")
        if source["type"] != destination["type"] or source["type"] not in RECORD_TYPES:
            raise ValidationError(f"Mapped fields {source_id} and {target_id} must have the same supported type.")
        if source["type"] == "record_reference" and as_uuid(source["dataset_id"]) != as_uuid(destination["dataset_id"]):
            raise ValidationError("Mapped record references must use the same lookup dataset.")
    missing = {field["id"] for field in target_fields.values() if field.get("required")} - set(mapping.values())
    if missing:
        raise ValidationError(f"Map the required dataset fields: {', '.join(sorted(missing))}.")


def validate_reference_values(schema, data, user, organization, *, prior=None):
    for field in schema["fields"]:
        value = data.get(field["id"])
        if field["type"] != "record_reference" or value in (None, ""):
            continue
        record_id = as_uuid(value, "record reference")
        if prior is not None and str(prior.get(field["id"])) == str(record_id):
            data[field["id"]] = str(record_id)
            continue
        dataset = Dataset.objects.get(pk=as_uuid(field["dataset_id"]), organization=organization)
        require_dataset(user, dataset, "lookup")
        if dataset.is_archived or not Record.objects.filter(pk=record_id, dataset=dataset, is_archived=False).exists():
            raise ValidationError({field["id"]: "Choose an available record from the permitted lookup dataset."})
        data[field["id"]] = str(record_id)


def validate_values(definition, data, user, *, prior=None):
    if not isinstance(data, dict):
        raise DatasetError("Record values must be a JSON object.")
    values = validate_submission(SimpleNamespace(schema=definition.schema), data)
    validate_reference_values(definition.schema, values, user, definition.dataset.organization, prior=prior)
    for field in definition.schema["fields"]:
        value = values.get(field["id"])
        if field["type"] in {"number", "rating"} and value not in (None, ""):
            number = float(value)
            values[field["id"]] = int(number) if number.is_integer() else number
    return values


def lock_dataset(dataset_id):
    # A write before reading serializes commands/schema edits on SQLite too.
    Dataset.objects.filter(pk=dataset_id).update(mutation_sequence=F("mutation_sequence") + 1)
    return Dataset.objects.select_related("organization").get(pk=dataset_id)


def _record_version_matches(value, expected):
    return not isinstance(value, bool) and str(value) == str(expected)


def persist_record(dataset, definition, data, user, *, record=None, source, submission=None, is_archived=False):
    if record is None:
        record = Record(dataset=dataset, schema_version=definition, created_by=user if getattr(user, "is_authenticated", False) else None)
    else:
        record.version += 1
    record.schema_version = definition
    record.data = copy.deepcopy(data)
    record.is_archived = is_archived
    record.save()
    RecordRevision.objects.create(
        record=record, number=record.version, schema_version=definition, data=copy.deepcopy(data),
        is_archived=is_archived, actor=user if getattr(user, "is_authenticated", False) else None,
        source=source, source_submission=submission,
    )
    return record


def write_record(*, dataset_id, user, payload, record_id=None, source="api"):
    """Explicit create/replace command, with current schema and version checks."""
    if not isinstance(payload, dict):
        raise DatasetError("Provide a record command object.")
    key = payload.get("request_id")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key):
        raise DatasetError("Provide a request_id of up to 128 letters, digits, underscores, or hyphens.")
    try:
        fingerprint = hashlib.sha256(json.dumps({"record_id": str(record_id) if record_id else None, "payload": payload}, sort_keys=True, allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError):
        raise DatasetError("Provide valid finite JSON record values.")
    with transaction.atomic():
        dataset = lock_dataset(dataset_id)
        require_dataset(user, dataset, "write")
        if dataset.is_archived or dataset.organization.is_archived:
            raise DatasetError("Restore this dataset and organization before writing records.", status=409)
        prior_receipt = RecordCommandReceipt.objects.filter(dataset=dataset, actor=user, key=key).first()
        if prior_receipt:
            if prior_receipt.payload_hash != fingerprint:
                raise DatasetError("This request_id was used for a different record command.", status=409, code="request_conflict")
            return {**prior_receipt.response, "replayed": True}
        definition = dataset.current_schema
        if str(as_uuid(payload.get("schema_version_id"), "dataset schema version")) != str(definition.pk):
            raise DatasetError("The dataset definition changed. Reload and review the current fields.", status=409, code="schema_conflict")
        record = None
        if record_id is not None:
            record = Record.objects.filter(pk=as_uuid(record_id, "record"), dataset=dataset).first()
            if not record:
                raise DatasetError("This record does not belong to the dataset.", status=404)
            if not _record_version_matches(payload.get("expected_version"), record.version):
                raise DatasetError("The record changed. Reload before saving.", status=409, code="record_conflict")
        archived = payload.get("is_archived", record.is_archived if record else False)
        if not isinstance(archived, bool):
            raise DatasetError("is_archived must be true or false.")
        values = validate_values(definition, payload.get("data"), user, prior=record.data if record else None)
        record = persist_record(dataset, definition, values, user, record=record, source=source, is_archived=archived)
        result = {"id": str(record.pk), "dataset_id": str(dataset.pk), "version": record.version,
                  "schema_version_id": str(definition.pk), "created": record.version == 1, "replayed": False}
        RecordCommandReceipt.objects.create(dataset=dataset, actor=user, key=key, payload_hash=fingerprint, response=result)
        return result


def project_submission(submission, revision, values, user, payload):
    """Apply one pinned mapping in the enclosing capture transaction."""
    if not revision.destination_schema_id:
        if payload.get("record_id"):
            raise DatasetError("This collection has no record destination.")
        return None
    definition = revision.destination_schema
    dataset = lock_dataset(definition.dataset_id)
    if dataset.organization_id != submission.organization_id:
        raise DatasetError("The destination belongs to another organization.", status=403)
    current_binding = submission.form.destination_schema
    if current_binding is None or current_binding.dataset_id != dataset.pk:
        raise DatasetError("The collection's record destination changed. Ask its manager to review this response.", status=409, code="binding_conflict")
    if dataset.is_archived or dataset.organization.is_archived:
        raise DatasetError("The destination dataset is archived.", status=409)
    if dataset.current_schema.pk != definition.pk:
        raise DatasetError("The dataset schema changed. Its manager must review and republish the collection mapping.", status=409, code="schema_conflict")
    record = submission.record
    explicit_id = payload.get("record_id")
    if record and explicit_id and as_uuid(explicit_id) != record.pk:
        raise DatasetError("A response cannot be reassigned to another record.", status=409)
    if record is None and explicit_id:
        require_dataset(user, dataset, "write")
        record = Record.objects.filter(pk=as_uuid(explicit_id, "record"), dataset=dataset).first()
        if not record:
            raise DatasetError("Choose a record in the destination dataset.", status=404)
    if record:
        record.refresh_from_db()
        expected = payload.get("record_version", submission.record_version)
        if record.dataset_id != dataset.pk or record.schema_version_id != definition.pk or not _record_version_matches(expected, record.version):
            raise DatasetError("The linked record changed. Review its latest version before editing this response.", status=409, code="record_conflict")
        if record.is_archived:
            raise DatasetError("The linked record is archived.", status=409)
    data = {key: value for key, value in (record.data if record else {}).items() if key not in revision.field_mapping.values()}
    data.update({target: values[source] for source, target in revision.field_mapping.items() if source in values})
    data = validate_values(definition, data, user, prior=record.data if record else None)
    record = persist_record(dataset, definition, data, user, record=record, source="collection", submission=submission)
    submission.record, submission.record_version = record, record.version
    submission.save(update_fields=("record", "record_version"))
    return record
