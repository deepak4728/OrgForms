from django.db import migrations, models
import django.db.models.deletion
from forms.legacy_history import seed_revision_baselines_v1


def backfill(apps, schema_editor):
    seed_revision_baselines_v1(apps, using=schema_editor.connection.alias)


class Migration(migrations.Migration):
    dependencies = [("forms", "0002_capturereceipt_collectionrevision_submissionrevision_and_more")]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="formsubmission", name="collection_revision",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="submissions", to="forms.collectionrevision"),
        ),
    ]
