import uuid
from django.conf import settings
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.utils.text import slugify
from decimal import Decimal


class DynamicForm(models.Model):
    VISIBILITY_PUBLIC = "public"
    VISIBILITY_ORGANIZATION = "organization"
    VISIBILITY_RESTRICTED = "restricted"
    VISIBILITY_CHOICES = (
        (VISIBILITY_PUBLIC, "Anyone with the link"),
        (VISIBILITY_ORGANIZATION, "Organization members"),
        (VISIBILITY_RESTRICTED, "Specific accounts"),
    )
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = ((STATUS_DRAFT, "Draft"), (STATUS_ACTIVE, "Active"), (STATUS_ARCHIVED, "Archived"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="forms")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=180)
    description = models.TextField(blank=True, default="")
    purpose = models.CharField(max_length=120, blank=True, default="")
    schema = models.JSONField(default=dict)
    destination_schema = models.ForeignKey("datasets.DatasetSchemaVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="collections")
    field_mapping = models.JSONField(default=dict, blank=True)
    response_limit = models.PositiveIntegerField(null=True, blank=True)
    capture_sequence = models.PositiveBigIntegerField(default=0, editable=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    visibility = models.CharField(max_length=16, choices=VISIBILITY_CHOICES, default=VISIBILITY_ORGANIZATION)
    allowed_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="shared_orgforms")
    allowed_departments = models.ManyToManyField("organizations.Department", blank=True, related_name="accessible_forms")
    editors = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="editable_orgforms")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("organization", "slug"), name="unique_form_slug_per_org"),
            models.CheckConstraint(condition=Q(response_limit__isnull=True) | Q(response_limit__gte=1), name="positive_response_limit"),
        ]
        ordering = ("-updated_at",)

    def save(self, *args, **kwargs):
        from .services import normalize_schema
        from .capture import publish_revision
        with transaction.atomic():
            if not self._state.adding:
                # A first write serializes publication/capture on SQLite too.
                type(self).objects.filter(pk=self.pk).update(capture_sequence=F("capture_sequence") + 1)
                expected = getattr(self, "_expected_revision", None)
                current = self.current_revision
                if expected and (current is None or str(current.pk) != str(expected)):
                    raise ValidationError("This form changed in another window. Reload before saving.")
                previous = type(self).objects.get(pk=self.pk)
                self.capture_sequence = previous.capture_sequence
                if previous.organization_id != self.organization_id and self.submissions.exists():
                    raise ValidationError("Archive or duplicate a form with responses instead of moving it to another organization.")
            if self.schema:
                self.schema = normalize_schema(self.schema, self.organization)
            from datasets.services import validate_binding
            validate_binding(self)
            if not self.slug:
                base = slugify(self.title)[:150] or "form"
                if base in {"settings", "people", "menu", "submissions", "forms", "data"}:
                    base += "-form"
                candidate, counter = base, 2
                while type(self).objects.filter(organization=self.organization, slug=candidate).exclude(pk=self.pk).exists():
                    candidate = f"{base}-{counter}"
                    counter += 1
                self.slug = candidate
            super().save(*args, **kwargs)
            # Read saved values even when update_fields excludes schema.
            publish_revision(type(self).objects.get(pk=self.pk), actor=getattr(self, "_revision_actor", None))

    @property
    def current_revision(self):
        return self.revisions.order_by("-number").first()

    def __str__(self):
        return self.title


class FormSubmission(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_PENDING, "Pending review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    )

    form = models.ForeignKey(DynamicForm, on_delete=models.PROTECT, related_name="submissions")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="submissions")
    data = models.JSONField(default=dict)
    collection_revision = models.ForeignKey("CollectionRevision", on_delete=models.PROTECT, related_name="submissions")
    version = models.PositiveIntegerField(default=1)
    record = models.ForeignKey("datasets.Record", null=True, blank=True, on_delete=models.PROTECT, related_name="submissions")
    record_version = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    respondent_name = models.CharField(max_length=200, blank=True, default="")
    respondent_email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("organization", "created_at"))]

    def save(self, *args, **kwargs):
        if self.organization_id != self.form.organization_id:
            raise ValidationError("The submission must belong to its form's organization.")
        if self.collection_revision_id is None:
            self.collection_revision = self.form.current_revision
        if self.collection_revision_id and self.collection_revision.form_id != self.form_id:
            raise ValidationError("The collection revision belongs to another form.")
        if self.record_id and self.record.dataset.organization_id != self.organization_id:
            raise ValidationError("The linked record belongs to another organization.")
        super().save(*args, **kwargs)

    @property
    def current_attachments(self):
        return self.attachments.filter(is_current=True)


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Published revisions are immutable.")

    def delete(self):
        raise ValidationError("Published revisions are immutable.")


class ImmutableRevision(models.Model):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Published revisions are immutable.")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Published revisions are immutable.")


class CollectionRevision(ImmutableRevision):
    """A definition snapshot; current grants and limits are always checked live."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(DynamicForm, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    schema_dialect = models.CharField(max_length=40, default="orgforms-fields-v1")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    purpose = models.CharField(max_length=120, blank=True, default="")
    schema = models.JSONField(default=dict)
    destination_schema = models.ForeignKey("datasets.DatasetSchemaVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="collection_revisions")
    field_mapping = models.JSONField(default=dict, blank=True)
    is_legacy_baseline = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-number",)
        constraints = [models.UniqueConstraint(fields=("form", "number"), name="unique_collection_revision")]


class SubmissionRevision(ImmutableRevision):
    submission = models.ForeignKey(FormSubmission, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    respondent_name = models.CharField(max_length=200, blank=True, default="")
    respondent_email = models.CharField(max_length=254, blank=True, default="")
    status = models.CharField(max_length=16)
    attachments = models.JSONField(default=list)
    item_selections = models.JSONField(default=list)
    record_snapshot = models.JSONField(default=dict)
    event = models.CharField(max_length=24)
    source = models.CharField(max_length=24)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-number",)
        constraints = [models.UniqueConstraint(fields=("submission", "number"), name="unique_submission_revision")]


class CaptureReceipt(models.Model):
    form = models.ForeignKey(DynamicForm, on_delete=models.CASCADE, related_name="capture_receipts")
    submission = models.ForeignKey(FormSubmission, on_delete=models.CASCADE, related_name="capture_receipts")
    owner_hash = models.CharField(max_length=64)
    key = models.CharField(max_length=128)
    payload_hash = models.CharField(max_length=64)
    response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("form", "owner_hash", "key"), name="unique_capture_receipt")]


class SubmissionAttachment(models.Model):
    submission = models.ForeignKey(FormSubmission, on_delete=models.CASCADE, related_name="attachments")
    field_id = models.CharField(max_length=80)
    file = models.FileField(upload_to="submission-files/%Y/%m/")
    original_name = models.CharField(max_length=255)
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")


class Catalog(models.Model):
    organization = models.ForeignKey("organizations.Organization", null=True, blank=True, on_delete=models.CASCADE, related_name="catalogs")
    name = models.CharField(max_length=200, default="Items")
    description = models.TextField(blank=True, default="")
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def for_organization(cls, organization):
        catalog = cls.objects.filter(organization=organization).order_by("pk").first()
        return catalog or cls.objects.create(organization=organization, name=organization.name)

class CatalogItem(models.Model):
    catalog = models.ForeignKey(
        Catalog,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="items",
    )
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, default="General")
    description = models.TextField(blank=True, default="")
    barcode = models.CharField(max_length=128, blank=True, default="", db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class ItemSelection(models.Model):
    submission = models.ForeignKey("FormSubmission", null=True, blank=True, on_delete=models.SET_NULL, related_name="item_selections")
    field_id = models.CharField(max_length=80, blank=True, default="")
    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_PREPARING = "preparing"
    STATUS_READY = "ready"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_PREPARING, "Preparing"),
        (STATUS_READY, "Ready"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    catalog = models.ForeignKey(Catalog, on_delete=models.CASCADE, related_name="selections")
    customer_name = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # Retain historical processing and payment state for migrated selections.
    PAYMENT_PENDING = "pending"
    PAYMENT_AUTHORIZED = "authorized"
    PAYMENT_PAID = "paid"
    PAYMENT_FAILED = "failed"
    PAYMENT_REFUNDED = "refunded"
    PAYMENT_STATUS_CHOICES = (
        (PAYMENT_PENDING, "Pending"),
        (PAYMENT_AUTHORIZED, "Authorized"),
        (PAYMENT_PAID, "Paid"),
        (PAYMENT_FAILED, "Failed"),
        (PAYMENT_REFUNDED, "Refunded"),
    )
    payment_status = models.CharField(
        max_length=32, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PENDING
    )
    fulfillment_status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    REVIEW_PENDING = "pending"
    REVIEW_APPROVED = "approved"
    REVIEW_REJECTED = "rejected"
    REVIEW_STATUS_CHOICES = (
        (REVIEW_PENDING, "Pending review"),
        (REVIEW_APPROVED, "Approved"),
        (REVIEW_REJECTED, "Rejected"),
    )
    review_status = models.CharField(
        max_length=32, choices=REVIEW_STATUS_CHOICES, default=REVIEW_PENDING
    )
    review_note = models.TextField(blank=True, default="")
    reviewed_by = models.CharField(max_length=160, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def recalculate_totals(self):
        subtotal = sum(
            (item.line_total for item in self.items.all()),
            Decimal("0.00"),
        )
        discount = subtotal * (self.catalog.discount_percent / Decimal("100")) if self.catalog.discount_percent else Decimal("0.00")
        tax = subtotal * (self.catalog.tax_rate / Decimal("100")) if self.catalog.tax_rate else Decimal("0.00")
        total = subtotal - discount + tax
        self.subtotal = subtotal.quantize(Decimal("0.01"))
        self.discount = discount.quantize(Decimal("0.01"))
        self.tax = tax.quantize(Decimal("0.01"))
        self.total = total.quantize(Decimal("0.01"))
        self.save(update_fields=["subtotal", "discount", "tax", "total", "updated_at"])

    def __str__(self):
        return f"ItemSelection #{self.pk}"


class SelectionLine(models.Model):
    selection = models.ForeignKey(ItemSelection, on_delete=models.CASCADE, related_name="items")
    catalog_item = models.ForeignKey(CatalogItem, on_delete=models.PROTECT, related_name="selection_lines")
    name = models.CharField(max_length=200, blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        unit_price = Decimal(str(self.unit_price))
        self.line_total = (unit_price * self.quantity).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.catalog_item.name}"
