"""Frozen v1 backfill shared by the data migration and legacy importer.

Keep this function compatible with historical models. A baseline records only
the currently available definition; it cannot reconstruct past schema edits.
"""


def snapshot_item_selections_v1(submission):
    return [
        {"id": selection.pk, "field_id": selection.field_id,
         "subtotal": str(selection.subtotal), "discount": str(selection.discount),
         "tax": str(selection.tax), "total": str(selection.total),
         "lines": [{"item_id": line.catalog_item_id, "name": line.name,
                    "quantity": line.quantity, "unit_price": str(line.unit_price),
                    "line_total": str(line.line_total)} for line in selection.items.all()]}
        for selection in submission.item_selections.prefetch_related("items").order_by("pk")
    ]


def seed_revision_baselines_v1(apps, using="default"):
    Form = apps.get_model("forms", "DynamicForm")
    Definition = apps.get_model("forms", "CollectionRevision")
    Submission = apps.get_model("forms", "FormSubmission")
    History = apps.get_model("forms", "SubmissionRevision")
    Attachment = apps.get_model("forms", "SubmissionAttachment")
    for form in Form.objects.using(using).filter(revisions__isnull=True).iterator():
        Definition.objects.using(using).create(
            form_id=form.pk, number=1, title=form.title, description=form.description,
            purpose=form.purpose, schema=form.schema, schema_dialect="orgforms-fields-v1",
            is_legacy_baseline=True, created_by_id=form.created_by_id,
        )
    for submission in Submission.objects.using(using).filter(revisions__isnull=True).iterator():
        if submission.organization_id != Form.objects.using(using).values_list("organization_id", flat=True).get(pk=submission.form_id):
            raise ValueError("Cannot baseline a response whose organization differs from its form. Resolve the inconsistent legacy record before migrating.")
        definition = Definition.objects.using(using).filter(form_id=submission.form_id).order_by("number").first()
        if submission.collection_revision_id is None:
            Submission.objects.using(using).filter(pk=submission.pk).update(collection_revision_id=definition.pk)
        History.objects.using(using).create(
            submission_id=submission.pk, number=submission.version, data=submission.data,
            respondent_name=submission.respondent_name, respondent_email=submission.respondent_email,
            status=submission.status, source="legacy", event="legacy_baseline",
            item_selections=snapshot_item_selections_v1(submission),
            attachments=list(Attachment.objects.using(using).filter(submission_id=submission.pk, is_current=True).values("id", "field_id", "original_name")),
        )
