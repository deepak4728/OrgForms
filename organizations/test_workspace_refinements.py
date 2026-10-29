from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from forms.models import DynamicForm
from organizations.models import Organization, Department, StaffAssignment, OrganizationMembership
from accounts.models import AccountSpace


class WorkspaceRefinementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(username="workspace-owner", email="owner@example.test")
        cls.member = User.objects.create_user(username="workspace-member", email="member@example.test")
        cls.outsider = User.objects.create_user(username="workspace-outsider", email="outsider@example.test")
        cls.org = Organization.objects.create(name="Owned team", created_by=cls.owner)
        cls.shared = Organization.objects.create(name="Other team", created_by=cls.outsider)
        for org, user, role in ((cls.org, cls.owner, "admin"), (cls.org, cls.member, "member"), (cls.shared, cls.outsider, "admin")):
            OrganizationMembership.objects.create(organization=org, user=user, role=role)
        AccountSpace.objects.create(user=cls.owner, kind=AccountSpace.ORGANIZATION_CREATE)
        AccountSpace.objects.create(user=cls.member, kind=AccountSpace.ORGANIZATION_JOIN)
        AccountSpace.objects.create(user=cls.outsider, kind=AccountSpace.ORGANIZATION_CREATE)
        cls.form = DynamicForm.objects.create(organization=cls.org, title="Team intake", slug="team-intake", created_by=cls.owner)
        cls.department = Department.objects.create(organization=cls.org, name="Reviewers")
        StaffAssignment.objects.create(department=cls.department, membership=cls.org.memberships.get(user=cls.member))
        cls.form.allowed_departments.add(cls.department)

    def setUp(self):
        self.client.force_login(self.owner)

    def test_dashboard_opens_the_accounts_organization(self):
        url = reverse("organizations:dashboard")
        self.assertRedirects(self.client.get(url), reverse("organizations:detail", args=[self.org.slug]))

    def test_workspace_navigation_does_not_offer_organization_switching(self):
        response = self.client.get(reverse('organizations:detail', args=[self.org.slug]))
        self.assertContains(response, 'id="workspace-nav-link"')
        self.assertNotContains(response, 'Choose organization')
        self.assertNotContains(response, reverse('organizations:detail', args=[self.shared.slug]))
        self.assertNotContains(response, 'Switch space')
        self.assertNotContains(response, '>Dashboard</a>')
        self.assertNotContains(response, '>Forms</a>')
        self.shared.is_archived = True
        self.shared.save(update_fields=['is_archived'])
        response = self.client.get(reverse('organizations:detail', args=[self.org.slug]))
        self.assertNotContains(response, f'href="{reverse("organizations:detail", args=[self.shared.slug])}"')

    def test_organization_account_cannot_open_personal_space(self):
        response = self.client.get(reverse('organizations:dashboard'), {'space': 'personal'})
        self.assertEqual(response.status_code, 403)

    def test_forms_keep_context_and_share_settings_dialog(self):
        response = self.client.get(reverse("organizations:detail", args=[self.org.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Owned team · OrgForms</title>", html=True)
        self.assertContains(response, f'/org/{self.org.slug}/submissions/?form={self.form.pk}')
        self.assertContains(response, f'data-open-manage="{self.org.slug}"')
        self.assertContains(response, f'id="manage-{self.org.slug}"')
        self.assertContains(response, 'name="return_to" value="organization"')
        self.assertContains(response, 'data-form-status-value="draft"')
        response = self.client.post(reverse("organizations:settings", args=[self.org.slug]), {
            "action": "update-details", "return_to": "organization", "name": "Updated team", "business_type": "generic",
        })
        self.assertRedirects(response, reverse("organizations:detail", args=[self.org.slug]) + f'?manage={self.org.slug}&tab=details')

    def test_department_access_and_membership_revocation(self):
        from organizations.permissions import visible_forms, can_respond_to_form
        self.form.visibility = "restricted"
        self.form.status = "active"
        self.form.save()
        self.assertTrue(visible_forms(self.member, self.org).filter(pk=self.form.pk).exists())
        self.assertTrue(can_respond_to_form(self.member, self.form))
        self.department.is_archived = True
        self.department.save()
        self.assertFalse(visible_forms(self.member, self.org).filter(pk=self.form.pk).exists())
        self.department.is_archived = False
        self.department.save()
        self.assertTrue(can_respond_to_form(self.member, self.form))
        membership = self.org.memberships.get(user=self.member)
        self.client.post(reverse("organizations:settings", args=[self.org.slug]), {"action":"remove-member", "return_to":"people", "membership_id":membership.pk})
        self.assertFalse(self.department.staff_assignments.exists())
        self.assertFalse(can_respond_to_form(self.member, self.form))

    def test_department_form_grants_are_organization_scoped(self):
        foreign = Department.objects.create(organization=self.shared, name="Other")
        response = self.client.patch(reverse("forms:api-form-detail", args=[self.form.pk]), data={"visibility":"restricted", "access_departments":[foreign.pk]}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.form.allowed_departments.filter(pk=foreign.pk).exists())

    def test_explicit_department_grant_can_be_saved_without_individual_accounts(self):
        from organizations.permissions import can_respond_to_form
        self.form.status = "active"
        self.form.save()
        response = self.client.patch(reverse("forms:api-form-detail", args=[self.form.pk]), data={"visibility":"restricted", "access_emails":[], "access_departments":[self.department.pk]}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.form.refresh_from_db()
        self.assertTrue(can_respond_to_form(self.member, self.form))
        self.assertEqual(self.form.allowed_departments.count(), 1)

    def test_people_and_submissions_render_task_specific_controls(self):
        people = self.client.get(reverse("organizations:people", args=[self.org.slug]))
        self.assertEqual(people.status_code, 200)
        self.assertContains(people, 'data-people-panel="departments"')
        self.assertContains(people, f'id="department-{self.department.pk}"')
        submissions = self.client.get(reverse("forms:all-submissions", args=[self.org.slug]), {"form": self.form.pk})
        self.assertEqual(submissions.status_code, 200)
        self.assertContains(submissions, "Pending review")
        self.assertContains(submissions, "Export CSV")
        self.assertEqual(submissions.context["selected_form"].pk, self.form.pk)

    def test_adding_existing_member_does_not_silently_replace_their_role(self):
        response = self.client.post(reverse("organizations:settings", args=[self.org.slug]), {
            "action": "add-member", "return_to": "people", "email": self.owner.email, "role": "member",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org, user=self.owner).role, "admin")
        self.client.post(reverse("organizations:settings", args=[self.org.slug]), {
            "action": "add-member", "return_to": "people", "email": self.member.email, "role": "admin",
        })
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org, user=self.member).role, "member")
