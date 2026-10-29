from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import DynamicForm, FormSubmission, CatalogItem
from .services import validate_form_schema, normalize_schema
from .forms import FormAccessSettingsForm


class DynamicFormSerializer(serializers.ModelSerializer):
    public_url = serializers.SerializerMethodField()
    submission_count = serializers.IntegerField(source="submissions.count", read_only=True)
    access_emails = serializers.ListField(child=serializers.EmailField(), write_only=True, required=False, max_length=100)
    access_departments = serializers.ListField(child=serializers.IntegerField(min_value=1), write_only=True, required=False, max_length=100)
    allowed_people = serializers.SerializerMethodField()
    revision = serializers.SerializerMethodField()
    base_revision = serializers.UUIDField(required=False, write_only=True)
    response_limit = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=2147483647)

    class Meta:
        model = DynamicForm
        fields = ("id", "title", "slug", "description", "purpose", "schema", "status", "visibility", "access_emails", "access_departments", "allowed_people", "public_url", "submission_count", "created_at", "updated_at", "response_limit", "revision", "base_revision", "destination_schema", "field_mapping")
        read_only_fields = ("id", "created_at", "updated_at", "public_url", "submission_count")
        extra_kwargs = {"slug": {"required": False, "allow_blank": True}}

    def get_public_url(self, form):
        request = self.context.get("request")
        path = f"/org/{form.organization.slug}/{form.slug}/"
        return request.build_absolute_uri(path) if request else path

    def get_revision(self, form):
        revision = form.current_revision
        return {"id": str(revision.pk), "number": revision.number, "schema_dialect": revision.schema_dialect, "is_legacy_baseline": revision.is_legacy_baseline} if revision else None

    def create(self, validated_data):
        validated_data.pop("base_revision", None)
        try:
            return super().create(validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"detail": error.messages}) from error

    def update(self, instance, validated_data):
        instance._expected_revision = validated_data.pop("base_revision", None)
        request = self.context.get("request")
        instance._revision_actor = request.user if request else None
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"detail": error.messages}) from error

    def get_allowed_people(self, form):
        request = self.context.get("request")
        if request and form.organization.memberships.filter(user=request.user, role__in=("admin", "manager")).exists():
            return list(form.allowed_users.values_list("email", flat=True))
        return []

    def validate_slug(self, value):
        if value in {"settings", "people", "menu", "submissions", "forms", "data"}:
            raise serializers.ValidationError("This link name is reserved for workspace pages.")
        return value

    def validate(self, attrs):
        organization = self.instance.organization if self.instance else self.context.get("organization")
        from types import SimpleNamespace
        from datasets.services import validate_binding
        destination = attrs.get("destination_schema", self.instance.destination_schema if self.instance else None)
        try:
            validate_binding(SimpleNamespace(
                organization_id=organization.pk if organization else None, destination_schema=destination,
                destination_schema_id=destination.pk if destination else None,
                field_mapping=attrs.get("field_mapping", self.instance.field_mapping if self.instance else {}),
                schema=attrs.get("schema", self.instance.schema if self.instance else {}),
            ))
        except DjangoValidationError as error:
            raise serializers.ValidationError({"field_mapping": error.messages})
        if organization and attrs.get("slug"):
            others = organization.forms.filter(slug=attrs["slug"])
            if self.instance:
                others = others.exclude(pk=self.instance.pk)
            if others.exists():
                raise serializers.ValidationError({"slug": "This form link is already in use."})
        if self.instance is None or "visibility" in attrs or "access_emails" in attrs or "access_departments" in attrs:
            emails = attrs.pop("access_emails", None)
            if emails is None:
                emails = list(self.instance.allowed_users.values_list("email", flat=True)) if self.instance else []
            department_ids = attrs.pop("access_departments", None)
            if department_ids is None:
                department_ids = list(self.instance.allowed_departments.values_list("pk", flat=True)) if self.instance else []
            access = FormAccessSettingsForm({
                "visibility": attrs.get("visibility", self.instance.visibility if self.instance else DynamicForm.VISIBILITY_ORGANIZATION),
                "access_emails": "\n".join(emails),
                "access_departments": department_ids,
            }, organization=organization)
            if not access.is_valid():
                raise serializers.ValidationError(dict(access.errors))
            attrs["allowed_users"] = access.allowed_accounts
            attrs["allowed_departments"] = access.cleaned_data["access_departments"]
        return attrs

    def validate_schema(self, value):
        try:
            organization = self.instance.organization if self.instance else self.context.get("organization")
            return normalize_schema(value, organization) if organization else validate_form_schema(value)
        except Exception as exc:
            raise serializers.ValidationError(str(exc)) from exc


class FormSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormSubmission
        fields = ("id", "form", "data", "respondent_name", "respondent_email", "created_at", "collection_revision", "version")
        read_only_fields = ("id", "form", "created_at", "collection_revision", "version")


class CatalogItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CatalogItem
        fields = (
            "id",
            "name",
            "category",
            "description",
            "barcode",
            "price",
            "is_available",
        )


class CatalogItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CatalogItem
        fields = (
            "name",
            "category",
            "description",
            "barcode",
            "price",
            "is_available",
        )

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price must be zero or greater.")
        return value
