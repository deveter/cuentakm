import os
import logging
from datetime import datetime, date

from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models import Q
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from django.core.mail import EmailMessage

from .models import Comercial, LecturaCuentaKM  # <-- ajusta si tu modelo se llama distinto
from .services.openai_km import extraer_km_desde_imagen  # <-- tu función de OCR con OpenAI


logger = logging.getLogger(__name__)

class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return


# -------------------------
# Helpers
# -------------------------

def iso_week_year(d: date):
    iso = d.isocalendar()
    return iso.week, iso.year


def is_monday(d: date) -> bool:
    return d.weekday() == 0  # Monday=0


def is_friday(d: date) -> bool:
    return d.weekday() == 4  # Friday=4


def delete_image_field_file(instance, field_name: str):
    """
    Borra físicamente el archivo asociado a un ImageField/FileField
    y deja el campo vacío (sin borrar el registro).
    """
    f = getattr(instance, field_name, None)
    if not f:
        return
    try:
        if f.name and default_storage.exists(f.name):
            default_storage.delete(f.name)
    except Exception:
        logger.exception("Error borrando archivo %s", f.name)
    try:
        setattr(instance, field_name, None)
        instance.save(update_fields=[field_name])
    except Exception:
        logger.exception("Error limpiando campo %s del modelo", field_name)


def enviar_email_admin_fin_semana(comercial, lectura_inicio, lectura_fin, kms_semana, warning=None):
    """
    Envía email a admin con:
    - medición inicio y fin
    - diferencia
    - warning (si aplica)
    - adjunta las 2 fotos (si existen)
    """
    subject = f"[Cuentakm] {comercial.nombre} – Semana {lectura_fin.semana}/{lectura_fin.anio}"
    lines = [
        f"Comercial: {comercial.nombre}",
        f"Semana: {lectura_fin.semana}/{lectura_fin.anio}",
        "",
        f"Inicio de semana: {lectura_inicio.kilometros} km  ({lectura_inicio.created_at})",
        f"Fin de semana:    {lectura_fin.kilometros} km  ({lectura_fin.created_at})",
        "",
        f"Kilómetros realizados: {kms_semana} km",
    ]
    if warning:
        lines += ["", f"AVISO: {warning}"]

    body = "\n".join(lines)

    to_email = ["ppinar@tipsitpv.com"]
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=to_email,
    )

    # Adjuntar fotos
    # IMPORTANTE: EmailMessage.attach_file necesita ruta absoluta en disco, no el "name" relativo.
    # Si usas default_storage local, esto funciona con .path.
    for lectura, label in [(lectura_inicio, "inicio"), (lectura_fin, "fin")]:
        try:
            if lectura.imagen and lectura.imagen.name:
                # Para storage local:
                file_path = lectura.imagen.path
                email.attach_file(file_path)
        except Exception:
            logger.exception("No se pudo adjuntar foto %s", label)

    email.send(fail_silently=False)
    logger.info("[EMAIL] Enviado resumen fin de semana a Administración")


def enviar_email_admin_mismatch_lunes(comercial, lectura_fin_anterior, lectura_inicio_nueva, warning):
    """
    Email específico cuando el lunes (inicio nueva semana) NO cuadra con el fin anterior.
    Adjunta foto fin anterior y foto inicio nueva (si existen).
    """
    subject = f"[Cuentakm][AVISO] Posible uso fin de semana – {comercial.nombre}"
    lines = [
        f"Comercial: {comercial.nombre}",
        "",
        f"Fin semana anterior: {lectura_fin_anterior.kilometros} km  ({lectura_fin_anterior.created_at})",
        f"Inicio semana nueva: {lectura_inicio_nueva.kilometros} km  ({lectura_inicio_nueva.created_at})",
        "",
        f"AVISO: {warning}",
    ]
    body = "\n".join(lines)

    to_email = ["ivallejo@tipsitpv.com"]
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=to_email,
    )

    for lectura, label in [(lectura_fin_anterior, "fin_anterior"), (lectura_inicio_nueva, "inicio_nueva")]:
        try:
            if lectura.imagen and lectura.imagen.name:
                email.attach_file(lectura.imagen.path)
        except Exception:
            logger.exception("No se pudo adjuntar foto %s", label)

    email.send(fail_silently=False)
    logger.info("[EMAIL] Enviado aviso mismatch lunes a Administración")


# -------------------------
# API Views
# -------------------------

class ComercialesView(APIView):
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    def get(self, request):
        qs = Comercial.objects.all().order_by("nombre")
        data = [{"id": c.id, "nombre": c.nombre} for c in qs]
        return Response(data, status=status.HTTP_200_OK)


class EstadoLecturasView(APIView):
    """
    Devuelve qué opciones de lectura se permiten según la regla:
    1) Si NO hay lecturas: solo "inicio_semana"
    2) Si la ÚLTIMA lectura es "inicio_semana": solo "fin_semana"
    3) Si la ÚLTIMA lectura es "fin_semana": solo "inicio_semana"
    Además devolvemos la última lectura y semana/año actual.
    
    """
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    def get(self, request):
        comercial_id = request.query_params.get("comercial_id")
        if not comercial_id:
            return Response({"error": "Falta comercial_id"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            comercial = Comercial.objects.get(id=comercial_id)
        except Comercial.DoesNotExist:
            return Response({"error": "Comercial no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        hoy = timezone.localdate()
        semana_actual, anio_actual = iso_week_year(hoy)

        last = (
            LecturaCuentaKM.objects
            .filter(comercial=comercial)
            .order_by("-created_at")
            .first()
        )

        if not last:
            allowed = ["inicio_semana"]
        else:
            if last.tipo_lectura == "inicio_semana":
                allowed = ["fin_semana"]
            else:
                allowed = ["inicio_semana"]

        last_data = None
        if last:
            last_data = {
                "id": last.id,
                "tipo_lectura": last.tipo_lectura,
                "kilometros": last.kilometros,
                "semana": last.semana,
                "anio": last.anio,
                "created_at": last.created_at,
            }

        return Response(
            {
                "comercial": {"id": comercial.id, "nombre": comercial.nombre},
                "semana_actual": semana_actual,
                "anio_actual": anio_actual,
                "allowed_types": allowed,
                "last": last_data,
            },
            status=status.HTTP_200_OK
        )


class LecturasView(APIView):
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def post(self, request):
        comercial_id = request.data.get("comercial_id")
        tipo_lectura = request.data.get("tipo_lectura")  # el front lo manda, pero lo validamos contra allowed
        imagen = request.FILES.get("imagen")

        if not comercial_id:
            return Response({"error": "Falta comercial_id"}, status=status.HTTP_400_BAD_REQUEST)
        if not imagen:
            return Response({"error": "Falta imagen"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            comercial = Comercial.objects.get(id=comercial_id)
        except Comercial.DoesNotExist:
            return Response({"error": "Comercial no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        hoy = timezone.localdate()
        semana_actual, anio_actual = iso_week_year(hoy)

        last = (
            LecturaCuentaKM.objects
            .filter(comercial=comercial)
            .order_by("-created_at")
            .first()
        )

        # Regla de allowed types (misma que EstadoLecturasView)
        if not last:
            allowed = ["inicio_semana"]
        else:
            allowed = ["fin_semana"] if last.tipo_lectura == "inicio_semana" else ["inicio_semana"]

        if tipo_lectura not in allowed:
            return Response(
                {"error": f"Tipo de lectura no permitido ahora. Permitidos: {allowed}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 1) Guardamos registro (con imagen) para poder adjuntarla luego si hace falta
        lectura = LecturaCuentaKM.objects.create(
            comercial=comercial,
            tipo_lectura=tipo_lectura,
            semana=semana_actual,
            anio=anio_actual,
            imagen=imagen,
        )

        # 2) Extraer km con OpenAI
        try:
            lectura.kilometros = extraer_km_desde_imagen(lectura.imagen.path)
            lectura.save(update_fields=["kilometros"])
        except Exception as e:
            logger.exception("Error leyendo km con OpenAI")
            # si falla, borramos la foto que acabamos de subir para no acumular basura
            delete_image_field_file(lectura, "imagen")
            lectura.delete()
            return Response({"error": f"Error leyendo kilómetros: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        warning = None
        kms_semana = None

        # -------------------------
        # CASO A: inicio_semana
        # -------------------------
        if tipo_lectura == "inicio_semana":
            # Si existe un fin_semana anterior, y esto NO es la primera vez:
            lectura_fin_anterior = (
                LecturaCuentaKM.objects
                .filter(comercial=comercial, tipo_lectura="fin_semana")
                .order_by("-created_at")
                .first()
            )

            # Regla: si hay cierre anterior, el inicio nuevo debería ser IGUAL al fin anterior.
            if lectura_fin_anterior:
                if lectura.kilometros != lectura_fin_anterior.kilometros:
                    warning = (
                        "La lectura del lunes (inicio de semana) no coincide con el fin de semana anterior. "
                        "Se avisará a Administración."
                    )
                    try:
                        enviar_email_admin_mismatch_lunes(
                            comercial=comercial,
                            lectura_fin_anterior=lectura_fin_anterior,
                            lectura_inicio_nueva=lectura,
                            warning=warning
                        )
                    except Exception:
                        logger.exception("[EMAIL] Error enviando aviso mismatch lunes")

            # Nota: NO borramos la foto de inicio, porque la necesitamos para el email del fin de semana.
            return Response(
                {
                    "comercial": comercial.nombre,
                    "tipo_lectura": tipo_lectura,
                    "kilometros": lectura.kilometros,
                    "semana": lectura.semana,
                    "anio": lectura.anio,
                    "kms_semana": kms_semana,
                    "warning": warning,
                },
                status=status.HTTP_201_CREATED,
            )

        # -------------------------
        # CASO B: fin_semana
        # -------------------------
        # Debe existir inicio_semana (para poder calcular)
        lectura_inicio = (
            LecturaCuentaKM.objects
            .filter(
                comercial=comercial,
                tipo_lectura="inicio_semana",
                semana=semana_actual,
                anio=anio_actual,
            )
            .order_by("-created_at")
            .first()
        )

        if not lectura_inicio:
            # no podemos calcular; borramos esta foto (fin) para no acumular
            delete_image_field_file(lectura, "imagen")
            lectura.delete()
            return Response(
                {
                    "error": "No tenemos la lectura de inicio de semana para esta semana. "
                             "No podemos calcular los km."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        kms_semana = lectura.kilometros - lectura_inicio.kilometros
        if kms_semana < 0:
            warning = "Los kilómetros de fin de semana son menores que los de inicio. Revisar posible error de lectura."

        # Warning por “fin fuera de plazo” (si no se hace en viernes)
        if not is_friday(hoy):
            warning_extra = (
                "La lectura de fin de semana se ha subido fuera de plazo (no es viernes). "
                "Se notificará a Administración."
            )
            warning = f"{warning} | {warning_extra}" if warning else warning_extra
            try:
                lectura.fin_fuera_de_plazo = True
                lectura.save(update_fields=["fin_fuera_de_plazo"])
            except Exception:
                pass

        # Email a admin SIEMPRE en fin de semana (como pediste), con las dos fotos
        try:
            enviar_email_admin_fin_semana(
                comercial=comercial,
                lectura_inicio=lectura_inicio,
                lectura_fin=lectura,
                kms_semana=kms_semana,
                warning=warning,
            )
        except Exception:
            logger.exception("[EMAIL] Error enviando email fin de semana")

        # ✅ BORRADO DE FOTOS: tras fin de semana, borramos foto de inicio y foto de fin
        # (así no peta media/)
        try:
            delete_image_field_file(lectura_inicio, "imagen")
            delete_image_field_file(lectura, "imagen")
        except Exception:
            logger.exception("Error borrando fotos tras fin de semana")

        return Response(
            {
                "comercial": comercial.nombre,
                "tipo_lectura": tipo_lectura,
                "kilometros": lectura.kilometros,
                "semana": lectura.semana,
                "anio": lectura.anio,
                "kms_semana": kms_semana,
                "warning": warning,
            },
            status=status.HTTP_201_CREATED,
        )
