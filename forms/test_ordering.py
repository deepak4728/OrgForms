import json
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from .models import Catalog, CatalogItem, DynamicForm, SelectionLine, FormSubmission
from .item_options import validate_options
from organizations.models import Organization


class MenuOrderingTests(TestCase):
    def setUp(self):
        self.org=Organization.objects.create(name='Cafe')
        self.catalog=Catalog.objects.create(organization=self.org)
        self.item=CatalogItem.objects.create(catalog=self.catalog,name='Coffee',price='90',stock=4,options=[{'label':'Size','choices':['Regular','Large'],'required':True,'price_adjustments':{'Large':'30.00'}}])
        self.form=DynamicForm.objects.create(organization=self.org,title='Menu',status='active',visibility='public',schema={'fields':[{'id':'items','label':'Menu','type':'item_cards','required':True,'catalog_id':self.catalog.pk}]})
        self.url=reverse('forms:public-form',args=[self.org.slug,self.form.slug])

    def submit(self,lines):
        return self.client.post(self.url,json.dumps({'data':{'items':lines}}),content_type='application/json')

    def test_server_prices_configuration_and_saves_notes(self):
        response=self.submit([{'menu_item_id':self.item.pk,'quantity':2,'options':{'Size':'Large'},'notes':'Less ice','price':1}])
        self.assertEqual(response.status_code,201,response.content)
        line=SelectionLine.objects.get()
        self.assertEqual(line.unit_price,Decimal('120'))
        self.assertEqual(line.line_total,Decimal('240'))
        self.assertEqual(line.notes,'Less ice')

    def test_stock_is_aggregated_across_configurations(self):
        response=self.submit([{'menu_item_id':self.item.pk,'quantity':3,'options':{'Size':'Large'}},{'menu_item_id':self.item.pk,'quantity':2,'options':{'Size':'Regular'}}])
        self.assertEqual(response.status_code,400)
        self.assertFalse(FormSubmission.objects.exists())

    def test_missing_choice_and_long_notes_are_rejected(self):
        for options,notes in [({},''),({'Size':'Fake'},''),({'Size':'Regular'},'a'*501)]:
            self.assertEqual(self.submit([{'menu_item_id':self.item.pk,'quantity':1,'options':options,'notes':notes}]).status_code,400)

    def test_price_additions_are_bounded_and_finite(self):
        for value in ['NaN','Infinity','-1','1.001','100001']:
            with self.subTest(value=value),self.assertRaises(ValidationError):
                validate_options([{'label':'Size','choices':['Large'],'price_adjustments':{'Large':value}}])

    def test_public_page_loads_ordering_module(self):
        self.assertContains(self.client.get(self.url),'menu-ordering.js')
