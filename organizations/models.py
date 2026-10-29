from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Organization(models.Model):
    TYPE_GENERIC = "generic"
    TYPE_RESTAURANT = "restaurant"
    TYPE_CAFE = "cafe"
    TYPE_HOSPITALITY = "hospitality"
    TYPE_RESTAURANT_SERVICE = "restaurant_service"
    TYPE_RETAIL = "retail"
    TYPE_HEALTHCARE = "healthcare"
    TYPE_EDUCATION = "education"
    TYPE_PROFESSIONAL_SERVICES = "professional_services"
    TYPE_CHOICES = (
        (TYPE_GENERIC, "General business"),
        (TYPE_RESTAURANT, "Restaurant"),
        (TYPE_CAFE, "Cafe"),
        (TYPE_HOSPITALITY, "Hospitality"),
        (TYPE_RESTAURANT_SERVICE, "Restaurant service"),
        (TYPE_RETAIL, "Retail"),
        (TYPE_HEALTHCARE, "Healthcare"),
        (TYPE_EDUCATION, "Education"),
        (TYPE_PROFESSIONAL_SERVICES, "Professional services"),
    )

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True, default="")
    purpose = models.CharField(max_length=80, blank=True, default="")
    business_type = models.CharField(max_length=24, choices=TYPE_CHOICES, default=TYPE_GENERIC)
    is_archived = models.BooleanField(default=False)
    profile_data = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_organizations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:150] or "organization"
            candidate = base
            counter = 2
            while Organization.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                candidate = f"{base}-{counter}"
                counter += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def category_display(self):
        return (self.profile_data or {}).get("custom_category") or self.get_business_type_display()


class OrganizationMembership(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = (
        (ROLE_ADMIN, "Admin"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_MEMBER, "Member"),
    )

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("organization", "user"), name="unique_org_membership"),
            models.UniqueConstraint(fields=("user",), name="one_organization_per_account"),
        ]
        ordering = ("organization__name", "user__email")

    def save(self, *args, **kwargs):
        if self._state.adding:
            from accounts.models import AccountSpace
            from django.core.exceptions import ValidationError
            space = AccountSpace.objects.filter(user_id=self.user_id).first()
            if space and space.kind == AccountSpace.PERSONAL:
                raise ValidationError("A personal account cannot join an organization. Create a separate organization account.")
            if type(self).objects.filter(user_id=self.user_id).exclude(organization_id=self.organization_id).exists():
                raise ValidationError("This account already belongs to an organization. Use a separate account.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} — {self.organization} ({self.role})"


class OrganizationDocument(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="organization-documents/%Y/%m/")
    extracted_text = models.TextField(blank=True, default="")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class Department(models.Model):
    """Organization team; restricted form access is granted explicitly."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("is_archived", "name", "id")
        constraints = [models.UniqueConstraint(models.functions.Lower("name"), "organization", name="unique_department_name_per_org")]

    def __str__(self):
        return self.name


class StaffAssignment(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="staff_assignments")
    membership = models.ForeignKey(OrganizationMembership, on_delete=models.CASCADE, related_name="department_assignments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("department", "membership"), name="unique_department_membership")]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.department_id and self.membership_id:
            if self.department.organization_id != self.membership.organization_id:
                raise ValidationError("Staff must belong to the department's organization.")
            if self.department.is_archived:
                raise ValidationError("Restore this department before changing assignments.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class DepartmentStewardship(models.Model):
    """Responsibility for a collection does not confer editor or results access."""
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="stewardships")
    collection = models.OneToOneField("forms.DynamicForm", on_delete=models.CASCADE, related_name="department_stewardship")

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.department_id and self.collection_id and self.department.organization_id != self.collection.organization_id:
            raise ValidationError("A collection and its steward department must share an organization.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
