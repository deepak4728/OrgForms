import uuid
from django import forms
from .services import validate_dataset_schema


class DatasetForm(forms.Form):
    name = forms.CharField(max_length=200)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    schema = forms.JSONField(widget=forms.Textarea(attrs={"rows": 10, "spellcheck": "false"}))
    label_field = forms.CharField(max_length=80, required=False, help_text="Only this field is disclosed as the label in record lookups. Leave empty to show record IDs.")
    is_archived = forms.BooleanField(required=False)
    base_schema = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)

    def clean_schema(self):
        schema = self.cleaned_data["schema"]
        validate_dataset_schema(schema, self.organization)
        return schema


class RecordForm(forms.Form):
    schema_version_id = forms.UUIDField(widget=forms.HiddenInput)
    expected_version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    request_id = forms.CharField(max_length=128, widget=forms.HiddenInput)
    is_archived = forms.BooleanField(required=False, label="Archive this record")

    def __init__(self, *args, definition, user, record=None, **kwargs):
        from .services import lookup_entries
        initial = {"schema_version_id": definition.pk, "expected_version": record.version if record else None, "request_id": str(uuid.uuid4()), "is_archived": bool(record and record.is_archived)}
        for field in definition.schema["fields"]:
            initial["value_" + field["id"]] = record.data.get(field["id"]) if record else None
        kwargs.setdefault("initial", initial)
        super().__init__(*args, **kwargs)
        self.definition = definition
        for field in definition.schema["fields"]:
            kind = field["type"]
            options = {"label": field["label"], "required": bool(field.get("required") and not field.get("visibleWhen"))}
            if field.get("visibleWhen"):
                options["help_text"] = "Required only when its visibility condition applies."
            if kind == "number" or kind == "rating":
                control = forms.FloatField(min_value=field.get("min"), max_value=field.get("max"), **options)
            elif kind == "email":
                control = forms.EmailField(**options)
            elif kind == "date":
                control = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), **options)
            elif kind == "checkbox":
                options["required"] = False
                control = forms.BooleanField(**options)
            elif kind in {"select", "radio"}:
                control = forms.ChoiceField(choices=[("", "Choose an option")] + [(value, value) for value in field["options"]], **options)
            elif kind == "record_reference":
                from django.core.exceptions import PermissionDenied
                from .models import Dataset
                lookup = Dataset.objects.get(pk=field["dataset_id"], organization=definition.dataset.organization)
                try:
                    choices = lookup_entries(lookup, user, limit=200)
                except PermissionDenied:
                    choices = []
                    options["help_text"] = "Lookup access is required to choose a different record."
                current = initial.get("value_" + field["id"])
                if current and not any(row["id"] == str(current) for row in choices):
                    choices.append({"id": str(current), "label": str(current)})
                control = forms.ChoiceField(choices=[("", "Choose a record")] + [(row["id"], row["label"]) for row in choices], **options)
            else:
                control = forms.CharField(max_length=10000, widget=forms.Textarea(attrs={"rows": 3}) if kind == "textarea" else forms.TextInput, **options)
            self.fields["value_" + field["id"]] = control
        self.order_fields([key for key in self.fields if key != "is_archived"] + ["is_archived"])

    def payload(self):
        data = {}
        for field in self.definition.schema["fields"]:
            value = self.cleaned_data.get("value_" + field["id"])
            if value is not None and hasattr(value, "isoformat"):
                value = value.isoformat()
            if value not in (None, ""):
                data[field["id"]] = value
        return {"data": data, **{key: str(self.cleaned_data[key]) if key == "schema_version_id" else self.cleaned_data[key] for key in ("schema_version_id", "expected_version", "request_id", "is_archived")}}
