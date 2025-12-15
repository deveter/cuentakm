from django.contrib import admin
from .models import Comercial, LecturaCuentaKM


@admin.register(Comercial)
class ComercialAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre")
    search_fields = ("nombre",)


@admin.register(LecturaCuentaKM)
class LecturaCuentaKMAdmin(admin.ModelAdmin):
    list_display = ("comercial", "tipo_lectura", "semana", "anio", "kilometros", "fin_fuera_de_plazo", "inicio_no_cuadra", "created_at")
    list_filter = ("tipo_lectura", "anio", "semana", "fin_fuera_de_plazo", "inicio_no_cuadra")
    search_fields = ("comercial__nombre",)
