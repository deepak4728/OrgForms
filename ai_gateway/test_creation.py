import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from organizations.models import Organization, OrganizationMembership
from forms.models import DynamicForm
from ai_gateway.creation import thinking_capability as real_thinking_capability

FORM = {'title':'Workshop registration','description':'Sign up for a workshop','purpose':'Registration','fields':[{'id':'participant','label':'Participant name','type':'text','required':True}]}


@override_settings(OLLAMA_DEFAULT_MODEL='test-model')
class LocalCreationTests(APITestCase):
    def setUp(self):
        capability = patch('ai_gateway.creation.thinking_capability', return_value=False)
        capability.start()
        self.addCleanup(capability.stop)
        self.user = get_user_model().objects.create_user('local-creator')
        self.client.force_login(self.user)
        self.org = Organization.objects.create(name='Research')
        OrganizationMembership.objects.create(organization=self.org,user=self.user,role='admin')

    @patch('ai_gateway.creation.installed_models', return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_library_prompt_recovers_explicit_details(self, upstream, models):
        upstream.return_value = self.output({'name':'Library', 'description':'', 'purpose':'', 'business_type':'education', 'address':'', 'phone':'', 'email':''})
        response = self.client.post('/api/creation/organization/', {'prompt':'Create a community library in Jaipur called Open Shelf that organizes book lending and reading events.'}, format='json')
        self.assertEqual(response.status_code, 200)
        result = response.data['organization']
        self.assertEqual(result['name'], 'Open Shelf')
        self.assertEqual(result['address'], 'Jaipur')
        self.assertEqual(result['purpose'], 'book lending and reading events')
        self.assertEqual(result['email'], '')

    def output(self,draft):
        return BytesIO(json.dumps({'message':{'content':json.dumps(draft)}}).encode())

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_organization_proposal_is_local_and_does_not_write(self,upstream,models):
        draft={'name':'Open Field','description':'Community research','purpose':'Research','business_type':'generic','initial_form':FORM}
        upstream.return_value=self.output(draft)
        before=Organization.objects.count()
        response=self.client.post('/api/creation/organization/',{'prompt':'Create Open Field with a registration form','include_form':True},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(Organization.objects.count(),before)
        self.assertEqual(DynamicForm.objects.count(),0)
        self.assertEqual(response.data['initial_form'],FORM)
        payload=upstream.call_args.args[1]
        self.assertNotIn('think',payload)
        self.assertFalse(response.data['thinking'])
        self.assertEqual(payload['model'],'test-model')
        self.assertIn('initial_form',payload['format']['required'])

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_organization_draft_extracts_only_supplied_contact_and_location(self,upstream,models):
        upstream.return_value=self.output({'name':'Programmers','description':'Employee management','purpose':'Manage leave requests','business_type':'professional_services','address':'invented city','phone':'9999999999','email':'invented@example.com'})
        response=self.client.post('/api/creation/organization/',{'prompt':'Create an organization Programmers located in Jaipur with mobile 9873456748 and email programmers@example.com. For employee management and leave requests.'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['organization']['description'],'employee management and leave requests')
        self.assertEqual(response.data['organization']['purpose'],'employee management and leave requests')
        self.assertEqual(response.data['organization']['address'],'Jaipur')
        self.assertEqual(response.data['organization']['phone'],'9873456748')
        self.assertEqual(response.data['organization']['email'],'programmers@example.com')
        OrganizationMembership.objects.filter(user=self.user).delete()
        result=self.client.post('/dashboard/',{'name':'Programmers','business_type':'professional_services','profile_data':json.dumps({k:response.data['organization'][k] for k in ('address','phone','email')})})
        self.assertEqual(result.status_code,302)
        self.assertEqual(Organization.objects.get(name='Programmers').profile_data['address'],'Jaipur')
        self.assertEqual(Organization.objects.get(name='Programmers').profile_data['email'],'programmers@example.com')

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_organization_draft_never_fills_guessed_or_ambiguous_contacts(self,upstream,models):
        upstream.return_value=self.output({'name':'Research','description':'','purpose':'','business_type':'generic','address':'Imaginary Street','phone':'9999999999','email':'guessed@example.com'})
        response=self.client.post('/api/creation/organization/',{'prompt':'Create a research organization'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual([response.data['organization'][key] for key in ('address','phone','email')],['','',''])
        upstream.return_value=self.output({'name':'Research','description':'','purpose':'','business_type':'generic'})
        response=self.client.post('/api/creation/organization/',{'prompt':'Create a team; contacts one@example.com and two@example.com'},format='json')
        self.assertEqual(response.data['organization']['email'],'')
        self.assertTrue(response.data['warnings'])

    def test_reviewed_initial_form_saved_atomically_as_unpublished(self):
        OrganizationMembership.objects.filter(user=self.user).delete()
        response=self.client.post('/dashboard/',{'name':'New workspace','initial_form':json.dumps(FORM)})
        self.assertEqual(response.status_code,302)
        form=DynamicForm.objects.get()
        self.assertEqual(form.status,'draft')
        self.assertEqual(form.visibility,'organization')
        self.assertEqual(form.organization.created_by,self.user)
        self.assertEqual(form.organization.memberships.get(user=self.user).role,'admin')
        self.assertIsNotNone(form.current_revision)

    def test_invalid_hidden_form_does_not_create_organization(self):
        OrganizationMembership.objects.filter(user=self.user).delete()
        before=Organization.objects.count()
        response=self.client.post('/dashboard/',{'name':'Retained name','initial_form':json.dumps({'title':'Bad','fields':[]})})
        self.assertEqual(response.status_code,200)
        self.assertEqual(Organization.objects.count(),before)
        self.assertContains(response,'Retained name')

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_form_generation_validates_and_rejects_member_or_foreign_workspace(self,upstream,models):
        upstream.return_value=self.output(FORM)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Workshop registration'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['source'],'local-ollama')
        self.assertFalse(DynamicForm.objects.exists())
        OrganizationMembership.objects.filter(organization=self.org,user=self.user).update(role='member')
        self.assertEqual(self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Workshop'},format='json').status_code,403)
        foreign=Organization.objects.create(name='Foreign')
        self.assertEqual(self.client.post(f'/api/creation/forms/{foreign.slug}/',{'prompt':'Workshop'},format='json').status_code,403)

    @patch('ai_gateway.creation.installed_models',side_effect=URLError('offline'))
    def test_no_silent_template_or_cloud_fallback(self,models):
        response=self.client.post('/api/creation/organization/',{'prompt':'New team'},format='json')
        self.assertEqual(response.status_code,503)
        self.assertIn('No cloud fallback',response.data['detail'])

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_malformed_model_output_is_not_accepted(self,upstream,models):
        upstream.return_value=self.output({'title':'Bad','fields':[{'id':'x','label':'X','type':'record_reference','dataset_id':'1'}]})
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Make form'},format='json')
        self.assertEqual(response.status_code,422)
        self.assertFalse(DynamicForm.objects.exists())

    def test_form_editor_uses_text_prompt_without_voice_controls(self):
        from django.template.loader import render_to_string
        rendered=render_to_string('forms/form_editor.html',{'organization':self.org,'schema_data':{'fields':[]},'field_types':[]})
        self.assertNotIn('data-voice-record',rendered)
        self.assertNotIn('Whisper',rendered)
        self.assertIn(f'/api/creation/forms/{self.org.slug}/',rendered)
        self.assertNotIn("form_id:''",rendered)

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_long_purpose_is_shortened_with_review_notice(self,upstream,models):
        draft={**FORM,'purpose':'A detailed purpose ' * 20}
        upstream.return_value=self.output(draft)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Registration'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertLessEqual(len(response.data['form']['purpose']),120)
        self.assertTrue(any('shortened' in text for text in response.data['warnings']))
        self.assertFalse(DynamicForm.objects.exists())

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_catalog_item_cards_are_scoped_and_reviewed(self,upstream,models):
        from forms.models import Catalog, CatalogItem
        catalog=Catalog.objects.create(organization=self.org,name='Drinks')
        CatalogItem.objects.create(catalog=catalog,name='Coffee',price='10.00')
        foreign_org=Organization.objects.create(name='Another org')
        foreign=Catalog.objects.create(organization=foreign_org,name='Private catalog')
        CatalogItem.objects.create(catalog=foreign,name='Private item',price='10.00')
        generated={**FORM,'fields':[{'id':'items','label':'Items','type':'item_cards','required':True,'catalog_id':catalog.pk}]}
        upstream.return_value=self.output(generated)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Order coffee from the catalog'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['form']['fields'][0]['catalog_id'],catalog.pk)
        self.assertTrue(any('all available' in text for text in response.data['warnings']))
        context=json.loads(upstream.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(context['available_items'][0]['name'],'Coffee')
        self.assertNotIn('Private item',json.dumps(context))
        generated['fields'][0]['catalog_id']=foreign.pk
        upstream.return_value=self.output(generated)
        self.assertEqual(self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Order coffee'},format='json').status_code,422)

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_unimplemented_either_requirement_is_disclosed(self,upstream,models):
        upstream.return_value=self.output(FORM)
        result=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Require either an ID or a mobile number'},format='json')
        self.assertEqual(result.status_code,200)
        self.assertTrue(any('not yet enforced' in text for text in result.data['warnings']))

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_requested_item_cards_replace_invented_choices_and_bind_to_catalog(self,upstream,models):
        from forms.models import Catalog, CatalogItem
        catalog=Catalog.objects.create(organization=self.org,name='Drinks')
        CatalogItem.objects.create(catalog=catalog,name='Tea',price='10.00')
        draft={**FORM,'purpose':'A very detailed purpose ' * 10,'fields':[{'id':'contact','label':'ID or mobile number','type':'select','required':True,'options':['1234567890','0987654321']},{'id':'card1','label':'Item Card 1','type':'select','required':True,'options':['Invented drink','Invented food']}]}
        upstream.return_value=self.output(draft)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Make an order form with ID or mobile and item cards from the catalog'},format='json')
        self.assertEqual(response.status_code,200)
        fields=response.data['form']['fields']
        self.assertEqual(fields[0]['type'],'text')
        self.assertNotIn('options',fields[0])
        self.assertTrue(any('not yet enforced' in warning for warning in response.data['warnings']))
        self.assertEqual(fields[1]['type'],'item_cards')
        self.assertEqual(fields[1]['catalog_id'],catalog.pk)
        self.assertFalse(any(field['label']=='Item Card 1' for field in fields))
        self.assertFalse(DynamicForm.objects.exists())
        saved=self.client.post(f'/org/{self.org.slug}/forms/new/',{'title':'Order','status':'active','visibility':'public','schema':json.dumps({'fields':fields})})
        self.assertEqual(saved.status_code,302)
        form=DynamicForm.objects.get(organization=self.org,title='Order')
        saved_card=next(field for field in form.current_revision.schema['fields'] if field['type']=='item_cards')
        self.assertEqual(saved_card['catalog_id'],catalog.pk)
        page=self.client.get(f'/org/{self.org.slug}/{form.slug}/')
        self.assertContains(page,'Tea')


    @patch('ai_gateway.creation.thinking_capability',return_value=True)
    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_form_draft_honors_selected_model_and_think_off(self,upstream,models,capability):
        upstream.return_value=self.output(FORM)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Registration','model':'test-model','think':False},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(upstream.call_args.args[1]['model'],'test-model')
        self.assertIs(upstream.call_args.args[1]['think'],False)

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    def test_form_draft_rejects_think_on_for_unsupported_model(self,models):
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Registration','model':'test-model','think':True},format='json')
        self.assertEqual(response.status_code,422)
        self.assertIn('not available',response.data['detail'])

    @patch('ai_gateway.creation.thinking_capability',return_value=True)
    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_supported_models_enable_thinking_for_both_creation_flows(self,upstream,models,capability):
        organization={'name':'Open Field','description':'Research','purpose':'Research','business_type':'generic'}
        for url,prompt,draft in [('/api/creation/organization/','Create an organization',organization),(f'/api/creation/forms/{self.org.slug}/','Create a registration form',FORM)]:
            upstream.return_value=self.output(draft)
            response=self.client.post(url,{'prompt':prompt},format='json')
            self.assertEqual(response.status_code,200)
            self.assertIs(response.data['thinking'],True)
            payload=upstream.call_args.args[1]
            self.assertIs(payload['think'],True)
            self.assertGreaterEqual(payload['options']['num_predict'],800)
            self.assertGreaterEqual(upstream.call_args.kwargs['timeout'],120)

    @patch('ai_gateway.creation.thinking_capability',return_value=None)
    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_unknown_thinking_support_is_reported_without_guessing(self,upstream,models,capability):
        upstream.return_value=self.output(FORM)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Create a form'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.data['thinking'])
        self.assertNotIn('think',upstream.call_args.args[1])

    def test_capability_detection_uses_ollama_metadata_and_saved_fallback(self):
        from ai_gateway.models import LocalModelProfile
        LocalModelProfile.objects.create(name='configured',supports_thinking=True)
        with patch('ai_gateway.creation.ollama.open_ollama_response',return_value=BytesIO(b'{"capabilities":["completion","thinking"]}')):
            with patch('ai_gateway.creation.thinking_capability', wraps=real_thinking_capability) as detection:
                self.assertIs(detection('test-model'),True)
        with patch('ai_gateway.creation.ollama.open_ollama_response',side_effect=URLError('offline')):
            with patch('ai_gateway.creation.thinking_capability', wraps=real_thinking_capability) as detection:
                self.assertIs(detection('configured'),True)
                self.assertIsNone(detection('unknown'))


    @patch('ai_gateway.creation.thinking_capability',return_value=True)
    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_thinking_budget_can_finish_json_in_a_second_local_call(self,upstream,models,capability):
        plan='A brief private planning note.'
        upstream.side_effect=[BytesIO(json.dumps({'message':{'content':'','thinking':plan}}).encode()),self.output(FORM)]
        result=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Make a form'},format='json')
        self.assertEqual(result.status_code,200)
        self.assertIs(result.data['thinking'],True)
        self.assertEqual(result.data['reasoning_mode'],'planned')
        self.assertNotIn(plan,json.dumps(result.data))
        first,second=upstream.call_args_list
        self.assertIs(first.args[1]['think'],True)
        self.assertIs(second.args[1]['think'],False)
        self.assertIn(plan,second.args[1]['messages'][1]['content'])
        self.assertFalse(DynamicForm.objects.exists())

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_long_organization_purpose_is_reviewable(self,upstream,models):
        upstream.return_value=self.output({'name':'Open Field','description':'Research','purpose':'A long purpose ' * 20,'business_type':'generic'})
        response=self.client.post('/api/creation/organization/',{'prompt':'Create a research organization'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertLessEqual(len(response.data['organization']['purpose']),80)
        self.assertTrue(any('shortened' in warning for warning in response.data['warnings']))

    @patch('ai_gateway.creation.thinking_capability',return_value=True)
    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_organization_can_use_thinking_for_planning(self,upstream,models,capability):
        draft={'name':'Open Field','description':'Research','purpose':'Research','business_type':'generic'}
        upstream.side_effect=[BytesIO(b'{"message":{"content":"","thinking":"Plan the organization."}}'),self.output(draft)]
        before=Organization.objects.count()
        response=self.client.post('/api/creation/organization/',{'prompt':'Create a research organization'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['reasoning_mode'],'planned')
        self.assertIs(upstream.call_args_list[0].args[1]['think'],True)
        self.assertEqual(Organization.objects.count(),before)

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_draft_normalizes_model_field_ids_and_avoids_collisions(self,upstream,models):
        fields=[{'id':'1. Name','label':'Name','type':'text','required':True}, {'id':'Email address','label':'Email','type':'email','required':True}, {'id':'Email address','label':'Alternate email','type':'email','required':False}, {'id':'💼','label':'Experience','type':'text','required':False}, {'label':'Résumé','type':'text','required':False}]
        upstream.return_value=self.output({**FORM,'fields':fields})
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Job application for a junior developer'},format='json')
        self.assertEqual(response.status_code,200, response.data)
        ids=[field['id'] for field in response.data['form']['fields']]
        self.assertEqual(len(ids),len(set(ids)))
        for field_id in ids:
            self.assertRegex(field_id,r'^[A-Za-z][A-Za-z0-9_-]{0,79}$')
        self.assertEqual([field['label'] for field in response.data['form']['fields']],[field['label'] for field in fields])

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_warns_when_model_omits_requested_id_option(self,upstream,models):
        upstream.return_value=self.output(FORM)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Ask for ID or mobile number'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertTrue(any('omitted the ID' in warning for warning in response.data['warnings']))

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_suggestions_skip_duplicate_labels_and_reassign_duplicate_ids(self,upstream,models):
        draft={**FORM,'fields':[{'id':'name','label':'Name','type':'text','required':True},{'id':'name','label':'Preferred time','type':'text','required':False},{'id':'name','label':'Notes','type':'textarea','required':False}]}
        upstream.return_value=self.output(draft)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'mode':'questions','prompt':'Ask about availability','current_form':{'questions':[{'id':'name','label':'Name','type':'text'}]}},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual([f['label'] for f in response.data['form']['fields']],['Preferred time','Notes'])
        self.assertEqual([f['id'] for f in response.data['form']['fields']],['name_2','name_3'])
        self.assertTrue(any('Skipped' in warning for warning in response.data['warnings']))
        self.assertFalse(DynamicForm.objects.exists())

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_all_duplicate_suggestions_are_rejected(self,upstream,models):
        upstream.return_value=self.output(FORM)
        response=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'mode':'questions','prompt':'Add something','current_form':{'questions':[{'id':'old','label':'Participant name','type':'text'}]}},format='json')
        self.assertEqual(response.status_code,422)
        self.assertIn('new questions',response.data['detail'])

    @patch('ai_gateway.creation.installed_models',return_value=['test-model'])
    @patch('ai_gateway.creation.open_ollama_response')
    def test_inferred_character_limit_is_not_silently_enforced(self,upstream,models):
        draft={**FORM,'fields':[{'id':'participant','label':'Participant name','type':'text','required':True,'max_length':20,'layout_width':'third'}]}
        upstream.return_value=self.output(draft)
        result=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Make a registration form'},format='json')
        self.assertEqual(result.status_code,200)
        self.assertNotIn('max_length',result.data['form']['fields'][0])
        self.assertEqual(result.data['form']['fields'][0]['layout_width'],'third')
        upstream.return_value=self.output(draft)
        result=self.client.post(f'/api/creation/forms/{self.org.slug}/',{'prompt':'Limit the name to 20 characters'},format='json')
        self.assertEqual(result.data['form']['fields'][0]['max_length'],20)
