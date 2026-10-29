from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from forms.models import DynamicForm
from .models import Organization, OrganizationMembership, Department, StaffAssignment, DepartmentStewardship
from .permissions import visible_forms, can_manage_form


class DepartmentTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user('department-admin')
        self.staff = get_user_model().objects.create_user('department-staff')
        self.outsider = get_user_model().objects.create_user('department-other')
        self.org = Organization.objects.create(name='Research team', created_by=self.admin)
        self.other_org = Organization.objects.create(name='Other workspace')
        self.admin_membership = OrganizationMembership.objects.create(organization=self.org,user=self.admin,role='admin')
        self.staff_membership = OrganizationMembership.objects.create(organization=self.org,user=self.staff,role='member')
        self.other_membership = OrganizationMembership.objects.create(organization=self.other_org,user=self.outsider,role='admin')
        self.url = reverse('organizations:people', kwargs={'org_slug':self.org.slug})
        self.client.force_login(self.admin)
        self.collection = DynamicForm.objects.create(organization=self.org,title='Private collection',visibility='restricted',schema={'fields':[{'id':'name','type':'text','label':'Name'}]})

    def test_create_assign_and_edit_departments(self):
        result = self.client.post(self.url, {'action':'save-department','name':'Operations','description':'Handles requests','members':[self.staff_membership.pk],'collections':[self.collection.pk]})
        self.assertRedirects(result, self.url+'#departments')
        department = self.org.departments.get()
        self.assertEqual(department.staff_assignments.get().membership, self.staff_membership)
        self.assertEqual(department.stewardships.get().collection, self.collection)
        self.client.post(self.url, {'action':'save-department','name':'Research','members':[self.staff_membership.pk]})
        self.assertEqual(self.staff_membership.department_assignments.count(), 2)
        self.client.post(self.url, {'action':'save-department','department_id':department.pk,'name':'Operations updated'})
        department.refresh_from_db()
        self.assertEqual(department.name, 'Operations updated')
        self.assertEqual(department.staff_assignments.count(), 0)
        self.assertEqual(department.stewardships.count(), 0)

    def test_cross_tenant_staff_collection_and_department_are_rejected(self):
        foreign = Department.objects.create(organization=self.other_org,name='Other')
        foreign_collection = DynamicForm.objects.create(organization=self.other_org,title='Other',schema={'fields':[{'id':'name','type':'text','label':'Name'}]})
        for data in [{'members':[self.other_membership.pk]}, {'collections':[foreign_collection.pk]}]:
            result = self.client.post(self.url, {'action':'save-department','name':'Invalid',**data})
            self.assertEqual(result.status_code, 200)
            self.assertFalse(self.org.departments.exists())
        result = self.client.post(self.url, {'action':'archive-department','department_id':foreign.pk})
        self.assertEqual(result.status_code, 404)
        with self.assertRaises(ValidationError):
            StaffAssignment.objects.create(department=foreign,membership=self.staff_membership)
        with self.assertRaises(ValidationError):
            DepartmentStewardship.objects.create(department=foreign,collection=self.collection)

    def test_assignments_do_not_grant_restricted_access(self):
        department = Department.objects.create(organization=self.org,name='Review')
        StaffAssignment.objects.create(department=department,membership=self.staff_membership)
        DepartmentStewardship.objects.create(department=department,collection=self.collection)
        self.assertFalse(visible_forms(self.staff,self.org).filter(pk=self.collection.pk).exists())
        self.assertFalse(can_manage_form(self.staff,self.collection))
        self.client.force_login(self.staff)
        result = self.client.get(self.url)
        self.assertNotContains(result, 'Private collection')
        result = self.client.post(self.url, {'action':'save-department','name':'Forbidden'})
        self.assertEqual(result.status_code,403)

    def test_archive_restore_and_membership_revocation(self):
        department = Department.objects.create(organization=self.org,name='Support')
        assignment = StaffAssignment.objects.create(department=department,membership=self.staff_membership)
        self.client.post(self.url, {'action':'archive-department','department_id':department.pk})
        department.refresh_from_db()
        self.assertTrue(department.is_archived)
        self.assertTrue(StaffAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertEqual(self.client.post(self.url, {'action':'save-department','department_id':department.pk,'name':'Changed'}).status_code,403)
        self.client.post(self.url, {'action':'restore-department','department_id':department.pk})
        department.refresh_from_db()
        self.assertFalse(department.is_archived)
        self.staff_membership.delete()
        self.assertFalse(StaffAssignment.objects.filter(pk=assignment.pk).exists())

    def test_names_unique_per_organization_and_no_mandatory_department(self):
        Department.objects.create(organization=self.org,name='Research')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Department.objects.create(organization=self.org,name='research')
        Department.objects.create(organization=self.other_org,name='Research')
        self.assertIsNotNone(DynamicForm.objects.create(organization=self.other_org,title='Survey without departments',schema={'fields':[{'id':'name','type':'text','label':'Name'}]}).pk)
