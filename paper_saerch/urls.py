from django.urls import path

from . import views

urlpatterns = [
    path("health", views.paper_search_health, name="paper_search_health"),
    path("quick", views.paper_search_quick, name="paper_search_quick"),
    path("quick/stream", views.paper_search_quick_stream, name="paper_search_quick_stream"),
    path("deep", views.paper_search_deep, name="paper_search_deep"),
    path("deep/stream", views.paper_search_deep_stream, name="paper_search_deep_stream"),
]
