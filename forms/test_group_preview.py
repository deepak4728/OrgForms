from django.template.loader import render_to_string
from django.test import SimpleTestCase
from .templatetags.form_preview import grouped_preview


class GroupPreviewTests(SimpleTestCase):
    def test_nested_fields_share_saved_groups_and_visibility(self):
        fields=[{'id':'name','label':'Name','type':'text','ui_group':'contact','ui_group_label':'Contact','ui_group_show_frame':False,'ui_group_path':[{'id':'booking','label':'Booking','layout':'horizontal'}]}, {'id':'email','label':'Email','type':'email','ui_group':'contact','ui_group_label':'Contact','ui_group_show_frame':False,'ui_group_path':[{'id':'booking','label':'Booking','layout':'horizontal'}]}]
        nodes=grouped_preview(fields)
        self.assertEqual(len(nodes),1)
        self.assertEqual(len(nodes[0]['children'][0]['children']),2)
        html=render_to_string('organizations/partials/form_preview_nodes.html',{'nodes':nodes})
        self.assertIn('data-layout="horizontal"',html)
        self.assertIn('is-frameless',html)
        self.assertNotIn('<h3>Contact</h3>',html)
        self.assertIn('<h3>Booking</h3>',html)
        self.assertEqual(fields[0]['label'],'Name')

    def test_names_remain_escaped(self):
        html=render_to_string('organizations/partials/form_preview_nodes.html',{'nodes':grouped_preview([{'id':'x','label':'<script>','ui_group':'g','ui_group_label':'<img>'}])})
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;img&gt;',html)
