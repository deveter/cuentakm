from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse, HttpResponseNotFound
from django.conf import settings
from pathlib import Path
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

def spa_index(request):
    if settings.DEBUG:
        index_path = Path(settings.BASE_DIR) / "static" / "dist" / "index.html"
    else:
        index_path = Path(settings.STATIC_ROOT) / "dist" / "index.html"

    if not index_path.exists():
        return HttpResponseNotFound("index.html no encontrado")

    return HttpResponse(index_path.read_text(encoding="utf-8"))

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("lecturas.urls")),
    path("", spa_index),
]

urlpatterns += staticfiles_urlpatterns()
