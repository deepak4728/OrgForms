from rest_framework.decorators import api_view
from rest_framework.response import Response
from .services import configuration_for_request
from .serializers import AIConfigurationSerializer
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
from urllib.error import HTTPError, URLError
import json
from rest_framework import status
from rest_framework.decorators import authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from organizations.models import Organization, OrganizationMembership
from organizations.permissions import require_membership
from .models import AIConfiguration, LocalModelProfile
from .serializers import LocalModelProfileSerializer
from .ollama import InvalidOllamaResponse, get_ollama_models
from .providers import CloudProviderError, validate_cloud_provider
from .http import _upstream_error_response, _model_provider_error_response, _invalid_ollama_response


@api_view(["GET", "PATCH"])
def configuration(request):
    profile = configuration_for_request(request, manage=request.method != "GET")
    if request.method == "PATCH":
        serializer = AIConfigurationSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
    return Response(AIConfigurationSerializer(profile).data)


@api_view(["GET"])
def health(request):
    profile = configuration_for_request(request)
    if profile.effective_provider == AIConfiguration.PROVIDER_CLOUD:
        try:
            validate_cloud_provider(profile)
        except CloudProviderError as error:
            return _model_provider_error_response(error)
        return Response({"status": "ok", "provider": "cloud"})

    try:
        get_ollama_models()
    except HTTPError as error:
        return _upstream_error_response(error)
    except (URLError, TimeoutError) as error:
        return _upstream_error_response(error)
    except (InvalidOllamaResponse, json.JSONDecodeError, UnicodeDecodeError):
        return _invalid_ollama_response()

    return Response({"status": "ok", "ollama": "available"})


@api_view(["GET"])
def models(request):
    organization_slug = request.query_params.get("org", "").strip()
    if organization_slug:
        organization = get_object_or_404(Organization, slug=organization_slug)
        require_membership(request.user, organization)
        profile = AIConfiguration.for_organization(organization)
    else:
        profile = configuration_for_request(request)
    if profile.effective_provider == AIConfiguration.PROVIDER_CLOUD:
        try:
            validate_cloud_provider(profile)
        except CloudProviderError as error:
            return _model_provider_error_response(error)
        configured_model = profile.default_model or settings.OLLAMA_DEFAULT_MODEL
        cloud_models = [{"name": configured_model}] if configured_model else []
        return Response({"models": cloud_models})

    try:
        available_models = get_ollama_models()
    except HTTPError as error:
        return _upstream_error_response(error)
    except (URLError, TimeoutError) as error:
        return _upstream_error_response(error)
    except (InvalidOllamaResponse, json.JSONDecodeError, UnicodeDecodeError):
        return _invalid_ollama_response()

    available_names = {item.get("name") for item in available_models}
    configured = {profile.name: profile for profile in LocalModelProfile.objects.all()}
    models_data = []
    for item in available_models:
        name = item.get("name")
        saved = configured.get(name)
        details = item.get("details") or {}
        capabilities = set(item.get("capabilities") or [])
        if saved:
            model_options = {
                "context_window": min(saved.context_window, settings.CHAT_MAX_CONTEXT_WINDOW),
                "context_window_limit": min(saved.context_window, settings.CHAT_MAX_CONTEXT_WINDOW),
                "supports_thinking": saved.supports_thinking,
                "think_enabled": saved.think_enabled,
                "supports_vision": saved.supports_vision,
                "input_mode": saved.input_mode,
                "configured": True,
            }
        elif details or capabilities:
            advertised_context = details.get("context_length")
            if isinstance(advertised_context, bool) or not isinstance(advertised_context, int) or advertised_context < 128:
                advertised_context = settings.CHAT_MAX_CONTEXT_WINDOW
            supports_vision = "vision" in capabilities
            model_options = {
                "context_window": min(4096, settings.CHAT_MAX_CONTEXT_WINDOW, advertised_context),
                "context_window_limit": min(settings.CHAT_MAX_CONTEXT_WINDOW, advertised_context),
                "supports_thinking": "thinking" in capabilities,
                "think_enabled": False,
                "supports_vision": supports_vision,
                "input_mode": "multimodal" if supports_vision else "text",
                "configured": False,
            }
        else:
            model_options = {}
        models_data.append({**item, **model_options})
    for saved in configured.values():
        if saved.name not in available_names:
            models_data.append(
                {
                    "name": saved.name,
                    "context_window": min(saved.context_window, settings.CHAT_MAX_CONTEXT_WINDOW),
                "context_window_limit": min(saved.context_window, settings.CHAT_MAX_CONTEXT_WINDOW),
                    "supports_thinking": saved.supports_thinking,
                    "think_enabled": saved.think_enabled,
                    "supports_vision": saved.supports_vision,
                    "input_mode": saved.input_mode,
                    "configured": True,
                    "available": False,
                }
            )
    return Response({"models": models_data, "default_model": profile.default_model or settings.OLLAMA_DEFAULT_MODEL, "context_window_limit": settings.CHAT_MAX_CONTEXT_WINDOW})


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def local_model_profiles(request):
    if request.method != "GET" and not getattr(request.user, "is_superuser", False):
        raise PermissionDenied("An installation administrator is required to change shared model profiles.")
    if request.method == "GET":
        return Response(LocalModelProfileSerializer(LocalModelProfile.objects.all(), many=True).data)
    serializer = LocalModelProfileSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def local_model_profile_detail(request, profile_id):
    if request.method != "GET" and not getattr(request.user, "is_superuser", False):
        raise PermissionDenied("An installation administrator is required to change shared model profiles.")
    profile = get_object_or_404(LocalModelProfile, pk=profile_id)
    if request.method == "DELETE":
        profile.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = LocalModelProfileSerializer(profile, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


def _runtime_access(request, *, control=False):
    import ipaddress
    organization = get_object_or_404(Organization, slug=request.query_params.get('org', ''))
    membership = require_membership(request.user, organization)
    try:
        local = ipaddress.ip_address(request.META.get('REMOTE_ADDR', '')).is_loopback
    except ValueError:
        local = False
    can_control = local and (request.user.is_superuser or membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER))
    if not local:
        raise PermissionDenied('Ollama runtime controls are available only on the server computer.')
    if control and not can_control:
        raise PermissionDenied('An organization admin or manager on this computer is required to control the shared Ollama server.')
    return can_control


@api_view(['GET', 'POST'])
def ollama_server(request):
    from .runtime import RuntimeErrorDetail, server_status, change_server
    can_control = _runtime_access(request, control=request.method == 'POST')
    try:
        if request.method == 'POST':
            action = request.data.get('action') if isinstance(request.data, dict) else None
            result = change_server(action)
        else:
            result = server_status()
        return Response({**result, 'can_control': can_control})
    except RuntimeErrorDetail as error:
        return Response({'detail': str(error)}, status=409)


@api_view(['GET'])
def ollama_processes(request):
    from .runtime import RuntimeErrorDetail, running_models
    _runtime_access(request)
    try:
        return Response(running_models())
    except RuntimeErrorDetail as error:
        return Response({'detail': str(error)}, status=409)
