import copy
import json
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from organizations.models import Organization, OrganizationMembership
from .capture import CaptureError, capture_submission, change_submission_status
from .models import Catalog, CatalogItem, CaptureReceipt, CollectionRevision, DynamicForm, FormSubmission, ItemSelection, SubmissionRevision


SCHEMA = {"fields": [{"id": "answer", "label": "Original question", "type": "text", "required": True}]}


class VersionedCaptureTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("owner", email="owner@example.test")
        self.member = get_user_model().objects.create_user("member")
        self.other = get_user_model().objects.create_user("other")
        self.org = Organization.objects.create(name="Research team", created_by=self.owner)
        for user, role in ((self.owner, "admin"), (self.member, "member")):
            OrganizationMembership.objects.create(organization=self.org, user=user, role=role)
        self.form = DynamicForm.objects.create(organization=self.org, title="Survey", schema=copy.deepcopy(SCHEMA), status="active", visibility="public")
        self.url = reverse("forms:public-form", args=[self.org.slug, self.form.slug])
        self.client.get(self.url)

    def post(self, *, client=None, **extra):
        payload = {"data": {"answer": "Accepted"}, "revision_id": str(self.form.current_revision.pk), **extra}
        return (client or self.client).post(self.url, json.dumps(payload), content_type="application/json")

    def test_definition_changes_publish_immutable_snapshots_only_when_needed(self):
        original = self.form.current_revision
        self.form.visibility = "organization"
        self.form.save()
        self.assertEqual(self.form.revisions.count(), 1)
        self.form.schema["fields"][0]["label"] = "New question"
        self.form.save()
        self.assertEqual(self.form.current_revision.number, 2)
        original.refresh_from_db()
        self.assertEqual(original.schema["fields"][0]["label"], "Original question")
        original.title = "Tampered"
        with self.assertRaises(ValidationError):
            original.save()
        with self.assertRaises(ValidationError):
            CollectionRevision.objects.filter(pk=original.pk).update(title="Tampered")

    def test_stale_browser_capture_is_rejected_without_creating_any_records(self):
        old = str(self.form.current_revision.pk)
        self.form.schema["fields"].append({"id": "consent", "label": "Consent", "type": "checkbox", "required": True})
        self.form.save()
        result = self.post(revision_id=old)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["code"], "revision_conflict")
        self.assertFalse(FormSubmission.objects.exists())

    def test_response_edits_keep_the_original_definition_and_history(self):
        first = self.post(request_id="create").json()
        old_revision = self.form.current_revision
        self.form.schema = {"fields": [{"id": "new", "label": "Unrelated", "type": "number", "required": True}]}
        self.form.save()
        updated = self.post(data={"answer": "Corrected"}, revision_id=str(old_revision.pk), edit_token=first["edit_token"], expected_version=1, request_id="edit")
        self.assertEqual(updated.status_code, 200)
        submission = FormSubmission.objects.get()
        self.assertEqual(submission.collection_revision_id, old_revision.pk)
        self.assertEqual(submission.version, 2)
        self.assertEqual(list(submission.revisions.order_by("number").values_list("data", flat=True)), [{"answer": "Accepted"}, {"answer": "Corrected"}])
        self.client.force_login(self.owner)
        records = self.client.get(reverse("forms:submissions", args=[self.org.slug, self.form.pk]))
        self.assertContains(records, "Original question")
        self.assertContains(records, "Response history")

    def test_stale_editor_cannot_overwrite_newer_form(self):
        old = str(self.form.current_revision.pk)
        self.form.title = "Published elsewhere"
        self.form.save()
        self.client.force_login(self.owner)
        response = self.client.patch(reverse("forms:api-form-detail", args=[self.form.pk]), json.dumps({"title": "Stale overwrite", "base_revision": old}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.form.refresh_from_db()
        self.assertEqual(self.form.title, "Published elsewhere")

    def test_html_editor_does_not_refresh_a_stale_token_when_showing_an_error(self):
        original = str(self.form.current_revision.pk)
        self.form.title = "Another editor's version"
        self.form.save()
        self.client.force_login(self.owner)
        url = reverse("forms:form-edit", args=[self.org.slug, self.form.pk])
        for _ in range(2):
            response = self.client.post(url, {"title": "Stale draft", "base_revision": original, "schema": json.dumps(SCHEMA), "visibility": "public", "status": "active"})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'name="base_revision" value="' + original + '"')
            self.form.refresh_from_db()
            self.assertEqual(self.form.title, "Another editor's version")

    def test_retries_return_one_receipt_even_after_definition_changes(self):
        revision = str(self.form.current_revision.pk)
        first = self.post(request_id="retry", revision_id=revision)
        self.form.title = "Updated survey"
        self.form.save()
        retry = self.post(request_id="retry", revision_id=revision)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["replayed"])
        self.assertEqual(first.json()["submission_id"], retry.json()["submission_id"])
        self.assertEqual(first.json()["edit_token"], retry.json()["edit_token"])
        self.assertEqual(FormSubmission.objects.count(), 1)
        self.assertEqual(SubmissionRevision.objects.count(), 1)
        mismatch = self.post(request_id="retry", revision_id=revision, data={"answer": "Different"})
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.json()["code"], "request_conflict")

    def test_retry_keys_and_edit_tokens_are_scoped_to_the_caller(self):
        first = self.post(request_id="shared").json()
        stranger = Client()
        stranger.get(self.url)
        self.assertEqual(self.post(client=stranger, request_id="shared").status_code, 201)
        response = self.post(client=stranger, edit_token=first["edit_token"])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(FormSubmission.objects.count(), 2)

    def test_quota_caps_new_responses_but_allows_retry_and_edit(self):
        self.form.response_limit = 1
        self.form.save()
        first = self.post(request_id="one").json()
        self.assertEqual(self.post(request_id="one").status_code, 200)
        self.assertEqual(self.post(request_id="two").json()["code"], "response_limit_reached")
        edit = self.post(request_id="edit", edit_token=first["edit_token"], expected_version=1, data={"answer": "Changed"})
        self.assertEqual(edit.status_code, 200)
        stale = self.post(request_id="edit-stale", edit_token=first["edit_token"], expected_version=1)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(FormSubmission.objects.get().version, 2)
        self.assertEqual(FormSubmission.objects.count(), 1)

    def test_history_and_definitions_require_current_workspace_permissions(self):
        saved = self.post().json()
        history = reverse("forms:api-submission-history", args=[saved["submission_id"]])
        definitions = reverse("forms:api-collection-revisions", args=[self.form.pk])
        for user in (self.other, self.owner):
            self.client.force_login(user)
            for url in (history, definitions):
                self.assertEqual(self.client.get(url).status_code, 200 if user == self.owner else 403)
        self.form.visibility = "restricted"
        self.form.save()
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(history).status_code, 403)

    def test_revocation_also_prevents_receipt_replay(self):
        self.client.force_login(self.member)
        self.form.visibility = "organization"
        self.form.save()
        self.assertEqual(self.post(request_id="member-retry").status_code, 201)
        self.org.memberships.filter(user=self.member).delete()
        self.assertEqual(self.post(request_id="member-retry").status_code, 403)

    def test_api_and_browser_share_validation_and_do_not_depend_on_ai(self):
        self.client.force_login(self.member)
        url = reverse("forms:api-submissions", args=[self.form.pk])
        with patch("ai_gateway.services.open_model_response", side_effect=RuntimeError("AI unavailable")):
            bad = self.client.post(url, json.dumps({"data": {}}), content_type="application/json")
            good = self.client.post(url, json.dumps({"data": {"answer": "API"}, "request_id": "api"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(good.status_code, 201)
        self.assertEqual(SubmissionRevision.objects.get().source, "api")

    def test_failed_commit_is_retryable_and_never_acknowledged(self):
        with patch("forms.capture.record_revision", side_effect=OperationalError("Disk full")):
            response = self.post(request_id="disk-error")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "capture_unavailable")
        self.assertFalse(FormSubmission.objects.exists())
        self.assertFalse(CaptureReceipt.objects.exists())
        self.assertEqual(self.post(request_id="disk-error").status_code, 201)

    def test_api_csrf_protection_is_retained_for_capture(self):
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.member)
        response = protected.post(reverse("forms:api-submissions", args=[self.form.pk]), json.dumps({"data": {"answer": "blocked"}}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(FormSubmission.objects.exists())

    def test_status_changes_are_audited_and_check_expected_version(self):
        saved = self.post().json()
        submission = change_submission_status(submission_id=saved["submission_id"], user=self.owner, status="approved", expected_version=1)
        self.assertEqual(submission.version, 2)
        latest = submission.revisions.first()
        self.assertEqual((latest.actor_id, latest.event, latest.status), (self.owner.pk, "status_changed", "approved"))
        with self.assertRaises(CaptureError):
            change_submission_status(submission_id=submission.pk, user=self.owner, status="rejected", expected_version=1)

    def test_submission_cannot_reference_another_organization_or_definition(self):
        foreign_org = Organization.objects.create(name="Another organization")
        foreign_form = DynamicForm.objects.create(organization=foreign_org, title="Foreign", schema=SCHEMA)
        with self.assertRaises(ValidationError):
            FormSubmission.objects.create(form=self.form, organization=foreign_org, data={})
        with self.assertRaises(ValidationError):
            FormSubmission.objects.create(form=self.form, organization=self.org, collection_revision=foreign_form.current_revision, data={})
        self.assertEqual(self.post(revision_id=str(foreign_form.current_revision.pk)).status_code, 409)

    def test_three_organization_categories_use_the_same_capture_contract(self):
        for category in ("generic", "education", "cafe"):
            self.org.business_type = category
            self.org.save()
            self.assertEqual(self.post(request_id=category).status_code, 201)
        self.assertFalse(ItemSelection.objects.exists())

    def test_manual_builder_works_without_ai_and_quota_policy_is_privileged(self):
        self.client.force_login(self.owner)
        self.org.business_type = "cafe"
        self.org.save()
        page = self.client.get(reverse("forms:form-new", args=[self.org.slug]))
        self.assertNotContains(page, "Restaurant &amp; Cafe Service Sub-Category")
        result = self.client.post(reverse("forms:form-new", args=[self.org.slug]), {"title": "Registration", "schema": json.dumps(SCHEMA), "visibility": "public", "status": "active", "response_limit": "100"})
        self.assertEqual(result.status_code, 302)
        form = DynamicForm.objects.get(title="Registration")
        self.assertEqual(form.response_limit, 100)
        invalid = self.client.patch(reverse("forms:api-form-detail", args=[form.pk]), json.dumps({"response_limit": 10**50}), content_type="application/json")
        self.assertEqual(invalid.status_code, 400)
        # Legacy definitions may have no creator; they must not break the
        # post-save workspace page when listed beside a newly created form.
        page = self.client.get(reverse("organizations:detail", args=[self.org.slug]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Organization admins")
        form.editors.add(self.member)
        self.client.force_login(self.member)
        result = self.client.patch(reverse("forms:api-form-detail", args=[form.pk]), json.dumps({"response_limit": None}), content_type="application/json")
        self.assertEqual(result.status_code, 403)

    def test_hidden_values_cannot_make_a_dependent_hidden_field_persist(self):
        self.form.schema = {"dialect": "orgforms-fields-v1", "fields": [
            {"id": "show", "label": "Show", "type": "checkbox"},
            {"id": "parent", "label": "Parent", "type": "text", "visibleWhen": {"field": "show", "equals": True}},
            {"id": "child", "label": "Child", "type": "text", "visibleWhen": {"field": "parent", "equals": "secret"}},
        ]}
        self.form.save()
        response = self.post(data={"show": False, "parent": "secret", "child": "must not persist"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(FormSubmission.objects.get().data, {"show": False})
        self.form.schema["fields"][0]["visibleWhen"] = {"field": "child", "equals": "x"}
        with self.assertRaises(ValidationError):
            self.form.save()
        self.form.schema = {"dialect": "unknown", "fields": SCHEMA["fields"]}
        with self.assertRaises(ValidationError):
            self.form.save()

    def test_recorded_collection_cannot_be_reassigned_to_a_different_tenant(self):
        self.post()
        self.form.organization = Organization.objects.create(name="Other")
        with self.assertRaises(ValidationError):
            self.form.save()

    def test_catalog_price_snapshots_and_retries_do_not_mutate_prior_versions(self):
        item = CatalogItem.objects.create(catalog=Catalog.for_organization(self.org), name="Workshop kit", price="25.00")
        self.form.schema = {"fields": [{"id": "items", "label": "Workshop kits", "type": "item_cards", "required": True}]}
        self.form.save()
        data = {"items": [{"catalog_item_id": item.pk, "quantity": 2, "price": "0.01"}]}
        first = self.post(data=data, request_id="items").json()
        item.name = "New kit name"
        item.price = "50.00"
        item.save()
        self.assertEqual(self.post(data=data, request_id="items").status_code, 200)
        self.assertEqual(ItemSelection.objects.get().total, 50)
        response = self.post(data=data, request_id="edit-items", edit_token=first["edit_token"], expected_version=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ItemSelection.objects.get().total, 100)
        original = FormSubmission.objects.get().revisions.get(number=1)
        self.assertEqual(original.item_selections[0]["total"], "50.00")
        self.assertEqual(original.item_selections[0]["lines"][0]["name"], "Workshop kit")

    def test_uploaded_versions_remain_private_and_failures_remove_new_bytes(self):
        self.form.schema = {"fields": [{"id": "document", "label": "Document", "type": "file", "required": True}]}
        self.form.save()
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            first = self.client.post(self.url, {"data": "{}", "document": SimpleUploadedFile("original.pdf", b"%PDF-1.7 original")}).json()
            replacement = self.client.post(self.url, {"data": "{}", "edit_token": first["edit_token"], "expected_version": 1, "document": SimpleUploadedFile("replacement.pdf", b"%PDF-1.7 replacement")})
            self.assertEqual(replacement.status_code, 200)
            submission = FormSubmission.objects.get()
            self.assertEqual(submission.attachments.count(), 2)
            self.assertEqual(submission.current_attachments.count(), 1)
            original = submission.attachments.get(original_name="original.pdf")
            self.assertTrue(Path(original.file.path).is_file())
            download = reverse("forms:submission-attachment", args=[original.pk])
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(download).status_code, 403)
            self.client.force_login(self.owner)
            response = self.client.get(download)
            self.assertEqual(response.status_code, 200)
            response.close()
            with patch("forms.capture.record_revision", side_effect=RuntimeError("Database failure")):
                with self.assertRaises(RuntimeError):
                    self.client.post(self.url, {"data": "{}", "document": SimpleUploadedFile("failed.pdf", b"%PDF-1.7 failed")})
            self.assertEqual(FormSubmission.objects.count(), 1)
            self.assertEqual(len([path for path in Path(media).rglob("*") if path.is_file()]), 2)


class CaptureContentionTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Public event")
        self.form = DynamicForm.objects.create(organization=self.org, title="Registration", schema=SCHEMA, status="active", visibility="public", response_limit=1)

    def race(self, keys):
        barrier = threading.Barrier(2)
        form_id = self.form.pk

        def worker(key):
            barrier.wait(timeout=5)
            try:
                for attempt in range(30):
                    try:
                        return capture_submission(form_id=form_id, user=AnonymousUser(), owner_hash="same-client", payload={"data": {"answer": "Race"}, "request_id": key})
                    except CaptureError as error:
                        return error.error_code
                    except OperationalError:
                        connections.close_all()
                        time.sleep(.01)
                return "lock_timeout"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, keys))
        return results

    def test_last_place_competition_does_not_overrun_sqlite_quota(self):
        results = self.race(["one", "two"])
        self.assertEqual(FormSubmission.objects.count(), 1)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn("response_limit_reached", results)

    def test_simultaneous_retry_commits_one_response_and_one_history_entry(self):
        results = self.race(["same", "same"])
        self.assertTrue(all(isinstance(result, dict) for result in results), results)
        self.assertEqual(FormSubmission.objects.count(), 1)
        self.assertEqual(SubmissionRevision.objects.count(), 1)
        self.assertEqual(CaptureReceipt.objects.count(), 1)
        self.assertEqual(sorted(result["replayed"] for result in results), [False, True])

    def test_survey_hundred_response_limit_has_no_order_side_effects(self):
        self.form.response_limit = 100
        self.form.save()
        for index in range(100):
            capture_submission(form_id=self.form.pk, user=AnonymousUser(), owner_hash="surveyor", payload={"data": {"answer": str(index)}, "request_id": str(index)})
        with self.assertRaises(CaptureError):
            capture_submission(form_id=self.form.pk, user=AnonymousUser(), owner_hash="surveyor", payload={"data": {"answer": "101"}})
        self.assertEqual(self.form.submissions.count(), 100)
        self.assertFalse(ItemSelection.objects.exists())


class CollectionRevisionMigrationTests(TransactionTestCase):
    def test_existing_definitions_and_answers_are_retained_as_explicit_baselines(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate([("forms", "0001_initial")])
        try:
            old = executor.loader.project_state([("forms", "0001_initial")]).apps
            org = old.get_model("organizations", "Organization").objects.create(name="Legacy", slug="legacy")
            form = old.get_model("forms", "DynamicForm").objects.create(organization_id=org.pk, title="Legacy survey", slug="survey", schema=SCHEMA)
            submission = old.get_model("forms", "FormSubmission").objects.create(form_id=form.pk, organization_id=org.pk, data={"answer": "Retain exactly"})
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            saved = FormSubmission.objects.get(pk=submission.pk)
            self.assertTrue(saved.collection_revision.is_legacy_baseline)
            self.assertEqual(saved.collection_revision.schema, SCHEMA)
            self.assertEqual(saved.revisions.get().data, {"answer": "Retain exactly"})
            self.assertEqual(saved.revisions.get().event, "legacy_baseline")
        finally:
            MigrationExecutor(connection).migrate(latest)
