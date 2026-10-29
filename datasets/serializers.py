from django.core.exceptions import ValidationError as ModelValidationError
from rest_framework import serializers
from .models import Dataset
from .services import validate_dataset_schema


class DatasetSerializer(serializers.ModelSerializer):
    base_schema = serializers.UUIDField(required=False, write_only=True)
    schema_version = serializers.SerializerMethodField()

    class Meta:
        model = Dataset
        fields = ("id", "name", "description", "schema", "label_field", "is_archived", "schema_version", "base_schema", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def get_schema_version(self, obj):
        version = obj.current_schema
        return {"id": str(version.pk), "number": version.number} if version else None

    def validate(self, attrs):
        organization = self.instance.organization if self.instance else self.context["organization"]
        if "schema" in attrs:
            try:
                validate_dataset_schema(attrs["schema"], organization)
            except ModelValidationError as error:
                raise serializers.ValidationError({"schema": error.messages})
        others = organization.datasets.filter(name=attrs.get("name", self.instance.name if self.instance else ""))
        if self.instance:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise serializers.ValidationError({"name": "A dataset with this name already exists in this organization."})
        if self.instance and not attrs.get("base_schema"):
            raise serializers.ValidationError({"base_schema": "Provide the current dataset schema ID before changing its definition or policy."})
        return attrs

    def create(self, validated_data):
        validated_data.pop("base_schema", None)
        try:
            return super().create(validated_data)
        except ModelValidationError as error:
            raise serializers.ValidationError({"detail": error.messages})

    def update(self, instance, validated_data):
        instance._expected_schema = validated_data.pop("base_schema", None)
        instance._actor = self.context["request"].user
        try:
            return super().update(instance, validated_data)
        except ModelValidationError as error:
            raise serializers.ValidationError({"detail": error.messages})
