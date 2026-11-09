import copy
import json
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from organizations.models import Organization, OrganizationMembership
from datasets.models import UIElement
from .models import Catalog, CatalogItem, DynamicForm, FormSubmission, ItemSelection
from .services import normalize_schema


class SimpleLibraryWorkflowTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user('simple-owner')
        self.member = get_user_model().objects.create_user('simple-member')
        self.org = Organization.objects.create(name='Simple cafe', created_by=self.owner)
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role='admin')
        OrganizationMembership.objects.create(organization=self.org, user=self.member, role='member')
        self.first = Catalog.objects.create(organization=self.org, name='Main', tax_rate='5')
        self.second = Catalog.objects.create(organization=self.org, name='Other', tax_rate='10')
        self.coffee = CatalogItem.objects.create(catalog=self.first, name='Coffee', category='Drinks', price=100, stock=4)
        self.tea = CatalogItem.objects.create(catalog=self.second, name='Tea', category='Drinks', price=50, stock=5)
        self.cake = CatalogItem.objects.create(catalog=self.second, name='Cake', category='Food', price=80)
        self.client.force_login(self.owner)

    def collection(self, **options):
        field = {'id':'items', 'label':'Menu', 'type':'item_cards', 'item_source':'organization', **options}
        schema = normalize_schema({'fields':[field]}, self.org)
        return DynamicForm.objects.create(organization=self.org, title='Order', status='active', visibility='public', schema=schema)

    def test_section_is_saved_as_copy_and_permissions_are_enforced(self):
        form = self.collection()
        original = copy.deepcopy(form.schema)
        url = reverse('datasets:api-elements', args=[self.org.slug])
        response = self.client.post(url, json.dumps({'name':'Order section','schema':original}), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        section = UIElement.objects.get(pk=response.json()['id'])
        section.schema['fields'][0]['label'] = 'Changed library label'
        section.save()
        form.refresh_from_db()
        self.assertEqual(form.schema, original)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url, json.dumps({'name':'No','schema':original}), content_type='application/json').status_code, 403)

    def test_item_popup_edits_existing_item_and_rejects_foreign_access(self):
        url = reverse('datasets:item-edit', args=[self.org.slug, self.coffee.pk]) + '?dialog=1'
        response = self.client.post(url, {'name':'Cold coffee', 'category':'Drinks', 'price':'110', 'stock':'3', 'is_available':'on', 'description':'Fresh', 'image_url':'', 'options':json.dumps([{'label':'Size','choices':['Regular','Large'],'price_adjustments':{'Large':'20'}}])})
        self.assertContains(response, 'orgforms:library-saved')
        self.coffee.refresh_from_db()
        self.assertEqual(self.coffee.price, Decimal('110'))
        self.assertEqual(self.coffee.options[0]['choices'], ['Regular','Large'])
        other = Organization.objects.create(name='Other organization')
        self.assertEqual(self.client.get(reverse('datasets:item-edit', args=[other.slug,self.coffee.pk])).status_code, 403)

    def test_category_list_accepts_items_from_both_owned_catalogs_with_correct_tax(self):
        form = self.collection(item_category='Drinks')
        response = self.client.post(reverse('forms:public-form', args=[self.org.slug,form.slug]), json.dumps({'data':{'items':[{'menu_item_id':self.coffee.pk,'quantity':1},{'menu_item_id':self.tea.pk,'quantity':1}]}}), content_type='application/json')
        self.assertEqual(response.status_code,201,response.content)
        selection = ItemSelection.objects.get()
        self.assertEqual(selection.subtotal, Decimal('150'))
        self.assertEqual(selection.tax, Decimal('10'))
        self.assertEqual(selection.total, Decimal('160'))

    def test_category_and_organization_are_enforced_on_submission(self):
        form = self.collection(item_category='Drinks')
        other = Catalog.objects.create(organization=Organization.objects.create(name='Foreign'))
        foreign = CatalogItem.objects.create(catalog=other,name='Foreign drink',category='Drinks',price=1)
        for item in [self.cake,foreign]:
            response=self.client.post(reverse('forms:public-form',args=[self.org.slug,form.slug]),json.dumps({'data':{'items':[{'menu_item_id':item.pk,'quantity':1}]}}),content_type='application/json')
            self.assertEqual(response.status_code,400,response.content)
        self.assertFalse(FormSubmission.objects.exists())

    def test_public_page_only_exports_items_used_by_its_fields(self):
        form=self.collection(item_category='Drinks')
        response=self.client.get(reverse('forms:public-form',args=[self.org.slug,form.slug]))
        names={item['name'] for item in response.context['menu_items']}
        self.assertEqual(names, {'Coffee','Tea'})
        plain=DynamicForm.objects.create(organization=self.org,title='Plain',status='active',visibility='public',schema={'fields':[{'id':'name','label':'Name','type':'text'}]})
        response=self.client.get(reverse('forms:public-form',args=[self.org.slug,plain.slug]))
        self.assertEqual(response.context['menu_items'], [])

    def test_library_defaults_to_items_and_has_saved_sections(self):
        response=self.client.get(reverse('datasets:library',args=[self.org.slug]))
        self.assertEqual(response.context['selected_view'],'items')
        self.assertContains(response,'Saved sections')
        self.assertContains(response,'Edit item')

    def test_delete_form_with_responses_requires_confirmation_and_preserves_other_forms(self):
        form = self.collection()
        other = self.collection()
        submission = FormSubmission.objects.create(form=form, organization=self.org, data={'items':[]})
        untouched = FormSubmission.objects.create(form=other, organization=self.org, data={'items':[]})
        url = reverse('forms:api-form-detail', args=[form.pk])
        self.client.force_login(self.member)
        self.assertEqual(self.client.delete(url, data=json.dumps({'confirm_title':form.title}), content_type='application/json').status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.delete(url, data=json.dumps({'confirm_title':'wrong'}), content_type='application/json').status_code, 400)
        self.assertTrue(FormSubmission.objects.filter(pk=submission.pk).exists())
        response = self.client.delete(url, data=json.dumps({'confirm_title':form.title}), content_type='application/json')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(DynamicForm.objects.filter(pk=form.pk).exists())
        self.assertFalse(FormSubmission.objects.filter(pk=submission.pk).exists())
        self.assertTrue(FormSubmission.objects.filter(pk=untouched.pk).exists())
        self.assertTrue(CatalogItem.objects.filter(pk=self.coffee.pk).exists())

    def test_page_starters_can_be_customized_saved_and_reused(self):
        from forms.element_catalog import STARTERS
        library = reverse('datasets:library', args=[self.org.slug])
        response = self.client.get(library + '?view=elements')
        self.assertContains(response, 'Ready-made sections')
        self.assertContains(response, 'Frequently asked questions')
        url = reverse('datasets:element-new', args=[self.org.slug]) + '?starter=welcome'
        response = self.client.get(url)
        self.assertEqual(response.context['form'].instance.schema, STARTERS['welcome']['schema'])
        schema = copy.deepcopy(STARTERS['welcome']['schema'])
        schema['fields'][0]['label'] = 'Welcome to our workshop'
        response = self.client.post(url, {'name': 'Workshop welcome', 'description': 'Our introduction', 'schema': json.dumps(schema)})
        self.assertEqual(response.status_code, 302)
        section = UIElement.objects.get(organization=self.org, name='Workshop welcome')
        self.assertEqual(section.schema, schema)
        self.assertEqual(STARTERS['welcome']['schema']['fields'][0]['label'], 'Welcome')
        response = self.client.get(reverse('datasets:api-elements', args=[self.org.slug]))
        self.assertContains(response, 'Workshop welcome')
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_section_preview_uses_shared_renderer_and_scoped_items(self):
        other = Catalog.objects.create(organization=Organization.objects.create(name='Private catalog'))
        foreign = CatalogItem.objects.create(catalog=other, name='Private item', price=1)
        response = self.client.get(reverse('datasets:element-new', args=[self.org.slug]) + '?starter=order')
        self.assertContains(response, 'form-renderer.js')
        self.assertEqual({item['id'] for item in response.context['preview_items']}, {self.coffee.pk, self.tea.pk, self.cake.pk})
        self.assertNotIn(foreign.pk, {item['id'] for item in response.context['preview_items']})
        form = self.collection()
        response = self.client.get(reverse('forms:public-form', args=[self.org.slug, form.slug]))
        self.assertContains(response, 'form-renderer.js')
        self.assertContains(response, 'OrgFormsFields.mount')
