from django.urls import path
from . import views

app_name = "datasets"
urlpatterns = [
    path("org/<slug:org_slug>/library/", views.library, name="library"),
    path("org/<slug:org_slug>/data/", views.dataset_list, name="list"),
    path("org/<slug:org_slug>/data/new/", views.dataset_editor, name="new"),
    path("org/<slug:org_slug>/data/<uuid:dataset_id>/", views.dataset_detail, name="detail"),
    path("org/<slug:org_slug>/data/<uuid:dataset_id>/edit/", views.dataset_editor, name="edit"),
    path("org/<slug:org_slug>/data/<uuid:dataset_id>/records/new/", views.record_editor, name="record-new"),
    path("org/<slug:org_slug>/data/<uuid:dataset_id>/records/<uuid:record_id>/", views.record_detail, name="record"),
    path("org/<slug:org_slug>/data/<uuid:dataset_id>/records/<uuid:record_id>/edit/", views.record_editor, name="record-edit"),
    path("api/orgs/<slug:org_slug>/datasets/", views.api_datasets, name="api-list"),
    path("api/datasets/<uuid:dataset_id>/", views.api_dataset, name="api-detail"),
    path("api/datasets/<uuid:dataset_id>/records/", views.api_records, name="api-records"),
    path("api/datasets/<uuid:dataset_id>/records/<uuid:record_id>/", views.api_record, name="api-record"),
    path("api/datasets/<uuid:dataset_id>/records/<uuid:record_id>/history/", views.api_record_history, name="api-history"),
    path("api/datasets/<uuid:dataset_id>/schemas/", views.api_schema_history, name="api-schemas"),
    path("api/datasets/<uuid:dataset_id>/lookup/", views.api_lookup, name="api-lookup"),
    path("api/datasets/<uuid:dataset_id>/grants/", views.api_grants, name="api-grants"),
]
