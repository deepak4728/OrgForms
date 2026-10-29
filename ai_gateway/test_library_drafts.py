from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from datasets.models import Dataset
from forms.models import CatalogItem
from organizations.models import Organization, OrganizationMembership


class LibraryDraftTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user('admin')
        self.member = User.objects.create_user('member')
        self.org = Organization.objects.create(name='Library team', created_by=self.admin)
        OrganizationMembership.objects.create(user=self.admin, organization=self.org, role='admin')
        OrganizationMembership.objects.create(user=self.member, organization=self.org, role='member')
        self.client.force_login(self.admin)

    def url(self, kind):
        return reverse('ai_gateway:library-draft', args=[self.org.slug, kind])

    @patch('ai_gateway.creation_views.local_json')
    def test_item_is_a_reviewable_draft_without_an_invented_price(self, generate):
        generate.return_value = ({'name': 'Sandwich', 'category': 'Food', 'description': '', 'price': '100'}, 'local', False, 'direct')
        response = self.client.post(self.url('item'), {'prompt': 'Sandwich'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['draft']['price'], '')
        self.assertFalse(CatalogItem.objects.exists())

    @patch('ai_gateway.creation_views.local_json')
    def test_dataset_rejects_unsupported_fields_and_does_not_write(self, generate):
        generate.return_value = ({'title': 'Records', 'description': '', 'purpose': '', 'fields': [{'id': 'photo', 'label': 'Photo', 'type': 'file', 'required': False}]}, 'local', False, 'direct')
        response = self.client.post(self.url('dataset'), {'prompt': 'A dataset'}, content_type='application/json')
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Dataset.objects.exists())

    @patch('ai_gateway.creation_views.local_json')
    def test_members_cannot_generate_organization_library_drafts(self, generate):
        self.client.force_login(self.member)
        response = self.client.post(self.url('item'), {'prompt': 'Item'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        generate.assert_not_called()
