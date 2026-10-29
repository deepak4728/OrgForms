import json
from io import BytesIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import AIConfiguration, LocalModelProfile
from organizations.models import Organization, OrganizationMembership
from forms.models import Catalog


class AIConfigurationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('owner', password='test-password')
        self.organization = Organization.objects.create(name='General office')
        OrganizationMembership.objects.create(organization=self.organization, user=self.user, role='admin')
        self.client.force_login(self.user)

    @patch('ai_gateway.creation.thinking_capability', return_value=True)
    @patch('ai_gateway.services.open_model_response')
    def test_local_json_generation_enables_supported_thinking(self, upstream, capability):
        from .services import generate_json
        profile = AIConfiguration.for_organization(self.organization)
        upstream.return_value = BytesIO(b'{"message":{"content":"{}"}}')
        self.assertEqual(generate_json(profile, 'prompt', 'instructions'), {})
        self.assertIs(upstream.call_args.args[1]['think'], True)

    def test_ai_settings_are_independent_of_catalogs(self):
        response = self.client.patch(reverse('ai_gateway:configuration'), json.dumps({'default_model': 'office-model'}), content_type='application/json', HTTP_X_ORGANIZATION=self.organization.slug)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.organization.ai_configuration.default_model, 'office-model')
        self.assertFalse(Catalog.objects.exists())

    def test_member_can_read_but_cannot_change_ai_settings(self):
        membership = self.organization.memberships.get()
        membership.role = 'member'
        membership.save()
        url = reverse('ai_gateway:configuration')
        self.assertEqual(self.client.get(url, HTTP_X_ORGANIZATION=self.organization.slug).status_code, 200)
        self.assertEqual(self.client.patch(url, '{}', content_type='application/json', HTTP_X_ORGANIZATION=self.organization.slug).status_code, 403)

    def test_shared_model_profiles_require_installation_admin(self):
        url = reverse('ai_gateway:local-model-profiles')
        self.assertEqual(self.client.post(url, {'name': 'model'}).status_code, 403)
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.post(url, {'name': 'model'}).status_code, 201)
        self.assertTrue(LocalModelProfile.objects.filter(name='model').exists())

    @override_settings(CLOUD_API_KEY='test-key', CLOUD_API_BASE_URL='https://cloud.example/v1', OLLAMA_DEFAULT_MODEL='test')
    @patch('ai_gateway.providers.urlopen', return_value=BytesIO(b'{"choices": []}'))
    def test_invalid_cloud_response_returns_clear_error(self, upstream):
        AIConfiguration.objects.create(organization=self.organization, preferred_provider='cloud', cloud_provider='openai-compatible', default_model='test')
        response = self.client.post('/api/chat/', json.dumps({'organization_slug': self.organization.slug, 'messages': [{'role': 'user', 'content': 'Hello'}]}), content_type='application/json')
        self.assertEqual(response.status_code, 502)

    @override_settings(CHAT_MAX_CONTEXT_WINDOW=32768)
    @patch('ai_gateway.views.get_ollama_models',return_value=[{'name':'qwen3.5:0.8b','details':{'context_length':262144},'capabilities':['thinking','vision']}])
    def test_advertised_large_context_is_not_used_as_chat_default(self,models):
        from chat.serializers import ChatRequestSerializer
        result=self.client.get(reverse('ai_gateway:models'),{'org':self.organization.slug})
        model=result.json()['models'][0]
        self.assertEqual(model['context_window'],4096)
        self.assertTrue(model['supports_thinking'])
        request=ChatRequestSerializer(data={'messages':[{'role':'user','content':'Hello'}],'model_options':{'context_window':model['context_window'],'think':False,'input_mode':model['input_mode']}})
        self.assertTrue(request.is_valid(),request.errors)

    @override_settings(CHAT_MAX_CONTEXT_WINDOW=2048)
    @patch('ai_gateway.views.get_ollama_models',return_value=[{'name':'qwen','details':{'context_length':262144}}])
    def test_default_context_respects_installation_limit(self,models):
        result=self.client.get(reverse('ai_gateway:models'),{'org':self.organization.slug})
        self.assertEqual(result.json()['models'][0]['context_window'],2048)

    def test_manager_saves_default_for_only_selected_organization(self):
        self.organization.memberships.filter(user=self.user).update(role='manager')
        other=Organization.objects.create(name='Separate workspace')
        AIConfiguration.objects.create(organization=other,default_model='unchanged-model')
        response=self.client.patch(reverse('ai_gateway:configuration')+'?org='+self.organization.slug,json.dumps({'default_model':'qwen3.5:0.8b'}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(AIConfiguration.objects.get(organization=self.organization).default_model,'qwen3.5:0.8b')
        self.assertEqual(AIConfiguration.objects.get(organization=other).default_model,'unchanged-model')
