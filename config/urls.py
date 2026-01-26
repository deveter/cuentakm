from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse, HttpResponseNotFound
from django.conf import settings
from django.conf.urls.static import static
from pathlib import Path


def spa_index(request):
    """
    Sirve el index.html del frontend (Vue SPA)
    - En DEBUG: desde backend/static/dist/index.html
    - En producción: desde STATIC_ROOT/dist/index.html
    """
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

# -----------------------------
# SERVIR MEDIA SOLO EN DEBUG
# -----------------------------
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
