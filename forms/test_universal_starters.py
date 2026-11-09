from django.test import SimpleTestCase
from forms.element_catalog import STARTERS
from forms.services import validate_form_schema


class UniversalStarterTests(SimpleTestCase):
    def test_collection_starters_use_supported_schema(self):
        for name in STARTERS:
            with self.subTest(name=name):
                validate_form_schema(STARTERS[name]['schema'])

    def test_groups_cover_every_starter_once(self):
        from forms.element_catalog import STARTER_GROUPS
        keys = [key for _, group in STARTER_GROUPS for key in group]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(STARTERS))

    def test_page_composition_keeps_independent_fields_and_groups(self):
        from forms.element_catalog import compose_page
        page = compose_page('Test', 'Test', ('contact', 'contact'))
        fields = page['schema']['fields']
        validate_form_schema(page['schema'])
        self.assertEqual(len({field['id'] for field in fields}), 6)
        self.assertEqual(len({field['ui_group'] for field in fields}), 2)
        fields[0]['label'] = 'Changed'
        self.assertEqual(STARTERS['contact']['schema']['fields'][0]['label'], 'Full name')

    def test_composition_remaps_conditional_dependencies(self):
        from unittest.mock import patch
        from forms.element_catalog import compose_page
        starter = {'name': 'Conditional', 'schema': {'fields': [
            {'id': 'choice', 'label': 'Choice', 'type': 'text'},
            {'id': 'detail', 'label': 'Detail', 'type': 'text',
             'visibleWhen': {'field': 'choice', 'equals': 'yes'}},
        ]}}
        with patch.dict(STARTERS, {'conditional': starter}):
            page = compose_page('Test', '', ('conditional', 'conditional'))
        validate_form_schema(page['schema'])
        self.assertEqual(page['schema']['fields'][3]['visibleWhen']['field'], 'section2_choice')
