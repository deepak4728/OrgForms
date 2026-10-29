from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import AccountSpace, UserPortfolio
from forms.models import DynamicForm
from organizations.models import Organization, OrganizationMembership


class AccountSpaceTests(TestCase):
    def signup(self, kind, email):
        return self.client.post(reverse("accounts:signup"), {
            "space": kind, "email": email,
            "password1": "different-strong-pass-249!", "password2": "different-strong-pass-249!",
        })

    def test_deleting_organization_does_not_open_creation_dialog(self):
        self.signup("organization_create", "owner@example.test")
        self.client.get(reverse("organizations:dashboard"))
        self.client.post(reverse("organizations:dashboard"), {"name": "Research Lab", "business_type": "education"})
        org = Organization.objects.get(name="Research Lab")
        response = self.client.post(reverse("organizations:settings", args=[org.slug]), {"action": "delete", "confirm_name": org.name})
        self.assertRedirects(response, reverse("organizations:dashboard"), fetch_redirect_response=False)
        self.assertFalse(Organization.objects.filter(pk=org.pk).exists())
        self.assertNotContains(self.client.get(reverse("organizations:dashboard")), 'data-open-on-load="true"')

    def test_personal_signup_is_separate_from_organizations(self):
        response = self.signup("personal", "person@example.test")
        self.assertRedirects(response, reverse("organizations:dashboard") + "?space=personal")
        user = get_user_model().objects.get(email="person@example.test")
        self.assertEqual(user.account_space.kind, AccountSpace.PERSONAL)
        self.assertContains(self.client.get(reverse("organizations:dashboard")), "Forms for you")
        self.assertEqual(self.client.post(reverse("organizations:api-orgs"), {"name": "No"}).status_code, 403)
        with self.assertRaises(ValidationError):
            OrganizationMembership.objects.create(organization=Organization.objects.create(name="Other"), user=user)

    def test_organization_signup_opens_ai_setup_then_creates_one_org(self):
        self.assertRedirects(self.signup("organization_create", "owner@example.test"), reverse("organizations:dashboard"), fetch_redirect_response=False)
        page = self.client.get(reverse("organizations:dashboard"))
        self.assertContains(page, 'data-open-on-load="true"')
        self.assertContains(page, 'id="organization-draft-prompt"')
        self.assertNotContains(page, 'data-voice-record')
        response = self.client.post(reverse("organizations:dashboard"), {"name": "Research Lab", "business_type": "education"})
        org = Organization.objects.get(name="Research Lab")
        self.assertRedirects(response, reverse("organizations:detail", args=[org.slug]))
        self.assertEqual(org.memberships.get().role, "admin")
        self.assertEqual(self.client.post(reverse("organizations:api-orgs"), {"name": "Second"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("organizations:dashboard"), {"name": "Second"}).status_code, 403)
        self.assertFalse(Organization.objects.filter(name="Second").exists())
        page = self.client.get(reverse("organizations:detail", args=[org.slug]))
        self.assertNotContains(page, "Switch space")
        self.assertNotContains(page, "Choose organization")
        self.assertEqual(self.client.get(reverse("organizations:dashboard"), {"space": "personal"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("accounts:profile"), {"action": "portfolio", "profile_data": "{}"}).status_code, 403)
        self.assertFalse(UserPortfolio.objects.filter(user=org.created_by).exists())

    def test_join_account_waits_until_admin_adds_it_and_cannot_join_another(self):
        owner = get_user_model().objects.create_user("owner", email="owner@example.test")
        AccountSpace.objects.create(user=owner, kind=AccountSpace.ORGANIZATION_CREATE)
        org = Organization.objects.create(name="Research", created_by=owner)
        OrganizationMembership.objects.create(organization=org, user=owner, role="admin")
        self.assertRedirects(self.signup("organization_join", "member@example.test"), reverse("organizations:dashboard"))
        member = get_user_model().objects.get(email="member@example.test")
        self.assertContains(self.client.get(reverse("organizations:dashboard")), "Ask an organization admin")
        self.assertEqual(self.client.post(reverse("organizations:dashboard"), {"name": "No"}).status_code, 403)
        self.client.force_login(owner)
        self.client.post(reverse("organizations:settings", args=[org.slug]), {
            "action": "add-member", "email": member.email, "role": "member",
        })
        self.assertTrue(OrganizationMembership.objects.filter(user=member, organization=org).exists())
        other = Organization.objects.create(name="Other")
        with self.assertRaises(ValidationError):
            OrganizationMembership.objects.create(user=member, organization=other)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationMembership.objects.bulk_create([OrganizationMembership(user=member, organization=other)])
        self.client.force_login(member)
        self.assertRedirects(self.client.get(reverse("organizations:dashboard")), reverse("organizations:detail", args=[org.slug]))
        self.assertEqual(self.client.get(reverse("organizations:detail", args=[other.slug])).status_code, 403)

    def test_ownership_transfer_keeps_both_accounts_in_same_organization(self):
        User = get_user_model()
        owner = User.objects.create_user("owner", email="owner@example.test")
        member = User.objects.create_user("member", email="member@example.test")
        AccountSpace.objects.create(user=owner, kind=AccountSpace.ORGANIZATION_CREATE)
        AccountSpace.objects.create(user=member, kind=AccountSpace.ORGANIZATION_JOIN)
        org = Organization.objects.create(name="Research", created_by=owner)
        OrganizationMembership.objects.create(organization=org, user=owner, role="admin")
        target = OrganizationMembership.objects.create(organization=org, user=member, role="member")
        self.client.force_login(owner)
        self.client.post(reverse("organizations:settings", args=[org.slug]), {
            "action": "transfer-ownership", "membership_id": target.pk,
        })
        org.refresh_from_db()
        self.assertEqual(org.created_by, member)
        self.assertEqual(org.memberships.get(user=member).role, "admin")
        self.assertEqual(org.memberships.get(user=owner).role, "manager")

    def test_form_owner_changes_within_organization_only(self):
        User = get_user_model()
        owner = User.objects.create_user("owner")
        manager = User.objects.create_user("manager")
        org = Organization.objects.create(name="Research", created_by=owner)
        other = Organization.objects.create(name="Other")
        OrganizationMembership.objects.create(organization=org, user=owner, role="admin")
        target = OrganizationMembership.objects.create(organization=org, user=manager, role="manager")
        form = DynamicForm.objects.create(organization=org, title="Feedback", created_by=owner)
        self.client.force_login(owner)
        url = reverse("forms:api-form-transfer", args=[form.pk])
        self.assertEqual(self.client.post(url, {"organization": other.slug, "owner_membership": target.pk}).status_code, 403)
        self.assertEqual(self.client.post(url, {"organization": org.slug, "owner_membership": target.pk}).status_code, 200)
        form.refresh_from_db()
        self.assertEqual(form.created_by, manager)
        self.assertEqual(form.organization, org)
