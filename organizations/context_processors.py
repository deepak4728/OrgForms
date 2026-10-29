from .models import OrganizationMembership
from accounts.models import AccountSpace


def organization_navigation(request):
    if not getattr(request.user, "is_authenticated", False):
        return {"navigation_organizations": [], "active_navigation_organization": None}
    account = AccountSpace.objects.filter(user=request.user).first()
    account_kind = account.kind if account else "legacy"
    memberships = list(
        OrganizationMembership.objects.filter(user=request.user, organization__is_archived=False)
        .select_related("organization")
        .order_by("organization__name")
    )
    organizations = [
        membership.organization for membership in memberships
        if not (membership.organization.name == "My Business" and membership.organization.slug == "my-business" and membership.organization.created_by_id is None)
    ]
    is_dashboard = getattr(getattr(request, "resolver_match", None), "url_name", None) == "dashboard"
    personal_space = account_kind == AccountSpace.PERSONAL or (not account and is_dashboard and request.GET.get("space") == "personal")
    personal_tab = ("submissions" if request.GET.get("tab") == "submissions" else "forms") if personal_space else ""
    selected_slug = (
        getattr(getattr(request, "resolver_match", None), "kwargs", {}).get("org_slug")
        or request.GET.get("org")
        or request.session.get("active_organization_slug")
    )
    active = None if personal_space else next((organization for organization in organizations if organization.slug == selected_slug), None)
    if active is None and organizations and not personal_space and (not is_dashboard or len(organizations) == 1):
        active = organizations[0]
    workspace_organization = active or next(
        (organization for organization in organizations if organization.slug == selected_slug),
        organizations[0] if organizations else None,
    )
    entry_organization = next((organization for organization in organizations if organization.slug == selected_slug), None)
    if entry_organization is None and len(organizations) == 1:
        entry_organization = organizations[0]
    active_membership = next((membership for membership in memberships if active and membership.organization_id == active.pk), None)
    return {
        "navigation_organizations": organizations,
        "active_navigation_organization": active,
        "workspace_entry_organization": entry_organization,
        "workspace_navigation_organization": workspace_organization,
        "active_navigation_role": active_membership.role if active_membership else "",
        "personal_space": personal_space,
        "personal_tab": personal_tab,
        "account_kind": account_kind,
    }
