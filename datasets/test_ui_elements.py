import json
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from organizations.models import Organization, OrganizationMembership
from .models import UIElement


class UIElementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('element-owner')
        self.org = Organization.objects.create(name='Element studio', created_by=self.user)
        self.membership = OrganizationMembership.objects.create(organization=self.org, user=self.user, role='admin')
        self.client.force_login(self.user)

    def test_create_edit_and_form_builder_definition(self):
        schema = {'fields':[{'id':'quantity','label':'Quantity','type':'number','min':1}, {'id':'spice','label':'Spice','type':'select','options':['Mild','Hot']}]}
        response = self.client.post(reverse('datasets:element-new', args=[self.org.slug]), {'name':'Sandwich card','description':'Choose your sandwich','schema':json.dumps(schema)})
        self.assertEqual(response.status_code, 302)
        element = UIElement.objects.get()
        page = self.client.get(reverse('forms:form-new', args=[self.org.slug]))
        self.assertContains(page, 'Sandwich card')
        response = self.client.post(reverse('datasets:element-edit', args=[self.org.slug, element.pk]), {'name':'Lunch card','description':'','schema':json.dumps(schema)})
        self.assertEqual(response.status_code, 302)
        element.refresh_from_db()
        self.assertEqual(element.name, 'Lunch card')

    def test_member_cannot_create_or_edit(self):
        self.membership.role = 'member'
        self.membership.save()
        self.assertEqual(self.client.get(reverse('datasets:element-new', args=[self.org.slug])).status_code, 403)

    def test_invalid_definition_is_not_saved(self):
        response = self.client.post(reverse('datasets:element-new', args=[self.org.slug]), {'name':'Broken','schema':json.dumps({'fields':[{'id':'x','label':'Spice','type':'select'}]})})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UIElement.objects.exists())

    def test_composite_with_choices_and_display_content(self):
        from forms.services import validate_submission
        from types import SimpleNamespace
        from django.core.exceptions import ValidationError
        schema = {'fields': [
            {'id': 'intro', 'label': 'Workshop', 'type': 'heading'},
            {'id': 'sessions', 'label': 'Sessions', 'type': 'multiselect', 'options': ['Morning', 'Evening'], 'required': True},
            {'id': 'arrival', 'label': 'Arrival', 'type': 'time'},
        ]}
        element = UIElement(organization=self.org, name='Workshop selection', schema=schema)
        element.full_clean()
        form = SimpleNamespace(schema=schema)
        self.assertEqual(validate_submission(form, {'intro': 'tampered', 'sessions': ['Morning'], 'arrival': '09:30'}), {'sessions': ['Morning'], 'arrival': '09:30'})
        for choices in ([], ['Unknown'], ['Morning', 'Morning'], 'Morning'):
            with self.assertRaises(ValidationError):
                validate_submission(form, {'sessions': choices})
        with self.assertRaises(ValidationError):
            validate_submission(form, {'sessions': ['Morning'], 'arrival': '25:99'})

    def test_starter_is_a_draft_until_saved(self):
        response = self.client.get(reverse('datasets:element-new', args=[self.org.slug]) + '?starter=sandwich')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Spice')
        self.assertFalse(UIElement.objects.exists())

    def test_ai_component_draft_requires_review_and_edit_access(self):
        from unittest.mock import patch
        proposal = {'name':'Menu chooser','description':'Current menu','layout':'grid','fields':[{'id':'menu','label':'Menu','type':'item_cards','required':True}]}
        url = reverse('datasets:element-draft', args=[self.org.slug])
        with patch('ai_gateway.creation.local_json', return_value=(proposal, 'test', True, 'json')):
            response = self.client.post(url, json.dumps({'prompt':'Create a menu card'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['schema']['layout'], 'grid')
        self.assertFalse(UIElement.objects.exists())
        self.membership.role='member'
        self.membership.save()
        self.assertEqual(self.client.post(url, {'prompt':'Menu'}).status_code, 403)
