import csv
import io
import json
from datetime import timedelta
from pathlib import Path
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
import re
from django.db import transaction, IntegrityError
from django.db.models import Count, Max, Q, Prefetch
from django.db.models.functions import TruncDate
from django.http import FileResponse, Http404, JsonResponse
from django.urls import reverse
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from urllib.parse import urlencode
from organizations.models import Organization, OrganizationDocument, OrganizationMembership, Department, StaffAssignment, DepartmentStewardship
from accounts.models import AccountSpace
from organizations.department_forms import DepartmentForm
from organizations.permissions import require_membership, visible_forms, can_manage_form
from organizations.library import ORGANIZATION_PROFILE_LIBRARY, clean_profile_data
from organizations.ui_context import prepare_organization_settings
from forms.models import DynamicForm, FormSubmission, SubmissionAttachment, Catalog, ItemSelection, SelectionLine
from organizations.serializers import OrganizationSerializer


def membership_error(user, organization=None):
    space = AccountSpace.objects.filter(user=user).first()
    if space and space.kind == AccountSpace.PERSONAL:
        return "This is a personal account. The person needs a separate organization account."
    memberships = OrganizationMembership.objects.filter(user=user)
    if organization is not None:
        memberships = memberships.exclude(organization=organization)
    if memberships.exists():
        return "This account already belongs to another organization. Use a separate account."
    return ""


@login_required
def organization_detail(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    if request.method == "POST":
        if membership.role != OrganizationMembership.ROLE_ADMIN:
            raise PermissionDenied("Only organization admins can manage members.")
        email = request.POST.get("email", "").strip()
        role = request.POST.get("role", OrganizationMembership.ROLE_MEMBER)
        if role not in dict(OrganizationMembership.ROLE_CHOICES):
            role = OrganizationMembership.ROLE_MEMBER
        member = get_user_model().objects.filter(email__iexact=email).first()
        if not member:
            messages.error(request, "That person needs an OrgForms account before you can add them.")
        elif membership_error(member, organization):
            messages.error(request, membership_error(member, organization))
        elif (member.pk == organization.created_by_id or member.pk == request.user.pk) and role != "admin":
            messages.error(request, "Owner and current admin access cannot be removed here.")
        else:
            OrganizationMembership.objects.update_or_create(
                organization=organization, user=member, defaults={"role": role}
            )
            messages.success(request, f"{member.email or member.username} is now an organization {role}.")
        return redirect("organizations:detail", org_slug=organization.slug)
    request.session["active_organization_slug"] = organization.slug
    forms = list((visible_forms(request.user, organization).distinct() | organization.forms.filter(editors=request.user).distinct())
                 .distinct().select_related("created_by").prefetch_related("allowed_users", "editors"))
    today = timezone.localdate()
    week_start = today - timedelta(days=6)
    month_start = today - timedelta(days=29)
    form_ids = [form.pk for form in forms]
    totals = {
        row["form_id"]: row for row in organization.submissions.filter(form_id__in=form_ids)
        .values("form_id").annotate(total=Count("pk"), latest=Max("created_at"))
    }
    recent = organization.submissions.filter(form_id__in=form_ids, created_at__date__gte=month_start)
    month_counts = {row["form_id"]: row["total"] for row in recent.values("form_id").annotate(total=Count("pk"))}
    week_counts_by_day = {
        (row["form_id"], row["day"]): row["total"]
        for row in organization.submissions.filter(form_id__in=form_ids, created_at__date__gte=week_start)
        .annotate(day=TruncDate("created_at")).values("form_id", "day").annotate(total=Count("pk"))
    }
    for form in forms:
        form.can_edit_form = can_manage_form(request.user, form)
        stats = totals.get(form.pk, {})
        form.response_total = stats.get("total", 0)
        form.response_latest = stats.get("latest")
        form.response_30d = month_counts.get(form.pk, 0)
        raw_trend = [week_counts_by_day.get((form.pk, today - timedelta(days=offset)), 0) for offset in reversed(range(7))]
        peak = max(raw_trend, default=0)
        form.response_trend = [{
            "count": count,
            "height": max(5, round(count / peak * 100)) if peak else 5,
            "day": today - timedelta(days=6 - index),
        } for index, count in enumerate(raw_trend)]
        form.allowed_emails = "\n".join(user.email for user in form.allowed_users.all())
        form.allowed_department_ids = {str(pk) for pk in form.allowed_departments.values_list("pk", flat=True)}
        form.editor_user_ids = {user.pk for user in form.editors.all()}
        form.public_url = request.build_absolute_uri(reverse(
            "forms:public-form", kwargs={"org_slug": organization.slug, "form_slug": form.slug}
        ))
    can_transfer_forms = membership.role == OrganizationMembership.ROLE_ADMIN
    can_manage_form_editors = membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER)
    manageable_organizations = Organization.objects.filter(
        memberships__user=request.user, memberships__role=OrganizationMembership.ROLE_ADMIN, is_archived=False
    ).prefetch_related("memberships__user").distinct() if can_transfer_forms else []
    from organizations.ui_context import prepare_organization_settings
    from organizations.library import ORGANIZATION_PROFILE_LIBRARY
    prepare_organization_settings(organization, request.user)
    return render(request, "organizations/organization.html", {
        "organization": organization, "membership": membership, "forms": forms,
        "members": organization.memberships.select_related("user"),
        "can_transfer_forms": can_transfer_forms,
        "can_manage_form_editors": can_manage_form_editors,
        "manageable_organizations": manageable_organizations,
        "organization_departments": organization.departments.all(),
        "profile_library": ORGANIZATION_PROFILE_LIBRARY,
        "organization_types": Organization.TYPE_CHOICES,
    })


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_organizations(request):
    if request.method == "GET":
        orgs = Organization.objects.filter(memberships__user=request.user).distinct()
        return Response(OrganizationSerializer(orgs, many=True, context={"request": request}).data)
    space = AccountSpace.objects.filter(user=request.user).first()
    if (space and space.kind != AccountSpace.ORGANIZATION_CREATE) or OrganizationMembership.objects.filter(user=request.user).exists():
        return Response({"detail": "An account can create only its own organization. Use a separate organization account."}, status=403)
    serializer = OrganizationSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        org = Organization.objects.create(
            name=serializer.validated_data["name"],
            description=serializer.validated_data.get("description", ""),
            purpose=serializer.validated_data.get("purpose", ""),
            business_type=serializer.validated_data.get("business_type", Organization.TYPE_GENERIC),
            created_by=request.user,
        )
        OrganizationMembership.objects.create(organization=org, user=request.user, role=OrganizationMembership.ROLE_ADMIN)
    return Response(OrganizationSerializer(org, context={"request": request}).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_documents(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization, manage=request.method == "POST")
    if request.method == "GET":
        return Response([{"id": d.pk, "title": d.title, "created_at": d.created_at, "download_url": reverse("organizations:api-document-detail", args=(organization.slug, d.pk)), "can_delete": membership.role in ("admin", "manager")} for d in organization.documents.all()])
    if organization.is_archived:
        return Response({"detail": "Restore this organization before uploading documents."}, status=400)
    uploaded = request.FILES.get("file")
    if not uploaded or uploaded.size > 2 * 1024 * 1024:
        return Response({"detail": "Upload a text, Markdown, or CSV file up to 2 MB."}, status=400)
    suffix = Path(uploaded.name).suffix.lower()
    if suffix not in {".txt", ".md", ".csv"}:
        return Response({"detail": "Only .txt, .md, and .csv documents are supported currently."}, status=400)
    try:
        text = uploaded.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return Response({"detail": "The file must use UTF-8 text encoding."}, status=400)
    if suffix == ".csv":
        rows = list(csv.reader(io.StringIO(text)))[:1000]
        text = "\n".join(", ".join(row) for row in rows)
    doc = OrganizationDocument.objects.create(
        organization=organization, title=request.data.get("title") or uploaded.name,
        file=uploaded, extracted_text=text[:200000], uploaded_by=request.user,
    )
    return Response({"id": doc.pk, "title": doc.title}, status=201)


@api_view(["GET", "DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_document_detail(request, org_slug, document_id):
    organization = get_object_or_404(Organization, slug=org_slug)
    require_membership(request.user, organization, manage=request.method == "DELETE")
    document = get_object_or_404(OrganizationDocument, organization=organization, pk=document_id)
    if request.method == "DELETE":
        name = document.file.name
        with transaction.atomic():
            document.delete()
            transaction.on_commit(lambda: default_storage.delete(name) if name else None)
        return Response(status=204)
    try:
        stream = document.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("The document file is unavailable.")
    response = FileResponse(stream, as_attachment=True, filename=Path(document.file.name).name)
    response["Cache-Control"] = "private, no-store"
    return response


def _settings_return(request, organization, tab="details", *, status=None, delete_error=False):
    if request.POST.get("return_to") == "dashboard":
        query = {"manage": organization.slug, "tab": tab}
        if delete_error:
            query["delete_error"] = "1"
        if status:
            query["status"] = status
        return redirect(f"{reverse('organizations:dashboard')}?{urlencode(query)}")
    if request.POST.get("return_to") == "organization":
        query = urlencode({"manage": organization.slug, "tab": tab, **({"delete_error": "1"} if delete_error else {})})
        return redirect(f"{reverse('organizations:detail', kwargs={'org_slug': organization.slug})}?{query}")
    if request.POST.get("return_to") == "people":
        return redirect("organizations:people", org_slug=organization.slug)
    return redirect("organizations:settings", org_slug=organization.slug)


@login_required
def dashboard(request):
    space = AccountSpace.objects.filter(user=request.user).first()
    account_kind = space.kind if space else "legacy"
    personal_space = account_kind == AccountSpace.PERSONAL or (not space and request.GET.get("space") == "personal")
    if space and account_kind != AccountSpace.PERSONAL and request.GET.get("space") == "personal":
        raise PermissionDenied("Personal space requires a separate personal account.")
    memberships = OrganizationMembership.objects.filter(user=request.user).select_related("organization")
    if space and account_kind != AccountSpace.PERSONAL and request.method == "GET":
        membership = memberships.first()
        if membership:
            return redirect("organizations:detail", org_slug=membership.organization.slug)
        if account_kind == AccountSpace.ORGANIZATION_JOIN:
            return render(request, "accounts/awaiting_organization.html")
    personal_tab = "submissions" if request.GET.get("tab") == "submissions" else "forms"
    initial_form = None
    initial_form_error = None
    creation_member_error = None
    if request.method == "POST" and not personal_space:
        if (space and account_kind != AccountSpace.ORGANIZATION_CREATE) or memberships.exists():
            raise PermissionDenied("Use a separate organization account to create another organization.")
        raw_initial = request.POST.get("initial_form", "")
        if raw_initial:
            try:
                if len(raw_initial)>32000:
                    raise ValueError()
                from ai_gateway.creation import clean_form_draft
                initial_form = clean_form_draft(json.loads(raw_initial))
            except (ValueError,TypeError,ValidationError):
                initial_form_error = "The initial form draft is invalid. Review or discard it before creating the organization."
        name = request.POST.get("name", "").strip()
        member_emails = [email for email in re.split(r"[,\s;]+", request.POST.get("member_emails", "").strip()) if email]
        member_role = request.POST.get("member_role", "member")
        members = []
        if len(member_emails) > 20:
            creation_member_error = "Add up to 20 members at a time."
        elif member_role not in dict(OrganizationMembership.ROLE_CHOICES):
            creation_member_error = "Choose a valid member role."
        else:
            seen_members = set()
            for email in member_emails:
                try:
                    validate_email(email)
                except ValidationError:
                    creation_member_error = f"Enter a valid email address: {email[:100]}."
                    break
                user = get_user_model().objects.filter(email__iexact=email).first()
                if not user:
                    creation_member_error = f"{email[:100]} does not have an OrgForms account yet."
                    break
                if user.pk != request.user.pk and membership_error(user):
                    creation_member_error = f"{email[:100]}: {membership_error(user)}"
                    break
                if user.pk != request.user.pk and user.pk not in seen_members:
                    members.append(user)
                    seen_members.add(user.pk)
        if initial_form_error:
            messages.error(request, initial_form_error)
        elif not name:
            messages.error(request, "Enter an organization name.")
        elif creation_member_error:
            messages.error(request, creation_member_error)
        else:
            business_type = request.POST.get("business_type", Organization.TYPE_GENERIC)
            if business_type not in dict(Organization.TYPE_CHOICES):
                business_type = Organization.TYPE_GENERIC
            with transaction.atomic():
                organization = Organization.objects.create(
                    name=name[:200],
                    description=request.POST.get("description", "").strip(),
                    purpose=request.POST.get("purpose", "").strip()[:80],
                    business_type=business_type,
                    profile_data=clean_profile_data(request.POST.get("profile_data", "{}"), business_type),
                    created_by=request.user,
                )
                OrganizationMembership.objects.create(
                    organization=organization,
                    user=request.user,
                    role=OrganizationMembership.ROLE_ADMIN,
                )
                for member in members:
                    OrganizationMembership.objects.create(organization=organization, user=member, role=member_role)
                if initial_form:
                    DynamicForm.objects.create(organization=organization, created_by=request.user,
                        title=initial_form["title"], description=initial_form["description"], purpose=initial_form["purpose"],
                        schema={"fields":initial_form["fields"]},status=DynamicForm.STATUS_DRAFT,visibility=DynamicForm.VISIBILITY_ORGANIZATION)
            return redirect("organizations:detail", org_slug=organization.slug)

    shared_forms = request.user.shared_orgforms.filter(
        visibility="restricted", status="active", organization__is_archived=False
    ).select_related("organization").distinct()
    if personal_space:
        personal_form_query = request.GET.get("q", "").strip()[:100]
        personal_form_category = request.GET.get("category", "all")
        valid_categories = {value for value, _label in Organization.TYPE_CHOICES}
        if personal_form_category not in valid_categories:
            personal_form_category = "all"
        public_forms = DynamicForm.objects.filter(
            status=DynamicForm.STATUS_ACTIVE,
            visibility=DynamicForm.VISIBILITY_PUBLIC,
            organization__is_archived=False,
        ).select_related("organization")
        if personal_form_category != "all":
            shared_forms = shared_forms.filter(organization__business_type=personal_form_category)
            public_forms = public_forms.filter(organization__business_type=personal_form_category)
        if personal_form_query:
            text_filter = (
                Q(title__icontains=personal_form_query)
                | Q(description__icontains=personal_form_query)
                | Q(purpose__icontains=personal_form_query)
                | Q(organization__name__icontains=personal_form_query)
            )
            shared_forms = shared_forms.filter(text_filter)
            public_forms = public_forms.filter(text_filter)
        shared_forms = shared_forms.order_by("organization__name", "title")
        public_forms = public_forms.order_by("organization__name", "title")
        personal_submissions = []
        if personal_tab == "submissions":
            personal_submissions = list(
                FormSubmission.objects.filter(submitted_by=request.user)
                .select_related("form", "organization")
                .order_by("-created_at")[:100]
            )
        return render(request, "organizations/dashboard.html", {
            "personal_space": True,
            "personal_tab": personal_tab,
            "personal_submissions": personal_submissions,
            "shared_forms": shared_forms,
            "public_forms": public_forms,
            "personal_form_query": personal_form_query,
            "personal_form_category": personal_form_category,
            "organization_types": Organization.TYPE_CHOICES,
        })

    showing_archived = request.GET.get("status") == "archived"
    ownership = request.GET.get("ownership", "all")
    if ownership not in {"all", "owned", "shared"}:
        ownership = "all"
    organization_query = Organization.objects.filter(
        memberships__user=request.user,
        is_archived=showing_archived,
    )
    if ownership == "owned":
        organization_query = organization_query.filter(created_by=request.user)
    elif ownership == "shared":
        organization_query = organization_query.exclude(created_by=request.user)
    organizations = list(organization_query.exclude(name="My Business", slug="my-business", created_by__isnull=True).annotate(
        forms_count=Count("forms", distinct=True),
        submissions_count=Count("submissions", distinct=True),
        members_count=Count("memberships", distinct=True),
    ).prefetch_related("memberships__user").distinct())
    for organization in organizations:
        prepare_organization_settings(organization, request.user)
    return render(request, "organizations/dashboard.html", {
        "organizations": organizations,
        "shared_forms": shared_forms,
        "personal_space": False,
        "showing_archived": showing_archived,
        "ownership": ownership,
        "open_create_dialog": request.method == "POST" or bool(request.session.pop("open_organization_setup", False)),
        "creation_has_errors": request.method == "POST",
        "account_kind": account_kind,
        "creation_member_error": creation_member_error,
        "creation_values": request.POST if request.method == "POST" else {},
        "initial_form_value": request.POST.get("initial_form", "")[:32000] if request.method == "POST" else "",
        "profile_library": ORGANIZATION_PROFILE_LIBRARY,
        "organization_types": Organization.TYPE_CHOICES,
        "manage_org_slug": request.GET.get("manage", ""),
        "manage_tab": request.GET.get("tab", "details"),
    })


@login_required
def organization_people(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug, is_archived=False)
    membership = require_membership(request.user, organization)
    bound_department_form = None
    bound_department_id = None
    if request.method == "POST":
        if membership.role != OrganizationMembership.ROLE_ADMIN:
            raise PermissionDenied("Only an organization admin can manage departments.")
        action = request.POST.get("action")
        if action in {"save-department", "archive-department", "restore-department"}:
            department_id = request.POST.get("department_id")
            department = get_object_or_404(Department, organization=organization, pk=department_id) if department_id else None
            if action != "save-department":
                if department is None:
                    raise Http404("Choose a department.")
                department.is_archived = action == "archive-department"
                department.save(update_fields=["is_archived", "updated_at"])
                messages.success(request, "Department archived. Assignments and responsibility are retained." if department.is_archived else "Department restored.")
                return redirect(reverse("organizations:people", kwargs={"org_slug": organization.slug}) + "#departments")
            if department and department.is_archived:
                raise PermissionDenied("Restore this department before editing it.")
            bound_department_form = DepartmentForm(request.POST, instance=department, organization=organization, auto_id="department-bound-%s")
            bound_department_id = department.pk if department else None
            if bound_department_form.is_valid():
                try:
                    with transaction.atomic():
                        department = bound_department_form.save()
                        chosen = list(bound_department_form.cleaned_data["members"])
                        department.staff_assignments.exclude(membership__in=chosen).delete()
                        for member in chosen:
                            StaffAssignment.objects.get_or_create(department=department, membership=member)
                        collections = list(bound_department_form.cleaned_data["collections"])
                        department.stewardships.exclude(collection__in=collections).delete()
                        for collection in collections:
                            DepartmentStewardship.objects.update_or_create(collection=collection, defaults={"department":department})
                    messages.success(request, "Department saved. Restricted forms grant access only when explicitly shared with this department.")
                    return redirect(reverse("organizations:people", kwargs={"org_slug": organization.slug}) + "#departments")
                except IntegrityError:
                    bound_department_form.add_error(None, "A department or membership changed. Review the details and try again.")
    members = list(organization.memberships.select_related("user"))
    departments = list(organization.departments.prefetch_related("staff_assignments__membership__user", Prefetch("stewardships", queryset=DepartmentStewardship.objects.filter(collection__in=visible_forms(request.user, organization)).select_related("collection"), to_attr="visible_stewardships")))
    for member in members:
        member.people_departments = [department for department in departments if not department.is_archived and any(assignment.membership_id == member.pk for assignment in department.staff_assignments.all())]
    for department in departments:
        if membership.role == OrganizationMembership.ROLE_ADMIN:
            department.edit_form = bound_department_form if bound_department_id == department.pk else DepartmentForm(instance=department, organization=organization, auto_id=f"department-{department.pk}-%s")
    role_counts = {role: sum(member.role == role for member in members) for role, _label in OrganizationMembership.ROLE_CHOICES}
    return render(request, "organizations/people.html", {
        "organization": organization,
        "membership": membership,
        "members": members,
        "membership_count": len(members),
        "can_manage_members": membership.role == OrganizationMembership.ROLE_ADMIN,
        "role_counts": role_counts,
        "departments": departments,
        "department_create_form": bound_department_form if bound_department_form and bound_department_id is None else DepartmentForm(organization=organization, auto_id="department-new-%s"),
        "department_form_error": bound_department_form if bound_department_form and bound_department_form.errors else None,
    })


@login_required
def organization_settings(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    is_admin = membership.role == OrganizationMembership.ROLE_ADMIN
    is_owner = organization.created_by_id == request.user.pk
    can_transfer = is_owner or (not organization.created_by_id and is_admin)
    can_archive = is_owner or is_admin
    can_delete = is_owner or request.user.is_superuser or (not organization.created_by_id and is_admin)

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "update-details":
            require_membership(request.user, organization, manage=True)
            json_response = (
                request.headers.get("x-requested-with") == "XMLHttpRequest"
                and request.POST.get("return_to") in {"dashboard", "organization"}
            )
            name = request.POST.get("name", "").strip()
            business_type = request.POST.get("business_type", Organization.TYPE_GENERIC)
            if not name:
                error_message = "Organization name is required."
            elif business_type not in dict(Organization.TYPE_CHOICES):
                error_message = "Choose a valid organization type."
            else:
                organization.name = name[:200]
                organization.description = request.POST.get("description", "").strip()
                organization.purpose = request.POST.get("purpose", "").strip()[:80]
                organization.business_type = business_type
                organization.profile_data = clean_profile_data(request.POST.get("profile_data", "{}"), business_type)
                organization.save(update_fields=("name", "description", "purpose", "business_type", "profile_data", "updated_at"))
                if json_response:
                    return JsonResponse({
                        "ok": True,
                        "message": "Organization details saved.",
                        "organization": {
                            "slug": organization.slug,
                            "name": organization.name,
                            "description": organization.description or "Your organization.",
                            "category": organization.category_display,
                        },
                    })
                messages.success(request, "Organization details saved.")
                return _settings_return(request, organization, "details")
            if json_response:
                return JsonResponse({"ok": False, "message": error_message}, status=400)
            messages.error(request, error_message)
            return _settings_return(request, organization, "details")

        elif action == "add-member":
            if not is_admin:
                raise PermissionDenied("Only an organization admin can add members or assign roles.")
            email = request.POST.get("email", "").strip()
            role = request.POST.get("role", OrganizationMembership.ROLE_MEMBER)
            user = get_user_model().objects.filter(email__iexact=email).first()
            if not user:
                messages.error(request, "That email does not have an OrgForms account yet.")
            elif role not in dict(OrganizationMembership.ROLE_CHOICES):
                messages.error(request, "Choose a valid role.")
            elif OrganizationMembership.objects.filter(organization=organization, user=user).exists():
                messages.info(request, "That person is already a member. Use their role control in People to change access.")
            elif membership_error(user, organization):
                messages.error(request, membership_error(user, organization))
            else:
                OrganizationMembership.objects.create(organization=organization, user=user, role=role)
                messages.success(request, f"{user.email or user.username} was added as {role}.")
            return _settings_return(request, organization, "members")

        elif action == "update-role":
            if not is_admin:
                raise PermissionDenied("Only an organization admin can change member roles.")
            target = get_object_or_404(OrganizationMembership, organization=organization, pk=request.POST.get("membership_id"))
            role = request.POST.get("role", "")
            if role not in dict(OrganizationMembership.ROLE_CHOICES):
                messages.error(request, "Choose a valid role.")
            elif target.user_id == organization.created_by_id:
                messages.error(request, "Transfer ownership before changing the owner’s role.")
            elif target.user_id == request.user.pk and target.role == OrganizationMembership.ROLE_ADMIN and role != OrganizationMembership.ROLE_ADMIN:
                messages.error(request, "You cannot remove your own admin access here.")
            else:
                target.role = role
                target.save(update_fields=("role",))
                messages.success(request, f"Role updated for {target.user.email or target.user.username}.")
            return _settings_return(request, organization, "members")

        elif action == "remove-member":
            if not is_admin:
                raise PermissionDenied("Only an organization admin can remove members.")
            target = get_object_or_404(OrganizationMembership, organization=organization, pk=request.POST.get("membership_id"))
            if target.user_id == organization.created_by_id or target.user_id == request.user.pk:
                messages.error(request, "Transfer ownership first, or ask another admin to remove your membership.")
            else:
                label = target.user.email or target.user.username
                target.delete()
                messages.success(request, f"{label} was removed from this organization.")
            return _settings_return(request, organization, "members")

        elif action == "transfer-ownership":
            if not can_transfer:
                raise PermissionDenied("Only the organization owner can transfer ownership.")
            target = get_object_or_404(
                OrganizationMembership.objects.select_related("user"),
                organization=organization,
                pk=request.POST.get("membership_id"),
            )
            if target.user_id == request.user.pk:
                messages.error(request, "Choose another organization member as the new owner.")
            else:
                with transaction.atomic():
                    old_owner_membership = OrganizationMembership.objects.filter(
                        organization=organization, user_id=organization.created_by_id,
                    ).first()
                    if not old_owner_membership and not organization.created_by_id:
                        old_owner_membership = OrganizationMembership.objects.filter(
                            organization=organization, user=request.user,
                        ).first()
                    if old_owner_membership:
                        old_owner_membership.role = OrganizationMembership.ROLE_MANAGER
                        old_owner_membership.save(update_fields=("role",))
                    target.role = OrganizationMembership.ROLE_ADMIN
                    target.save(update_fields=("role",))
                    organization.created_by = target.user
                    organization.save(update_fields=("created_by", "updated_at"))
                messages.success(request, f"Ownership transferred to {target.user.email or target.user.username}.")
            return _settings_return(request, organization, "ownership")

        elif action in ("archive", "restore"):
            if not can_archive:
                raise PermissionDenied("Only an organization owner or admin can archive it.")
            organization.is_archived = action == "archive"
            organization.save(update_fields=("is_archived", "updated_at"))
            messages.success(request, "Organization archived." if organization.is_archived else "Organization restored.")
            return _settings_return(
                request, organization, "lifecycle",
                status="archived" if organization.is_archived else None,
            )

        elif action == "delete":
            if not can_delete:
                raise PermissionDenied("Only the organization owner can delete it.")
            if request.POST.get("confirm_name", "").strip() != organization.name:
                if request.POST.get("return_to") not in {"dashboard", "organization"}:
                    messages.error(request, "Type the organization name exactly to confirm deletion.")
                return _settings_return(request, organization, "lifecycle", delete_error=True)
            document_names = tuple(
                document.file.name
                for document in organization.documents.all()
                if document.file
            )
            attachment_names = tuple(
                attachment.file.name
                for attachment in SubmissionAttachment.objects.filter(
                    submission__organization=organization
                ).only("file")
                if attachment.file
            )
            private_file_names = tuple(dict.fromkeys((*document_names, *attachment_names)))
            with transaction.atomic():
                # Remove protected order references and form submissions before
                # cascading the organization-owned records.
                FormSubmission.objects.filter(organization=organization).delete()
                from forms.models import DynamicForm
                from datasets.models import Record
                DynamicForm.objects.filter(organization=organization).delete()
                Record.objects.filter(dataset__organization=organization).delete()
                from forms.models import Catalog, SelectionLine, ItemSelection
                business_ids = list(Catalog.objects.filter(organization=organization).values_list("pk", flat=True))
                order_ids = ItemSelection.objects.filter(catalog_id__in=business_ids).values_list("pk", flat=True)
                SelectionLine.objects.filter(selection_id__in=order_ids).delete()
                ItemSelection.objects.filter(catalog_id__in=business_ids).delete()
                organization.delete()
                transaction.on_commit(
                    lambda file_names=private_file_names: [default_storage.delete(name) for name in file_names],
                    robust=True,
                )
            messages.success(request, "Organization and its data were deleted.")
            request.session.pop("open_organization_setup", None)
            return redirect("organizations:dashboard")

        else:
            messages.error(request, "Choose a valid organization action.")
            return _settings_return(request, organization)

    return render(request, "organizations/settings.html", {
        "organization": organization,
        "membership": membership,
        "members": organization.memberships.select_related("user"),
        "membership_count": organization.memberships.count(),
        "forms_count": visible_forms(request.user, organization).count(),
        "submissions_count": organization.submissions.filter(form__in=visible_forms(request.user, organization)).count(),
        "can_edit_details": membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER),
        "can_manage_members": is_admin,
        "can_transfer": can_transfer,
        "can_archive": can_archive,
        "can_delete": can_delete,
        "transfer_targets": organization.memberships.select_related("user").exclude(user=request.user),
        "profile_library": ORGANIZATION_PROFILE_LIBRARY,
        "organization_types": Organization.TYPE_CHOICES,
        "profile_data_json": json.dumps(organization.profile_data or {}),
    })


def home(request):
    """Show the public product homepage to visitors and signed-in members."""
    return render(request, "home.html")


def access_denied(request, exception=None):
    response = render(request, "access_denied.html", status=403)
    response["Cache-Control"] = "private, no-store"
    return response
