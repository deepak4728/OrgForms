import re
import math
from datetime import date, time
from django.core.exceptions import ValidationError


FIELD_TYPES = {"text", "textarea", "quantity", "number", "email", "tel", "select", "radio", "date", "checkbox", "rating", "file", "item_cards", "record_reference", "multiselect", "time", "heading", "paragraph", "image"}


def validate_form_schema(schema):
    if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list) or not schema["fields"]:
        raise ValidationError("A form schema must contain at least one field.")
    if schema.get("dialect", "orgforms-fields-v1") != "orgforms-fields-v1":
        raise ValidationError("Unsupported schema dialect. Use orgforms-fields-v1.")
    if len(schema["fields"]) > 100:
        raise ValidationError("Use up to 100 fields per form.")
    seen = set()
    group_paths = {}
    for field in schema['fields']:
        if not isinstance(field, dict):
            continue
        if field.get('ui_group_layout', 'grid') not in ('grid', 'stack', 'horizontal'):
            raise ValidationError('Choose Grid, Horizontal or Vertical for group layout.')
        if not isinstance(field.get('ui_group_show_frame', True), bool):
            raise ValidationError('Group visibility must be true or false.')
        path = field.get('ui_group_path', [])
        if not isinstance(path, list) or len(path) > 5:
            raise ValidationError('Use up to five parent groups.')
        ids = []
        for ancestor in path:
            if not isinstance(ancestor, dict) or not isinstance(ancestor.get('id'), str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}', ancestor['id']) or not isinstance(ancestor.get('label'), str) or not ancestor['label'].strip() or len(ancestor['label']) > 200:
                raise ValidationError('Each parent group needs a valid id and name.')
            if not isinstance(ancestor.get('show_frame', True), bool):
                raise ValidationError('Parent group visibility must be true or false.')
            if ancestor.get('layout', 'grid') not in ('grid', 'stack', 'horizontal'):
                raise ValidationError('Invalid parent group layout.')
            if ancestor['id'] in ids or ancestor['id'] == field.get('ui_group'):
                raise ValidationError('Groups cannot contain themselves.')
            previous = group_paths.setdefault(ancestor['id'], tuple(ids))
            if previous != tuple(ids):
                raise ValidationError('A group must have one consistent parent.')
            ids.append(ancestor['id'])
        if field.get('ui_group'):
            previous = group_paths.setdefault(field['ui_group'], tuple(ids))
            if previous != tuple(ids):
                raise ValidationError('A group must have one consistent parent.')

    for field in schema["fields"]:
        if not isinstance(field, dict):
            raise ValidationError("Each field must be an object.")
        field_id = field.get("id", "")
        if not isinstance(field_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", field_id):
            raise ValidationError("Field ids must start with a letter and contain only letters, digits, _ or -.")
        if field_id in seen:
            raise ValidationError(f"Duplicate field id: {field_id}.")
        seen.add(field_id)
        if not isinstance(field.get("label"), str) or not field["label"].strip():
            raise ValidationError(f"Field {field_id} requires a label.")
        if "required" in field and not isinstance(field["required"], bool):
            raise ValidationError(f"Field {field_id} requires a true/false required setting.")
        if not isinstance(field.get("type"), str) or field["type"] not in FIELD_TYPES:
            raise ValidationError(f"Field {field_id} has an unsupported type.")
        if not isinstance(field.get("layout_width", "auto"), str) or field.get("layout_width", "auto") not in {"auto", "third", "half", "full"}:
            raise ValidationError(f"Field {field_id} has an invalid layout width.")
        if "max_length" in field:
            length = field["max_length"]
            if field.get("type") not in {"text", "textarea", "email", "tel"} or isinstance(length, bool) or not isinstance(length, int) or not 1 <= length <= 10000:
                raise ValidationError(f"Field {field_id} needs a character limit between 1 and 10000 for a text field.")
        if field.get("type") in {"select", "radio", "multiselect"}:
            options = field.get("options")
            if not isinstance(options, list) or not options or any(not isinstance(option, str) or not option.strip() for option in options):
                raise ValidationError(f"Field {field_id} requires a non-empty list of text options.")
        if field.get("type") in {"number", "rating", "quantity"}:
            try:
                bounds = [float(field[key]) for key in ("min", "max") if field.get(key) is not None]
                if not all(math.isfinite(bound) for bound in bounds) or (len(bounds) == 2 and bounds[0] > bounds[1]):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValidationError(f"Field {field_id} requires valid minimum and maximum values.")
        if field['type'] in {'heading', 'paragraph', 'image'} and field.get('required'):
            raise ValidationError('Display elements cannot require an answer.')
        for key in ('content', 'placeholder'):
            if key in field and (not isinstance(field[key], str) or len(field[key]) > 10000):
                raise ValidationError(f'Invalid {key} for {field_id}.')
        if field['type'] == 'image':
            from django.core.validators import URLValidator
            URLValidator(schemes=['https'])(field.get('src', ''))
        condition = field.get("visibleWhen")
        if condition is not None and (not isinstance(condition, dict) or (condition and not isinstance(condition.get("field"), str))):
            raise ValidationError(f"Field {field_id} has an invalid visibility condition.")
    for field in schema["fields"]:
        condition = field.get("visibleWhen")
        if condition and (condition.get("field") not in seen or "equals" not in condition):
            raise ValidationError(f"Field {field['id']} requires a known visibility field and an equals value.")
    dependencies = {field["id"]: (field.get("visibleWhen") or {}).get("field") for field in schema["fields"]}
    for field_id in dependencies:
        visited = set()
        current = field_id
        while current is not None:
            if current in visited:
                raise ValidationError("Visibility conditions must not contain a cycle.")
            visited.add(current)
            current = dependencies.get(current)
    return schema


def _visible(field, data, fields=None):
    condition = field.get("visibleWhen")
    if not condition:
        return True
    parent = condition.get("field")
    if fields and not _visible(fields[parent], data, fields):
        return False
    value, expected = data.get(parent), condition.get("equals")
    if fields and fields[parent]["type"] in {"number", "rating", "quantity"}:
        try:
            return not isinstance(value, bool) and not isinstance(expected, bool) and math.isfinite(float(value)) and float(value) == float(expected)
        except (TypeError, ValueError):
            return False
    return value == expected


def validate_submission(form, data, *, schema=None):
    if not isinstance(data, dict):
        raise ValidationError("Submission data must be an object.")
    errors = {}
    schema = schema if schema is not None else form.schema
    validate_form_schema(schema)
    fields = {field["id"]: field for field in schema["fields"]}
    for field in schema["fields"]:
        field_id = field["id"]
        if not _visible(field, data, fields):
            continue
        if field['type'] in {'heading', 'paragraph', 'image'}:
            continue
        value = data.get(field_id)
        if field.get("required") and (value is None or value == "" or value == []):
            errors[field_id] = "This field is required."
            continue
        if value in (None, "", []) or field_id in errors:
            continue
        kind = field.get("type")
        if field.get("max_length") is not None and isinstance(value, str) and len(value) > field["max_length"]:
            errors[field_id] = f"Enter no more than {field['max_length']} characters."
            continue
        if kind == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(value)):
            errors[field_id] = "Enter a valid email address."
        elif kind in {"number", "rating", "quantity"}:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                errors[field_id] = "Enter a number."
                continue
            if isinstance(value, bool) or not math.isfinite(numeric):
                errors[field_id] = "Enter a finite number."
                continue
            if kind == "quantity" and not numeric.is_integer():
                errors[field_id] = "Enter a whole quantity."
                continue
            if field.get("min") is not None and numeric < float(field["min"]):
                errors[field_id] = f"Enter a value of at least {field['min']}."
            if field.get("max") is not None and numeric > float(field["max"]):
                errors[field_id] = f"Enter a value no greater than {field['max']}."
        elif kind in {"select", "radio"} and value not in field.get("options", []):
            errors[field_id] = "Choose one of the listed options."
        elif kind == 'multiselect' and (not isinstance(value, list) or any(not isinstance(v, str) or v not in field.get('options', []) for v in value) or len(value) != len(set(value))):
            errors[field_id] = 'Choose distinct listed options.'
        elif kind == 'time':
            try:
                time.fromisoformat(str(value))
            except ValueError:
                errors[field_id] = 'Enter a valid time.'
        elif kind == "checkbox" and not isinstance(value, bool):
            errors[field_id] = "Choose yes or no."
        elif kind == "date":
            try:
                date.fromisoformat(str(value))
            except ValueError:
                errors[field_id] = "Enter a date in YYYY-MM-DD format."
        elif kind in {"text", "textarea", "tel"} and (not isinstance(value, str) or len(value) > 10000):
            errors[field_id] = "Enter text of up to 10,000 characters."
        elif kind == "item_cards":
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                errors[field_id] = "Choose valid menu items."
        elif kind == "file" and value != "Uploaded document":
            errors[field_id] = "Upload a document."
    if errors:
        raise ValidationError(errors)
    return {
        field["id"]: data[field["id"]]
        for field in schema["fields"]
        if field["type"] not in {"heading", "paragraph", "image"} and field["id"] in data and _visible(field, data, fields)
    }


def normalize_schema(schema, organization):
    """Bind reusable item-card fields to an organization-owned catalog."""
    import copy
    from .models import Catalog
    schema = copy.deepcopy(validate_form_schema(schema))
    if any(field["type"] == "record_reference" for field in schema["fields"]):
        from datasets.services import validate_reference_schema
        validate_reference_schema(schema, organization)
    for field in schema.get("fields", []):
        if field.get("type") != "item_cards":
            continue
        if field.get('item_source', 'catalog') not in ('organization', 'catalog'):
            raise ValidationError({field['id']: 'Choose a valid item source.'})
        if 'item_category' in field and (not isinstance(field['item_category'], str) or len(field['item_category']) > 100):
            raise ValidationError({field['id']: 'Choose a valid category.'})
        catalog_id = field.get("catalog_id")
        if catalog_id is None:
            field["catalog_id"] = Catalog.for_organization(organization).pk
        else:
            try:
                if isinstance(catalog_id, bool):
                    raise ValueError
                catalog_pk = int(catalog_id)
                if catalog_pk < 1:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                raise ValidationError({field["id"]: "Choose a catalog belonging to this organization."})
            if not Catalog.objects.filter(pk=catalog_pk, organization=organization).exists():
                raise ValidationError({field["id"]: "Choose a catalog belonging to this organization."})
            field["catalog_id"] = catalog_pk
        if 'item_ids' in field:
            ids = field['item_ids']
            if not isinstance(ids, list) or not ids or len(ids) > 500 or any(type(pk) is not int or pk < 1 for pk in ids) or len(ids) != len(set(ids)):
                raise ValidationError({field['id']: 'Select at least one valid library item.'})
            from .models import CatalogItem
            if items_for_field(field, organization).filter(pk__in=ids).count() != len(ids):
                raise ValidationError({field['id']: 'Selected items must belong to this question’s catalog.'})
    return schema


def items_for_field(field, organization):
    from .models import CatalogItem
    items = CatalogItem.objects.filter(catalog__organization=organization)
    if field.get('item_source') != 'organization':
        items = items.filter(catalog_id=field['catalog_id'])
    if field.get('item_category'):
        items = items.filter(category=field['item_category'])
    return items


def save_item_selections(form, submission, data, payload, *, schema=None):
    """Persist authoritative item snapshots inside the submission transaction."""
    from .models import CatalogItem, ItemSelection, SelectionLine
    schema = normalize_schema(schema if schema is not None else form.schema, form.organization)
    fields = [field for field in schema['fields'] if field['type'] == 'item_cards']
    # Check every existing record, even if conditional visibility hides its field.
    existing = list(submission.item_selections.select_for_update())
    if any(item.status != ItemSelection.STATUS_PENDING or item.payment_status != ItemSelection.PAYMENT_PENDING for item in existing):
        raise ValidationError('This response has started processing and can no longer be edited.')
    result = []
    stock_totals = {}
    for field in fields:
        values = data.get(field['id'], [])
        if not isinstance(values, list):
            raise ValidationError({field['id']: 'Choose valid items and quantities.'})
        selected = []
        for value in values:
            try:
                raw_id = value.get('catalog_item_id', value.get('menu_item_id'))
                raw_quantity = value.get('quantity', 1)
                if isinstance(raw_id, bool) or isinstance(raw_quantity, bool):
                    raise ValueError
                item_id, quantity = int(raw_id), int(raw_quantity)
                if str(quantity) != str(raw_quantity) or not 1 <= quantity <= 50:
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise ValidationError({field['id']: 'Choose valid items and whole quantities from 1 to 50.'})
            item = items_for_field(field, form.organization).filter(pk=item_id, is_available=True).first()
            if item is None or ('item_ids' in field and item_id not in field['item_ids']):
                raise ValidationError({field['id']: 'An item is unavailable or belongs to another catalog.'})
            from .item_options import validate_options
            validate_options(item.options)
            chosen = value.get('options', {})
            if not isinstance(chosen, dict) or set(chosen) - {option['label'] for option in item.options}:
                raise ValidationError({field['id']: 'Choose valid item options.'})
            unit_price = item.price
            for option in item.options:
                answer = chosen.get(option['label'], '')
                if (option.get('required') or answer) and answer not in option['choices']:
                    raise ValidationError({field['id']: f"Choose {option['label']} for {item.name}."})
                if answer:
                    from decimal import Decimal
                    unit_price += Decimal(str(option.get('price_adjustments', {}).get(answer, 0)))
            notes = value.get('notes', '')
            if not isinstance(notes, str) or len(notes) > 500:
                raise ValidationError({field['id']: 'Item instructions must be up to 500 characters.'})
            stock_totals[item.pk] = stock_totals.get(item.pk, 0) + quantity
            if item.stock is not None and stock_totals[item.pk] > item.stock:
                raise ValidationError({field['id']: f"Only {item.stock} units of {item.name} are available."})
            selected.append((item, quantity, chosen, unit_price, notes))
        selection = next((item for item in existing if item.field_id == field['id']), None)
        # The importer binds historical order IDs. Never accept an order ID from a respondent.
        if not selected and selection is None:
            continue
        if selection is None:
            selection = ItemSelection(submission=submission, field_id=field['id'], catalog_id=field['catalog_id'])
        selection.customer_name = str(payload.get('respondent_name') or data.get('customer_name', ''))[:200]
        selection.notes = str(data.get('notes', ''))[:10000]
        selection.save()
        selection.items.all().delete()
        for item, quantity, chosen, unit_price, notes in selected:
            SelectionLine.objects.create(selection=selection, catalog_item=item, name=item.name, quantity=quantity, unit_price=unit_price, options=chosen, notes=notes)
        selection.recalculate_totals()
        result.append(selection)
    return result
