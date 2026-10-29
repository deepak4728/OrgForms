import csv
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from rest_framework.decorators import api_view
from rest_framework.response import Response

from organizations.models import Organization
from organizations.permissions import require_membership
from forms.models import CatalogItem
from .forms import DatasetForm, RecordForm
from .models import Dataset, Record
from .permissions import dataset_permissions, require_dataset, visible_datasets
from .serializers import DatasetSerializer
from .services import DatasetError, lookup_entries, set_grants, write_record


def _dataset(identity):
    return get_object_or_404(Dataset.objects.select_related("organization"), pk=identity)


def _api_error(error):
    if isinstance(error, (IntegrityError, OperationalError)):
        return Response({"detail": "The write could not be committed. Retry with the same request_id.", "code": "write_unavailable"}, status=503)
    return Response({"errors": getattr(error, "message_dict", {"detail": error.messages}), "code": getattr(error, "error_code", "invalid_request")}, status=getattr(error, "status", 400))


def _dataset_data(dataset, user):
    permissions = dataset_permissions(user, dataset)
    data = {"id": str(dataset.pk), "name": dataset.name, "is_archived": dataset.is_archived, "permissions": permissions}
    if permissions["read"] or permissions["write"] or permissions["manage"]:
        data.update(DatasetSerializer(dataset).data)
    return data


def _record_data(record):
    return {"id": str(record.pk), "dataset_id": str(record.dataset_id), "schema_version_id": str(record.schema_version_id), "version": record.version, "data": record.data, "is_archived": record.is_archived, "updated_at": record.updated_at}


@api_view(["GET", "POST"])
def api_datasets(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    if request.method == "GET":
        return Response([_dataset_data(dataset, request.user) for dataset in visible_datasets(request.user, organization)[:100]])
    require_membership(request.user, organization, manage=True)
    if organization.is_archived:
        return Response({"detail": "Restore the organization before creating datasets."}, status=409)
    serializer = DatasetSerializer(data=request.data, context={"request": request, "organization": organization})
    serializer.is_valid(raise_exception=True)
    try:
        dataset = serializer.save(organization=organization, created_by=request.user)
    except (ValidationError, IntegrityError, OperationalError) as error:
        return _api_error(error)
    return Response(_dataset_data(dataset, request.user), status=201)


@api_view(["GET", "PATCH"])
def api_dataset(request, dataset_id):
    dataset = _dataset(dataset_id)
    if request.method == "GET":
        permissions = dataset_permissions(request.user, dataset)
        if not any(permissions.values()):
            require_dataset(request.user, dataset, "read")
        return Response(_dataset_data(dataset, request.user))
    require_dataset(request.user, dataset, "manage")
    if dataset.organization.is_archived:
        return Response({"detail": "Restore the organization before changing dataset definitions."}, status=409)
    serializer = DatasetSerializer(dataset, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    try:
        serializer.save()
    except (ValidationError, IntegrityError, OperationalError) as error:
        return _api_error(error)
    return Response(_dataset_data(dataset, request.user))


@api_view(["GET", "POST"])
def api_records(request, dataset_id):
    dataset = _dataset(dataset_id)
    if request.method == "POST":
        try:
            result = write_record(dataset_id=dataset.pk, user=request.user, payload=request.data)
        except (ValidationError, IntegrityError, OperationalError) as error:
            return _api_error(error)
        return Response(result, status=201 if result["created"] and not result["replayed"] else 200)
    require_dataset(request.user, dataset, "read")
    try:
        page = max(1, min(int(request.GET.get("page", 1)), 100000))
    except (ValueError, TypeError):
        return Response({"detail": "Use a valid page number."}, status=400)
    records = dataset.records.all()
    return Response({"count": records.count(), "page": page, "results": [_record_data(record) for record in records[(page-1)*50:page*50]]})


@api_view(["GET", "PATCH"])
def api_record(request, dataset_id, record_id):
    dataset = _dataset(dataset_id)
    if request.method == "PATCH":
        try:
            return Response(write_record(dataset_id=dataset.pk, user=request.user, payload=request.data, record_id=record_id))
        except (ValidationError, IntegrityError, OperationalError) as error:
            return _api_error(error)
    require_dataset(request.user, dataset, "read")
    record = get_object_or_404(Record, pk=record_id, dataset=dataset)
    return Response(_record_data(record))


@api_view(["GET"])
def api_record_history(request, dataset_id, record_id):
    dataset = _dataset(dataset_id)
    require_dataset(request.user, dataset, "read")
    record = get_object_or_404(Record, pk=record_id, dataset=dataset)
    return Response({"record": _record_data(record), "revisions": [
        {"number": entry.number, "schema_version_id": str(entry.schema_version_id), "schema": entry.schema_version.schema,
         "data": entry.data, "is_archived": entry.is_archived, "source": entry.source, "source_submission_id": entry.source_submission_id,
         "actor_id": entry.actor_id, "created_at": entry.created_at}
        for entry in record.revisions.select_related("schema_version")[:200]
    ]})


@api_view(["GET"])
def api_lookup(request, dataset_id):
    dataset = _dataset(dataset_id)
    try:
        return Response({"results": lookup_entries(dataset, request.user, request.GET.get("q", ""))})
    except ValidationError as error:
        return _api_error(error)


@api_view(["GET", "PUT"])
def api_grants(request, dataset_id):
    dataset = _dataset(dataset_id)
    require_dataset(request.user, dataset, "manage")
    if request.method == "PUT":
        try:
            set_grants(dataset.pk, request.user, request.data.get("grants") if isinstance(request.data, dict) else None)
        except (ValidationError, IntegrityError, OperationalError) as error:
            return _api_error(error)
    return Response({"grants": list(dataset.grants.values("membership_id", "can_read", "can_write", "can_lookup"))})


@login_required
def library(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    can_manage = membership.role in ("admin", "manager")
    selected_view = request.GET.get('view', 'datasets')
    if selected_view != 'items' or not can_manage:
        selected_view = 'datasets'
    datasets = list(visible_datasets(request.user, organization).annotate(total=Count('records', distinct=True))[:100])
    for dataset in datasets:
        dataset.access = dataset_permissions(request.user, dataset)
    return render(request, "datasets/library.html", {
        "organization": organization,
        "can_manage": can_manage,
        "dataset_count": visible_datasets(request.user, organization).count(),
        "item_count": CatalogItem.objects.filter(catalog__organization=organization).count() if can_manage else None,
        "selected_view": selected_view,
        "datasets": datasets,
        "items": CatalogItem.objects.filter(catalog__organization=organization).order_by('category', 'name') if can_manage and selected_view == 'items' else [],
    })


@login_required
def dataset_list(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    datasets = list(visible_datasets(request.user, organization).annotate(total=Count("records", distinct=True))[:100])
    for dataset in datasets:
        dataset.access = dataset_permissions(request.user, dataset)
    return render(request, "datasets/list.html", {"organization": organization, "datasets": datasets, "can_manage": membership.role in {"admin", "manager"}})


@login_required
def dataset_editor(request, org_slug, dataset_id=None):
    organization = get_object_or_404(Organization, slug=org_slug)
    require_membership(request.user, organization, manage=True)
    dataset = get_object_or_404(Dataset, pk=dataset_id, organization=organization) if dataset_id else None
    if organization.is_archived:
        messages.error(request, "Restore the organization before changing datasets.")
        return redirect("datasets:list", org_slug=org_slug)
    initial = {"schema": {"fields": [{"id": "name", "label": "Name", "type": "text", "required": True}]}}
    if dataset:
        initial.update({key: getattr(dataset, key) for key in ("name", "description", "schema", "label_field", "is_archived")})
        initial["base_schema"] = dataset.current_schema.pk
    form = DatasetForm(request.POST if request.method == "POST" else None, initial=initial, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                dataset = dataset or Dataset(organization=organization, created_by=request.user)
                for key in ("name", "description", "schema", "label_field", "is_archived"):
                    setattr(dataset, key, form.cleaned_data[key])
                dataset._actor = request.user
                dataset._expected_schema = form.cleaned_data["base_schema"]
                if dataset.pk and not dataset._state.adding and not dataset._expected_schema:
                    raise ValidationError("Reload the dataset editor before changing its definition.")
                dataset.save()
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, str(error) if isinstance(error, ValidationError) else "This dataset name is already in use.")
        else:
            messages.success(request, "Dataset definition saved. Existing records retain their original schema version.")
            if request.GET.get('dialog') == '1' and dataset_id is None:
                return render(request, 'datasets/dialog_complete.html')
            return redirect("datasets:detail", org_slug=org_slug, dataset_id=dataset.pk)
    return render(request, "datasets/editor.html", {"organization": organization, "dataset": dataset, "form": form,
                  "base_template": "embedded.html" if request.GET.get('dialog') == '1' and not dataset_id else "base.html",
                  "embedded": request.GET.get('dialog') == '1' and not dataset_id,
                  "lookup_datasets": list(visible_datasets(request.user, organization).values("id", "name"))})


def _answers(schema, data):
    labels = {field["id"]: field["label"] for field in schema.get("fields", [])}
    return [{"label": labels.get(key, key), "value": value} for key, value in data.items()]


@login_required
def dataset_detail(request, org_slug, dataset_id):
    dataset = get_object_or_404(Dataset.objects.select_related("organization"), pk=dataset_id, organization__slug=org_slug)
    require_dataset(request.user, dataset, "read")
    access = dataset_permissions(request.user, dataset)
    if request.method == "POST":
        require_dataset(request.user, dataset, "manage")
        rows = [{"membership_id": member.pk, **{action: request.POST.get(f"{action}_{member.pk}") == "on" for action in ("read", "write", "lookup")}} for member in dataset.organization.memberships.all()]
        try:
            set_grants(dataset.pk, request.user, rows)
        except ValidationError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Dataset access updated.")
        return redirect("datasets:detail", org_slug=org_slug, dataset_id=dataset.pk)
    records = dataset.records.select_related("schema_version").all()
    query = request.GET.get("q", "").strip()[:100]
    if query:
        records = records.filter(data__icontains=query)
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{slugify(dataset.name) or "dataset"}-records.csv"'
        writer = csv.writer(response)
        writer.writerow(("Record ID", "Version", "Schema version", "Archived", "Updated", "Values JSON"))
        for row in records[:5000]:
            writer.writerow((row.pk, row.version, row.schema_version.number, row.is_archived, row.updated_at.isoformat(), json.dumps(row.data, ensure_ascii=False)))
        return response
    count = records.count()
    rows = list(records[:100])
    for row in rows:
        row.answers = _answers(row.schema_version.schema, row.data)
    members = []
    if access["manage"]:
        grants = {grant.membership_id: grant for grant in dataset.grants.all()}
        for membership in dataset.organization.memberships.select_related("user"):
            membership.dataset_grant = grants.get(membership.pk)
            members.append(membership)
    return render(request, "datasets/detail.html", {"organization": dataset.organization, "dataset": dataset, "definition": dataset.current_schema,
                  "schema_versions": dataset.schema_versions.all()[:100], "records": rows, "total": count, "query": query, "access": access, "members": members,
                  "collections": dataset.organization.forms.filter(destination_schema__dataset=dataset)})


@login_required
def record_editor(request, org_slug, dataset_id, record_id=None):
    dataset = get_object_or_404(Dataset.objects.select_related("organization"), pk=dataset_id, organization__slug=org_slug)
    require_dataset(request.user, dataset, "write")
    record = None
    if record_id:
        require_dataset(request.user, dataset, "read")
        record = get_object_or_404(Record, pk=record_id, dataset=dataset)
    definition = dataset.current_schema
    form = RecordForm(request.POST if request.method == "POST" else None, definition=definition, user=request.user, record=record)
    if request.method == "POST" and form.is_valid():
        try:
            write_record(dataset_id=dataset.pk, record_id=record.pk if record else None, user=request.user, payload=form.payload(), source="staff")
        except (ValidationError, IntegrityError, OperationalError) as error:
            form.add_error(None, str(error) if isinstance(error, ValidationError) else "The write was not committed. Retry the same request.")
        else:
            messages.success(request, "Record saved with a new revision.")
            return redirect("datasets:detail" if dataset_permissions(request.user, dataset)["read"] else "datasets:list", **({"org_slug": org_slug, "dataset_id": dataset.pk} if dataset_permissions(request.user, dataset)["read"] else {"org_slug": org_slug}))
    return render(request, "datasets/record_editor.html", {"organization": dataset.organization, "dataset": dataset, "record": record, "definition": definition, "form": form})


@login_required
def record_detail(request, org_slug, dataset_id, record_id):
    dataset = get_object_or_404(Dataset.objects.select_related("organization"), pk=dataset_id, organization__slug=org_slug)
    require_dataset(request.user, dataset, "read")
    record = get_object_or_404(Record.objects.select_related("schema_version"), pk=record_id, dataset=dataset)
    entries = list(record.revisions.select_related("schema_version")[:200])
    for entry in entries:
        entry.answers = _answers(entry.schema_version.schema, entry.data)
    from organizations.permissions import can_respond_to_form
    access = dataset_permissions(request.user, dataset)
    collections = [form for form in dataset.organization.forms.filter(destination_schema=record.schema_version, status="active") if access["write"] and dataset.current_schema.pk == record.schema_version_id and not record.is_archived and can_respond_to_form(request.user, form)]
    return render(request, "datasets/record.html", {"organization": dataset.organization, "dataset": dataset, "record": record,
                  "answers": _answers(record.schema_version.schema, record.data), "entries": entries, "access": access, "collections": collections})


@api_view(["GET"])
def api_schema_history(request, dataset_id):
    dataset = _dataset(dataset_id)
    require_dataset(request.user, dataset, "read")
    return Response({"versions": [{"id": str(version.pk), "number": version.number,
                                  "schema": version.schema, "created_at": version.created_at}
                                 for version in dataset.schema_versions.all()[:100]]})
