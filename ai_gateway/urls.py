from django.urls import path
from . import views, creation_views
from .views import configuration


app_name = "ai_gateway"
urlpatterns = [
    path("api/creation/models/", creation_views.creation_models, name="creation-models"),
    path("api/creation/organization/", creation_views.organization_draft, name="organization-draft"),
    path("api/creation/library/<slug:org_slug>/<str:kind>/", creation_views.library_draft, name="library-draft"),
    path("api/creation/forms/<slug:org_slug>/", creation_views.form_draft, name="local-form-draft"),
    path("api/ollama/server/", views.ollama_server, name="ollama-server"),
    path("api/ollama/ps/", views.ollama_processes, name="ollama-ps"),
    path("api/health/", views.health, name="health"),
    path("api/models/", views.models, name="models"),
    path("api/local-model-profiles/", views.local_model_profiles, name="local-model-profiles"),
    path("api/local-model-profiles/<int:profile_id>/", views.local_model_profile_detail, name="local-model-profile-detail"),
    path("api/chat/health/", views.health),
    path("api/chat/models/", views.models),
    path("api/chat/local-model-profiles/", views.local_model_profiles),
    path("api/chat/local-model-profiles/<int:profile_id>/", views.local_model_profile_detail),
    path("api/ai/configuration/", configuration, name="configuration"),
]
