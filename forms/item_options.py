from django.core.exceptions import ValidationError

def validate_options(value):
    if not isinstance(value, list) or len(value) > 12:
        raise ValidationError("Use up to 12 item options.")
    seen = set()
    for option in value:
        if not isinstance(option, dict) or set(option) - {"label", "choices", "required", "price_adjustments"}:
            raise ValidationError("Each option needs a label, choices and optional required flag.")
        label = option.get("label")
        choices = option.get("choices")
        if not isinstance(label, str) or not label.strip() or len(label) > 100 or label in seen:
            raise ValidationError("Option labels must be unique and up to 100 characters.")
        if not isinstance(choices, list) or not 1 <= len(choices) <= 30 or any(not isinstance(c, str) or not c.strip() or len(c) > 100 for c in choices) or len(set(choices)) != len(choices):
            raise ValidationError("Each option needs 1–30 unique text choices.")
        if not isinstance(option.get("required", False), bool):
            raise ValidationError("Required must be true or false.")
        adjustments = option.get('price_adjustments', {})
        if not isinstance(adjustments, dict) or set(adjustments) - set(choices):
            raise ValidationError('Prices must belong to listed choices.')
        from decimal import Decimal, InvalidOperation
        for amount in adjustments.values():
            try:
                price = Decimal(str(amount))
                if not price.is_finite() or price < 0 or price > 100000 or price != price.quantize(Decimal('0.01')):
                    raise ValueError
            except (InvalidOperation, ValueError):
                raise ValidationError('Choice price additions must be from 0 to 100000 with up to two decimal places.')
        seen.add(label)
    return value
