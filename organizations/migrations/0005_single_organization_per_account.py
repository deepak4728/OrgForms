from django.conf import settings
from django.db import migrations, models
from django.db.models import Count


def prepare_accounts(apps, schema_editor):
    Membership = apps.get_model("organizations", "OrganizationMembership")
    AccountSpace = apps.get_model("accounts", "AccountSpace")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    alias = schema_editor.connection.alias
    if Membership.objects.using(alias).values("user_id").annotate(total=Count("pk")).filter(total__gt=1).exists():
        raise RuntimeError("Accounts with multiple organizations must be resolved before this migration. Back up the database first.")
    member_ids = set(Membership.objects.using(alias).values_list("user_id", flat=True))
    for user_id in User.objects.using(alias).values_list("pk", flat=True).iterator():
        AccountSpace.objects.using(alias).get_or_create(
            user_id=user_id, defaults={"kind": "organization_join" if user_id in member_ids else "personal"},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_accountspace"),
        ("organizations", "0004_delete_organizationgroup"),
    ]

    operations = [
        migrations.RunPython(prepare_accounts, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="organizationmembership",
            constraint=models.UniqueConstraint(fields=("user",), name="one_organization_per_account"),
        ),
    ]
