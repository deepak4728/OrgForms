import copy
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F

from forms.models import ImmutableRevision


class Dataset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="datasets")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    schema = models.JSONField(default=dict)
    label_field = models.CharField(max_length=80, blank=True, default="")
    is_archived = models.BooleanField(default=False)
    mutation_sequence = models.PositiveBigIntegerField(default=0, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        constraints = [models.UniqueConstraint(fields=("organization", "name"), name="unique_dataset_name_per_org")]

    @property
    def current_schema(self):
        return self.schema_versions.order_by("-number").first()

    def save(self, *args, **kwargs):
        from .services import validate_dataset_schema
        with transaction.atomic():
            if not self._state.adding:
                type(self).objects.filter(pk=self.pk).update(mutation_sequence=F("mutation_sequence") + 1)
                previous = type(self).objects.get(pk=self.pk)
                self.mutation_sequence = previous.mutation_sequence
                if previous.organization_id != self.organization_id:
                    raise ValidationError("A dataset cannot be reassigned to another organization.")
                expected = getattr(self, "_expected_schema", None)
                if expected and str(previous.current_schema.pk) != str(expected):
                    raise ValidationError("The dataset definition changed. Reload before saving.")
            validate_dataset_schema(self.schema, self.organization)
            if self.label_field and self.label_field not in {field["id"] for field in self.schema["fields"]}:
                raise ValidationError("The lookup label must be a field ID in this dataset.")
            super().save(*args, **kwargs)
            persisted = type(self).objects.get(pk=self.pk)
            current = persisted.current_schema
            if current is None or current.schema != persisted.schema:
                DatasetSchemaVersion.objects.create(
                    dataset=self, number=current.number + 1 if current else 1,
                    schema=copy.deepcopy(persisted.schema),
                    created_by=getattr(self, "_actor", None) or self.created_by,
                )


class DatasetSchemaVersion(ImmutableRevision):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="schema_versions")
    number = models.PositiveIntegerField()
    schema = models.JSONField(default=dict)
    schema_dialect = models.CharField(max_length=40, default="orgforms-fields-v1")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-number",)
        constraints = [models.UniqueConstraint(fields=("dataset", "number"), name="unique_dataset_schema_version")]


class DatasetGrant(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="grants")
    membership = models.ForeignKey("organizations.OrganizationMembership", on_delete=models.CASCADE, related_name="dataset_grants")
    can_read = models.BooleanField(default=False)
    can_write = models.BooleanField(default=False)
    can_lookup = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("dataset", "membership"), name="unique_dataset_membership_grant")]

    def save(self, *args, **kwargs):
        if self.membership.organization_id != self.dataset.organization_id:
            raise ValidationError("Choose a member of the dataset's organization.")
        super().save(*args, **kwargs)


class Record(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="records")
    schema_version = models.ForeignKey(DatasetSchemaVersion, on_delete=models.PROTECT, related_name="records")
    data = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "id")
        indexes = [models.Index(fields=("dataset", "updated_at"))]

    def save(self, *args, **kwargs):
        if self.schema_version.dataset_id != self.dataset_id:
            raise ValidationError("The record schema belongs to a different dataset.")
        super().save(*args, **kwargs)


class RecordRevision(ImmutableRevision):
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    schema_version = models.ForeignKey(DatasetSchemaVersion, on_delete=models.PROTECT, related_name="record_revisions")
    data = models.JSONField(default=dict)
    is_archived = models.BooleanField(default=False)
    source_submission = models.ForeignKey("forms.FormSubmission", null=True, blank=True, on_delete=models.SET_NULL, related_name="record_revisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=24)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-number",)
        constraints = [models.UniqueConstraint(fields=("record", "number"), name="unique_dataset_record_revision")]


class RecordCommandReceipt(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.CharField(max_length=128)
    payload_hash = models.CharField(max_length=64)
    response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("dataset", "actor", "key"), name="unique_record_command_receipt")]
