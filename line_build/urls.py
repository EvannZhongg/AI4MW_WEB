from django.urls import path

from . import views

urlpatterns = [
    path("health", views.line_chart_health, name="line_chart_health"),
    path("extract", views.line_chart_extract, name="line_chart_extract"),
]
