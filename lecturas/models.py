from django.db import models


class Comercial(models.Model):
    nombre = models.CharField(max_length=120, unique=True)

    def __str__(self):
        return self.nombre


class LecturaCuentaKM(models.Model):
    INICIO = "inicio_semana"
    FIN = "fin_semana"

    TIPO_CHOICES = (
        (INICIO, "Inicio de semana"),
        (FIN, "Fin de semana"),
    )

    comercial = models.ForeignKey(Comercial, on_delete=models.CASCADE, related_name="lecturas")
    tipo_lectura = models.CharField(max_length=20, choices=TIPO_CHOICES)
    semana = models.PositiveSmallIntegerField()
    anio = models.PositiveSmallIntegerField()

    kilometros = models.PositiveIntegerField(null=True, blank=True)

    # OJO: solo queremos guardar temporalmente (inicio hasta cierre, luego borrar ambas)
    imagen = models.ImageField(upload_to="lecturas/", null=True, blank=True)

    # flags/incidencias
    fin_fuera_de_plazo = models.BooleanField(default=False)     # cierre subido fuera de viernes
    inicio_no_cuadra = models.BooleanField(default=False)       # lunes != viernes anterior

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-anio", "-semana", "-created_at"]
        indexes = [
            models.Index(fields=["comercial", "anio", "semana", "tipo_lectura"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.comercial.nombre} - {self.get_tipo_lectura_display()} - Semana {self.semana}/{self.anio}"
