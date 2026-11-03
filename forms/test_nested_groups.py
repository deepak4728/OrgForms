from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from .services import validate_form_schema


class NestedGroupTests(SimpleTestCase):
    def field(self):
        return {'id':'name','label':'Name','type':'text','ui_group':'contact','ui_group_label':'Contact','ui_group_path':[{'id':'registration','label':'Registration'}]}

    def test_nested_group_is_preserved(self):
        schema={'fields':[self.field()]}
        self.assertEqual(validate_form_schema(schema)['fields'][0]['ui_group_path'][0]['id'],'registration')

    def test_cycle_is_rejected(self):
        field=self.field();field['ui_group_path'].append({'id':'contact','label':'Contact'})
        with self.assertRaises(ValidationError):validate_form_schema({'fields':[field]})

    def test_conflicting_parents_are_rejected(self):
        other={**self.field(),'id':'email','ui_group_path':[]}
        with self.assertRaises(ValidationError):validate_form_schema({'fields':[self.field(),other]})

    def test_horizontal_layout_survives_validation(self):
        field=self.field();field['ui_group_layout']='horizontal';field['ui_group_path'][0]['layout']='stack'
        result=validate_form_schema({'fields':[field]})
        self.assertEqual(result['fields'][0]['ui_group_layout'],'horizontal')

    def test_unknown_layout_is_rejected(self):
        field=self.field();field['ui_group_layout']='invalid'
        with self.assertRaises(ValidationError):validate_form_schema({'fields':[field]})

    def test_hidden_group_and_parent_are_preserved(self):
        field=self.field();field['ui_group_show_frame']=False;field['ui_group_path'][0]['show_frame']=False
        result=validate_form_schema({'fields':[field]})['fields'][0]
        self.assertIs(result['ui_group_show_frame'],False)
        self.assertIs(result['ui_group_path'][0]['show_frame'],False)

    def test_visibility_must_be_boolean(self):
        field=self.field();field['ui_group_show_frame']='false'
        with self.assertRaises(ValidationError):validate_form_schema({'fields':[field]})
