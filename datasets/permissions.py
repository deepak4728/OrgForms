from django.core.exceptions import PermissionDenied
from django.db.models import Q
from organizations.permissions import require_membership
from .models import Dataset


def dataset_permissions(user, dataset):
    membership = require_membership(user, dataset.organization)
    if membership.role in {"admin", "manager"}:
        return {"read": True, "write": True, "lookup": True, "manage": True}
    grant = dataset.grants.filter(membership=membership).first()
    return {"read": bool(grant and grant.can_read), "write": bool(grant and grant.can_write),
            "lookup": bool(grant and grant.can_lookup), "manage": False}


def require_dataset(user, dataset, action):
    if not dataset_permissions(user, dataset).get(action, False):
        raise PermissionDenied(f"Dataset {action} permission is required.")


def visible_datasets(user, organization):
    membership = require_membership(user, organization)
    datasets = Dataset.objects.filter(organization=organization)
    if membership.role not in {"admin", "manager"}:
        datasets = datasets.filter(Q(grants__membership=membership) & (Q(grants__can_read=True) | Q(grants__can_write=True) | Q(grants__can_lookup=True)))
    return datasets.distinct()
