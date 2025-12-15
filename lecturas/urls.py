from django.urls import path
from .views import ComercialesView, LecturasView, EstadoLecturasView

urlpatterns = [
    path("comerciales/", ComercialesView.as_view(), name="comerciales"),
    path("lecturas/", LecturasView.as_view(), name="lecturas"),
    path("lecturas/estado/", EstadoLecturasView.as_view(), name="lecturas_estado"),
]
