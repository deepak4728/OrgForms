from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def migrate_groups(apps, schema_editor):
    Group = apps.get_model('organizations', 'OrganizationGroup')
    Department = apps.get_model('organizations', 'Department')
    Membership = apps.get_model('organizations', 'OrganizationMembership')
    Assignment = apps.get_model('organizations', 'StaffAssignment')
    db = schema_editor.connection.alias
    for group in Group.objects.using(db).all().iterator():
        base = group.name.strip() or group.alias or 'Team'
        candidate = base[:100]
        suffix = 2
        while Department.objects.using(db).filter(organization_id=group.organization_id, name__iexact=candidate).exists():
            ending = f' ({suffix})'
            candidate = base[:100-len(ending)] + ending
            suffix += 1
        department = Department.objects.using(db).create(organization_id=group.organization_id, name=candidate)
        user_ids = group.members.using(db).values_list('pk', flat=True)
        memberships = Membership.objects.using(db).filter(organization_id=group.organization_id, user_id__in=user_ids)
        for member in memberships.iterator():
            Assignment.objects.using(db).create(department_id=department.pk, membership_id=member.pk)
        for form in group.forms.using(db).filter(organization_id=group.organization_id).iterator():
            form.allowed_departments.add(department)


def reverse_empty_only(apps, schema_editor):
    # Reconstructing old aliases and grants from departments could broaden or
    # silently lose access. Permit rollback only when there is no team data.
    if apps.get_model('organizations', 'Department').objects.using(schema_editor.connection.alias).exists():
        raise IrreversibleError('Cannot reverse the department migration while departments exist; restore a database backup instead.')


class Migration(migrations.Migration):
    dependencies = [('forms', '0004_collectionrevision_destination_schema_and_more'), ('organizations', '0003_departmentstewardship')]
    operations = [
        migrations.AddField(model_name='dynamicform', name='allowed_departments', field=models.ManyToManyField(blank=True, related_name='accessible_forms', to='organizations.department')),
        migrations.RunPython(migrate_groups, reverse_empty_only),
        migrations.RemoveField(model_name='dynamicform', name='allowed_groups'),
    ]
