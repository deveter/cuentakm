from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.conf import settings
from pathlib import Path


def spa_index(request):
    index_path = Path(settings.BASE_DIR) / "static" / "dist" / "index.html"
    return HttpResponse(index_path.read_text(encoding="utf-8"))


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("lecturas.urls")),
    path("", spa_index),
]

