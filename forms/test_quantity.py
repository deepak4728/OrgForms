from types import SimpleNamespace
from django.test import SimpleTestCase
from django.core.exceptions import ValidationError
from .services import validate_form_schema, validate_submission

class QuantityTests(SimpleTestCase):
    def test_quantity_validates_whole_numbers_and_limits(self):
        schema = {'fields': [{'id':'qty','label':'Quantity','type':'quantity','min':0,'max':5}]}
        validate_form_schema(schema)
        form = SimpleNamespace(schema=schema)
        validate_submission(form, {'qty':3}, schema=schema)
        for value in (-1, 6, 1.5):
            with self.assertRaises(ValidationError):
                validate_submission(form, {'qty':value}, schema=schema)

    def test_item_answers_use_names_and_readable_choices(self):
        from .views import _readable_answer
        answer = _readable_answer([{'menu_item_id': 8, 'quantity': 2, 'options': {'Size': 'Large'}, 'notes': 'No sugar'}], {'8': 'Coffee'})
        self.assertEqual(answer, 'Coffee × 2 · Size: Large\nNote: No sugar')
        self.assertEqual(_readable_answer([{'menu_item_id': 9, 'quantity': 1}], {}), 'Unavailable item × 1')
