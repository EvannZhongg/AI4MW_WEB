"""
URL configuration for AI4MW_web project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from . import views
from llm_agent import views as llm_views

urlpatterns = [
    path("", views.root_redirect, name="root_redirect"),
    path("admin/", admin.site.urls),
    path("api/chat", llm_views.chat_stream, name="chat_stream"),
    path("api/conversations", llm_views.list_conversations, name="list_conversations"),
    path("api/conversations/<int:conversation_id>", llm_views.list_messages, name="list_messages"),
    path(
        "api/conversations/<int:conversation_id>/rename",
        llm_views.rename_conversation,
        name="rename_conversation",
    ),
    path(
        "api/conversations/<int:conversation_id>/delete",
        llm_views.delete_conversation,
        name="delete_conversation",
    ),
    path("api/session", views.session_info, name="session_info"),
    path("api/logout", views.api_logout, name="api_logout"),
    path("accounts/", include("allauth.urls")),
]
