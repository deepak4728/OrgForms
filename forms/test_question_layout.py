from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from .services import validate_form_schema, validate_submission


class QuestionLayoutTests(SimpleTestCase):
    def test_explicit_limit_and_layout_are_validated_and_enforced(self):
        schema={'fields':[{'id':'name','label':'Name','type':'text','required':True,'max_length':20,'layout_width':'third'}, {'id':'email','label':'Email','type':'email','required':False}]}
        self.assertEqual(validate_form_schema(schema),schema)
        self.assertEqual(validate_submission(None,{'name':'A'*20},schema=schema)['name'],'A'*20)
        with self.assertRaises(ValidationError): validate_submission(None,{'name':'A'*21},schema=schema)
        for invalid in [0,10001,True,'20']:
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                validate_form_schema({'fields':[{'id':'name','label':'Name','type':'text','max_length':invalid}]})
        with self.assertRaises(ValidationError): validate_form_schema({'fields':[{'id':'x','label':'X','type':'text','layout_width':'huge'}]})
        # Earlier schemas need no new layout settings.
        validate_form_schema({'fields':[{'id':'name','label':'Name','type':'text'}]})
