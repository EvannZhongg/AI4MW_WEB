# evannzhongg/ai4mw_web/AI4MW_Web-b75f2e933ce5eb3d7c9b77393d2d6eec787f7611/pdf_parser/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PDFTaskViewSet

router = DefaultRouter()
# 注册 ViewSet, basename 是必须的，因为我们自定义了 get_queryset
router.register(r'tasks', PDFTaskViewSet, basename='pdftask')

urlpatterns = [
    path('', include(router.urls)),
    # router 会自动生成:
    # /api/pdf_parser/tasks/ (GET, POST)
    # /api/pdf_parser/tasks/<id>/ (GET, DELETE)
]