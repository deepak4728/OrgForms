import copy
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from forms.models import CaptureReceipt, Catalog, CatalogItem, DynamicForm, FormSubmission, SubmissionRevision
from organizations.models import Organization, OrganizationMembership
from .models import Dataset, DatasetGrant, DatasetSchemaVersion, Record, RecordRevision
from .services import DatasetError, lookup_entries, set_grants, write_record

SCHEMA = {"fields": [{"id": "name", "label": "Name", "type": "text", "required": True}, {"id": "note", "label": "Note", "type": "text"}]}


class DatasetFoundationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('dataset-owner')
        self.member = User.objects.create_user('dataset-member')
        self.stranger = User.objects.create_user('dataset-stranger')
        self.org = Organization.objects.create(name='Community research', created_by=self.owner)
        self.other = Organization.objects.create(name='Other team', created_by=self.stranger)
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role='admin')
        self.membership = OrganizationMembership.objects.create(organization=self.org, user=self.member, role='member')
        OrganizationMembership.objects.create(organization=self.other, user=self.stranger, role='admin')
        self.dataset = Dataset.objects.create(organization=self.org, name='Registrations', schema=copy.deepcopy(SCHEMA), label_field='name', created_by=self.owner)
        self.client.force_login(self.owner)
        self.form = self.collection()
        self.url = reverse('forms:public-form', args=[self.org.slug, self.form.slug])

    def collection(self, title='Registration', source='full_name'):
        return DynamicForm.objects.create(organization=self.org, title=title, schema={'fields':[{'id':source,'label':'Your name','type':'text','required':True}]}, destination_schema=self.dataset.current_schema, field_mapping={source:'name'}, status='active', visibility='public')

    def command(self, **extra):
        return {'schema_version_id':str(self.dataset.current_schema.pk),'request_id':str(uuid.uuid4()),'data':{'name':'Ada','note':'Private note'}, **extra}

    def create(self, **extra):
        result=write_record(dataset_id=self.dataset.pk,user=self.owner,payload=self.command(**extra))
        return Record.objects.get(pk=result['id'])

    def capture(self, form=None, **extra):
        form=form or self.form
        return self.client.post(reverse('forms:public-form', args=[self.org.slug,form.slug]),json.dumps({'data':{'full_name':'Ada'},'revision_id':str(form.current_revision.pk),'request_id':str(uuid.uuid4()),**extra}),content_type='application/json')

    def grant(self, **flags):
        return DatasetGrant.objects.create(dataset=self.dataset,membership=self.membership,**{'can_'+key:value for key,value in flags.items()})

    def test_library_counts_respect_organization_and_access(self):
        catalog = Catalog.objects.create(organization=self.org, name='Items')
        CatalogItem.objects.create(catalog=catalog, name='Book', price=0)
        other_catalog = Catalog.objects.create(organization=self.other, name='Other items')
        CatalogItem.objects.create(catalog=other_catalog, name='Other', price=0)
        url = reverse('datasets:library', args=[self.org.slug])
        response = self.client.get(url)
        self.assertEqual(response.context['dataset_count'], 1)
        self.assertEqual(response.context['item_count'], 1)
        self.client.force_login(self.member)
        response = self.client.get(url)
        self.assertEqual(response.context['dataset_count'], 0)
        self.assertIsNone(response.context['item_count'])
        self.assertNotContains(response, 'Catalog items')
        self.grant(lookup=True)
        self.assertEqual(self.client.get(url).context['dataset_count'], 1)

    def test_library_views_and_item_creation_respect_membership(self):
        url = reverse('datasets:library', args=[self.org.slug])
        response = self.client.get(url, {'view': 'datasets'})
        self.assertContains(response, 'Registrations')
        response = self.client.post(reverse('forms:menu', args=[self.org.slug]), {'return_to': 'library', 'name': 'Book', 'category': 'Reading', 'price': '10'})
        self.assertRedirects(response, url + '?view=items')
        self.assertContains(self.client.get(url, {'view': 'items'}), 'Book')
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url, {'view': 'items'}).context['selected_view'], 'datasets')
        self.assertEqual(self.client.post(reverse('forms:menu', args=[self.org.slug]), {'name':'Unauthorized', 'price':'1'}).status_code, 403)

    def test_dataset_creation_dialog_saves_and_reports_completion(self):
        url = reverse('datasets:new', args=[self.org.slug]) + '?dialog=1'
        self.assertContains(self.client.get(url), 'dataset-definition-form')
        response = self.client.post(url, {'name':'Books', 'description':'', 'schema':json.dumps(SCHEMA), 'label_field':'name'})
        self.assertContains(response, 'orgforms:library-saved')
        self.assertTrue(Dataset.objects.filter(organization=self.org, name='Books').exists())

    def test_schema_versions_are_immutable_and_only_schema_changes_version(self):
        first=self.dataset.current_schema
        self.dataset.description='Updated';self.dataset.save()
        self.assertEqual(self.dataset.schema_versions.count(),1)
        self.dataset.schema['fields'][0]['label']='Full name';self.dataset.save()
        self.assertEqual(self.dataset.current_schema.number,2)
        first.refresh_from_db();self.assertEqual(first.schema['fields'][0]['label'],'Name')
        with self.assertRaises(ValidationError): first.save()
        with self.assertRaises(ValidationError): DatasetSchemaVersion.objects.filter(pk=first.pk).update(schema={})

    def test_schema_compare_and_swap_rejects_stale_editor(self):
        stale=Dataset.objects.get(pk=self.dataset.pk);stale._expected_schema=self.dataset.current_schema.pk
        self.dataset.schema['fields'][0]['label']='Changed';self.dataset.save()
        stale.name='Stale'
        with self.assertRaises(ValidationError): stale.save()
        self.dataset.refresh_from_db();self.assertEqual(self.dataset.name,'Registrations')

    def test_record_commands_are_versioned_idempotent_and_do_not_merge_names(self):
        payload=self.command();first=write_record(dataset_id=self.dataset.pk,user=self.owner,payload=payload)
        again=write_record(dataset_id=self.dataset.pk,user=self.owner,payload=payload)
        self.assertTrue(again['replayed']);self.assertEqual(first['id'],again['id'])
        record=self.create();self.assertEqual(Record.objects.count(),2)
        result=write_record(dataset_id=self.dataset.pk,user=self.owner,record_id=record.pk,payload=self.command(expected_version=1,data={'name':'Grace'}))
        self.assertEqual(result['version'],2);self.assertEqual(record.revisions.count(),2)
        with self.assertRaises(DatasetError): write_record(dataset_id=self.dataset.pk,user=self.owner,record_id=record.pk,payload=self.command(expected_version=1))

    def test_request_key_reuse_for_other_values_conflicts(self):
        payload=self.command();write_record(dataset_id=self.dataset.pk,user=self.owner,payload=payload)
        payload['data']['name']='Changed'
        with self.assertRaises(DatasetError) as caught: write_record(dataset_id=self.dataset.pk,user=self.owner,payload=payload)
        self.assertEqual(caught.exception.status,409)

    def test_record_schema_upgrade_preserves_old_revision_schema(self):
        record=self.create();old=record.schema_version
        self.dataset.schema['fields'][0]['label']='Updated name';self.dataset.save()
        with self.assertRaises(DatasetError): write_record(dataset_id=self.dataset.pk,user=self.owner,record_id=record.pk,payload=self.command(schema_version_id=str(old.pk),expected_version=1))
        write_record(dataset_id=self.dataset.pk,user=self.owner,record_id=record.pk,payload=self.command(expected_version=1))
        record.refresh_from_db();self.assertEqual(record.schema_version.number,2)
        self.assertEqual(record.revisions.get(number=1).schema_version.schema['fields'][0]['label'],'Name')

    def test_schema_history_is_read_scoped_and_keeps_old_definitions(self):
        self.dataset.schema['fields'][0]['label']='Full name';self.dataset.save()
        url=reverse('datasets:api-schemas',args=[self.dataset.pk])
        result=self.client.get(url)
        self.assertEqual(result.status_code,200);self.assertEqual([v['number'] for v in result.json()['versions']],[2,1])
        self.grant(lookup=True);self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code,403)

    def test_form_editor_saves_explicit_mapping(self):
        response=self.client.post(reverse('forms:form-edit',args=[self.org.slug,self.form.pk]),{'title':self.form.title,'slug':self.form.slug,'schema':json.dumps(self.form.schema),'status':'active','visibility':'public','base_revision':str(self.form.current_revision.pk),'destination_schema':str(self.dataset.current_schema.pk),'field_mapping':json.dumps({'full_name':'name'})})
        self.assertEqual(response.status_code,302);self.form.refresh_from_db()
        self.assertEqual(self.form.current_revision.field_mapping,{'full_name':'name'})

    def test_record_revisions_reject_application_mutations(self):
        record=self.create()
        with self.assertRaises(ValidationError): RecordRevision.objects.filter(record=record).update(data={})
        entry=record.revisions.first();entry.data={}
        with self.assertRaises(ValidationError): entry.save()

    def test_no_grant_denies_read_write_lookup(self):
        self.client.force_login(self.member)
        for name in ('api-detail','api-records','api-lookup'):
            self.assertEqual(self.client.get(reverse('datasets:'+name,args=[self.dataset.pk])).status_code,403)
        with self.assertRaises(PermissionDenied): write_record(dataset_id=self.dataset.pk,user=self.member,payload=self.command())

    def test_lookup_only_exposes_approved_label_and_id(self):
        record=self.create();self.grant(lookup=True);self.client.force_login(self.member)
        response=self.client.get(reverse('datasets:api-lookup',args=[self.dataset.pk]))
        self.assertEqual(response.json()['results'],[{'id':str(record.pk),'label':'Ada'}])
        metadata=self.client.get(reverse('datasets:api-detail',args=[self.dataset.pk])).json()
        self.assertNotIn('schema',metadata);self.assertNotIn('description',metadata)
        self.assertEqual(self.client.get(reverse('datasets:api-records',args=[self.dataset.pk])).status_code,403)
        self.assertEqual(self.client.get(reverse('datasets:detail',args=[self.org.slug,self.dataset.pk]),{'export':'csv'}).status_code,403)

    def test_write_only_cannot_read_or_export(self):
        self.grant(write=True);self.client.force_login(self.member)
        result=self.client.post(reverse('datasets:api-records',args=[self.dataset.pk]),json.dumps(self.command()),content_type='application/json')
        self.assertEqual(result.status_code,201);self.assertNotIn('data',result.json())
        for name,args in [('api-records',[self.dataset.pk]),('api-history',[self.dataset.pk,result.json()['id']])]:
            self.assertEqual(self.client.get(reverse('datasets:'+name,args=args)).status_code,403)
        self.assertEqual(self.client.get(reverse('datasets:record-new',args=[self.org.slug,self.dataset.pk])).status_code,200)

    def test_read_does_not_imply_lookup_or_write(self):
        self.grant(read=True);self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse('datasets:api-records',args=[self.dataset.pk])).status_code,200)
        with self.assertRaises(PermissionDenied): lookup_entries(self.dataset,self.member)
        with self.assertRaises(PermissionDenied): write_record(dataset_id=self.dataset.pk,user=self.member,payload=self.command())

    def test_tenant_boundary_blocks_even_other_owner(self):
        self.client.force_login(self.stranger)
        for name in ('api-records','api-detail','api-lookup'):
            self.assertEqual(self.client.get(reverse('datasets:'+name,args=[self.dataset.pk])).status_code,403)
        with self.assertRaises(ValidationError):
            DatasetGrant.objects.create(dataset=self.dataset,membership=self.other.memberships.first(),can_read=True)
        self.dataset.organization=self.other
        with self.assertRaises(ValidationError): self.dataset.save()

    def test_removed_membership_blocks_receipt_replay(self):
        self.grant(write=True);payload=self.command();write_record(dataset_id=self.dataset.pk,user=self.member,payload=payload)
        self.membership.delete()
        with self.assertRaises(PermissionDenied): write_record(dataset_id=self.dataset.pk,user=self.member,payload=payload)

    def test_grant_validation_is_atomic_and_same_org_only(self):
        grant=self.grant(read=True)
        with self.assertRaises(DatasetError): set_grants(self.dataset.pk,self.owner,[{'membership_id':self.other.memberships.first().pk,'read':True}])
        self.assertTrue(DatasetGrant.objects.filter(pk=grant.pk,can_read=True).exists())
        set_grants(self.dataset.pk,self.owner,[{'membership_id':self.membership.pk,'lookup':True}])
        grant.refresh_from_db();self.assertFalse(grant.can_read);self.assertTrue(grant.can_lookup)
        response=self.client.put(reverse('datasets:api-grants',args=[self.dataset.pk]),'[]',content_type='application/json');self.assertEqual(response.status_code,400)

    def test_two_collections_write_one_dataset_with_different_source_ids(self):
        first=self.capture();second=self.collection('Event sign up','attendee')
        result=self.capture(form=second,data={'attendee':'Grace'})
        self.assertEqual(first.status_code,201);self.assertEqual(result.status_code,201)
        self.assertEqual(set(self.dataset.records.values_list('data__name',flat=True)),{'Ada','Grace'})
        self.assertEqual(FormSubmission.objects.count(),2);self.assertEqual(RecordRevision.objects.count(),2)

    def test_guest_capture_creates_record_without_grant_but_cannot_read(self):
        self.client.logout();self.client.get(self.url)
        response=self.capture();self.assertEqual(response.status_code,201)
        self.assertIsNone(Record.objects.get().created_by_id)
        self.assertNotIn('data',response.json());self.assertEqual(self.client.get(reverse('datasets:api-records',args=[self.dataset.pk])).status_code,403)

    def test_capture_retry_does_not_duplicate_record_or_revision(self):
        first=self.capture(request_id='replay');second=self.capture(request_id='replay')
        self.assertEqual(first.json()['record_id'],second.json()['record_id'])
        self.assertTrue(second.json()['replayed']);self.assertEqual(Record.objects.count(),1);self.assertEqual(RecordRevision.objects.count(),1)
        self.assertEqual(SubmissionRevision.objects.get().record_snapshot,{'id':first.json()['record_id'],'version':1})

    def test_explicit_collection_update_requires_write_and_version(self):
        record=self.create();self.client.force_login(self.member)
        response=self.capture(record_id=str(record.pk),record_version=1)
        self.assertEqual(response.status_code,403);self.assertFalse(FormSubmission.objects.exists())
        self.grant(write=True)
        result=self.capture(record_id=str(record.pk),record_version=1)
        self.assertEqual(result.status_code,201);record.refresh_from_db()
        self.assertEqual(record.version,2);self.assertEqual(record.data['note'],'Private note')
        stale=self.capture(record_id=str(record.pk),record_version=1)
        self.assertEqual(stale.status_code,409);self.assertEqual(FormSubmission.objects.count(),1)

    def test_own_response_edit_updates_only_linked_record(self):
        first=self.capture().json()
        response=self.capture(edit_token=first['edit_token'],expected_version=1,record_version=1,data={'full_name':'Corrected'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['record_version'],2)
        self.assertEqual(Record.objects.get().data['name'],'Corrected');self.assertEqual(Record.objects.count(),1)

    def test_external_record_change_blocks_old_response_edit_atomically(self):
        first=self.capture().json();record=Record.objects.get()
        write_record(dataset_id=self.dataset.pk,user=self.owner,record_id=record.pk,payload=self.command(expected_version=1))
        result=self.capture(edit_token=first['edit_token'],expected_version=1,record_version=1,data={'full_name':'Old response'})
        self.assertEqual(result.status_code,409);self.assertEqual(FormSubmission.objects.get().version,1);self.assertEqual(SubmissionRevision.objects.count(),1)

    def test_destination_schema_changes_require_explicit_republication(self):
        self.dataset.schema['fields'][0]['label']='Full name';self.dataset.save()
        failed=self.capture();self.assertEqual(failed.status_code,409);self.assertFalse(FormSubmission.objects.exists());self.assertFalse(CaptureReceipt.objects.exists())
        self.form.destination_schema=self.dataset.current_schema;self.form.save()
        self.assertEqual(self.capture().status_code,201)

    def test_archived_dataset_rejects_capture_without_using_quota(self):
        self.dataset.is_archived=True;self.dataset.save()
        self.assertEqual(self.capture().status_code,409);self.assertFalse(FormSubmission.objects.exists());self.assertFalse(Record.objects.exists())

    def test_record_failure_rolls_back_submission_and_receipt(self):
        with patch('datasets.services.persist_record',side_effect=OperationalError('Disk unavailable')):
            self.assertEqual(self.capture(request_id='retry').status_code,503)
        self.assertFalse(FormSubmission.objects.exists());self.assertFalse(CaptureReceipt.objects.exists())
        self.assertEqual(self.capture(request_id='retry').status_code,201)

    def test_binding_rejects_missing_wrong_type_and_foreign_fields(self):
        for mapping in ({}, {'missing':'name'},{'full_name':'missing'}):
            self.form.field_mapping=mapping
            with self.assertRaises(ValidationError): self.form.save()
        self.form.field_mapping={'full_name':'name'};self.form.schema['fields'][0]['type']='number'
        with self.assertRaises(ValidationError):self.form.save()
        foreign=Dataset.objects.create(organization=self.other,name='Foreign',schema=copy.deepcopy(SCHEMA))
        self.form.destination_schema=foreign.current_schema
        with self.assertRaises(ValidationError):self.form.save()

    def test_reference_lookup_requires_independent_permission(self):
        record=self.create()
        references=Dataset.objects.create(organization=self.org,name='Requests',schema={'fields':[{'id':'asset','label':'Asset','type':'record_reference','dataset_id':str(self.dataset.pk),'required':True}]})
        DatasetGrant.objects.create(dataset=references,membership=self.membership,can_write=True)
        payload={'data':{'asset':str(record.pk)},'schema_version_id':str(references.current_schema.pk),'request_id':'ref'}
        with self.assertRaises(PermissionDenied):write_record(dataset_id=references.pk,user=self.member,payload=payload)
        self.grant(lookup=True);write_record(dataset_id=references.pk,user=self.member,payload=payload)
        record.is_archived=True;record.save()
        with self.assertRaises(ValidationError):write_record(dataset_id=references.pk,user=self.member,payload={**payload,'request_id':'archived'})

    def test_reference_schema_rejects_foreign_dataset(self):
        with self.assertRaises(ValidationError):Dataset.objects.create(organization=self.other,name='Wrong reference',schema={'fields':[{'id':'ref','label':'Ref','type':'record_reference','dataset_id':str(self.dataset.pk)}]})

    def test_ui_dataset_builder_record_and_history_render(self):
        record=self.create()
        for name,args in [('list',[self.org.slug]),('new',[self.org.slug]),('edit',[self.org.slug,self.dataset.pk]),('detail',[self.org.slug,self.dataset.pk]),('record-new',[self.org.slug,self.dataset.pk]),('record-edit',[self.org.slug,self.dataset.pk,record.pk]),('record',[self.org.slug,self.dataset.pk,record.pk])]:
            with self.subTest(name=name):self.assertEqual(self.client.get(reverse('datasets:'+name,args=args)).status_code,200)
        page=self.client.get(reverse('forms:form-edit',args=[self.org.slug,self.form.pk]));self.assertContains(page,'Record destination')
        prefill=self.client.get(self.url,{'record':str(record.pk)});self.assertContains(prefill,str(record.pk))
        self.assertEqual(self.client.get(self.url,{'record':'malformed'}).status_code,404)

    def test_html_dataset_and_record_creation(self):
        response=self.client.post(reverse('datasets:new',args=[self.org.slug]),{'name':'Assets','schema':json.dumps(SCHEMA),'label_field':'name'})
        self.assertEqual(response.status_code,302);dataset=Dataset.objects.get(name='Assets')
        result=self.client.post(reverse('datasets:record-new',args=[self.org.slug,dataset.pk]),{'schema_version_id':str(dataset.current_schema.pk),'request_id':'html','value_name':'Laptop'})
        self.assertEqual(result.status_code,302);self.assertEqual(dataset.records.get().data['name'],'Laptop')

    def test_api_csrf_protects_record_commands(self):
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.owner)
        response=browser.post(reverse('datasets:api-records',args=[self.dataset.pk]),json.dumps(self.command()),content_type='application/json')
        self.assertEqual(response.status_code,403);self.assertFalse(Record.objects.exists())

    def test_invalid_record_command_does_not_500(self):
        url=reverse('datasets:api-records',args=[self.dataset.pk])
        for data in ([],{},self.command(data={'name':[]} ),self.command(schema_version_id='invalid')):
            with self.subTest(data=data):self.assertEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,400)

    def test_organization_delete_includes_bound_forms_records_and_history(self):
        self.capture();self.create()
        result=self.client.post(reverse('organizations:settings',args=[self.org.slug]),{'action':'delete','confirm_name':self.org.name})
        self.assertEqual(result.status_code,302);self.assertFalse(Organization.objects.filter(pk=self.org.pk).exists());self.assertFalse(Record.objects.exists())


class DatasetConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner=get_user_model().objects.create_user('concurrent-owner')
        self.org=Organization.objects.create(name='Concurrent workspace',created_by=self.owner)
        OrganizationMembership.objects.create(organization=self.org,user=self.owner,role='admin')
        self.dataset=Dataset.objects.create(organization=self.org,name='Requests',schema=copy.deepcopy(SCHEMA))
        self.payload={'schema_version_id':str(self.dataset.current_schema.pk),'request_id':'create','data':{'name':'Initial'}}
        self.result=write_record(dataset_id=self.dataset.pk,user=self.owner,payload=self.payload)

    def race(self, payloads, record_id=None):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        barrier=threading.Barrier(2)
        dataset_id=self.dataset.pk;user=self.owner
        def worker(payload):
            barrier.wait(timeout=5)
            try:
                for _ in range(40):
                    try:return write_record(dataset_id=dataset_id,user=user,record_id=record_id,payload=payload)
                    except DatasetError as error:return error.error_code
                    except OperationalError:
                        connections.close_all();time.sleep(.01)
                return 'lock_timeout'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(worker,payloads))

    def test_concurrent_record_edits_accept_one_expected_version(self):
        results=self.race([{**self.payload,'request_id':key,'expected_version':1} for key in ('one','two')],record_id=self.result['id'])
        self.assertEqual(sum(isinstance(item,dict) for item in results),1,results)
        self.assertIn('record_conflict',results);self.assertEqual(RecordRevision.objects.count(),2)

    def test_concurrent_record_retry_creates_once(self):
        results=self.race([{**self.payload,'request_id':'same'}]*2)
        self.assertTrue(all(isinstance(item,dict) for item in results),results)
        self.assertEqual(sorted(item['replayed'] for item in results),[False,True]);self.assertEqual(Record.objects.count(),2)
