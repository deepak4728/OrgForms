from unittest.mock import patch
from django.test import SimpleTestCase
from .classification import suggest_field_values


class QuickFillTests(SimpleTestCase):
    @patch('ai_gateway.creation.local_json')
    def test_only_editable_known_fields_are_returned(self, generate):
        generate.return_value = ({'values':[{'field_id':'name','value':'Rahul'},{'field_id':'picture','value':'invented'},{'field_id':'unknown','value':'ignored'},{'field_id':'name','value':'duplicate'}]}, 'local-model', False, 'direct')
        fields = [{'id':'name','label':'Full name','type':'text'},{'id':'picture','type':'image'}]
        result = suggest_field_values('My name is Rahul',fields,'local-model')
        self.assertEqual(result['classifications'],[{'predictedFieldId':'name','dataPoint':'Rahul','probability':1.0}])
        self.assertEqual(generate.call_args.kwargs['think'],False)

    @patch('ai_gateway.creation.local_json')
    def test_invalid_choice_is_ignored(self, generate):
        generate.return_value = ({'values':[{'field_id':'shift','value':'night'}]},'local-model',False,'direct')
        self.assertEqual(suggest_field_values('night',[{'id':'shift','type':'select','options':['Morning']}],'local-model')['classifications'],[])
