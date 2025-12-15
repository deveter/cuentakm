import base64
import os
import re
from pathlib import Path

from dotenv import load_dotenv

# ============================================================
# Cargar .env
# ============================================================
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# ============================================================
# Normalización robusta
# ============================================================
def _normalizar_km(texto: str) -> int:
    """
    Acepta respuestas tipo:
      - "235977"
      - "235.977"
      - "235 977 km"
      - "Km: 235,977"
    y devuelve 235977 (int).

    Evita errores típicos como pillar "79.1" (hora/temperatura) en vez del odómetro:
    - Priorizamos candidatos de 4 a 8 dígitos (típico cuentakm)
    - Si hay formato con separadores, unimos grupos (235 + 977 => 235977)
    """

    if not texto:
        raise Exception("Respuesta vacía del modelo.")

    t = texto.strip()

    # 1) Caso ideal: solo dígitos
    if re.fullmatch(r"\d{3,8}", t):
        return int(t)

    # 2) Buscar patrones con separadores: 123.456 / 123 456 / 1,234,567
    # Captura grupos de 1-3 dígitos repetidos con separadores típicos.
    # Ej: "235.977" => ["235", "977"] => "235977"
    sep_pat = re.findall(r"\b\d{1,3}(?:[ \.,]\d{3})+\b", t)
    if sep_pat:
        # Elegimos el más largo (más fiable)
        best = max(sep_pat, key=len)
        digits = re.sub(r"\D", "", best)
        if 3 <= len(digits) <= 8:
            return int(digits)

    # 3) Fallback: quedarnos con el número "más plausible"
    # - cogemos todas las secuencias de dígitos
    # - priorizamos longitudes 4..8
    nums = re.findall(r"\d+", t)
    if not nums:
        raise Exception(f"No se encontraron números en la respuesta: {texto!r}")

    candidates = [n for n in nums if 4 <= len(n) <= 8]
    if candidates:
        # si hay varios, nos quedamos con el más largo; empate => el mayor
        best = max(candidates, key=lambda x: (len(x), int(x)))
        return int(best)

    # 4) Último recurso: si solo hay números cortos, cogemos el mayor (pero es menos fiable)
    best = max(nums, key=lambda x: int(x))
    return int(best)


# ============================================================
# Cliente OpenAI: nuevo SDK si existe, si no, legacy
# ============================================================
def _call_openai_vision(img_b64: str) -> str:
    """
    Devuelve texto del modelo con el km.
    Compatible con openai>=1.0 (OpenAI client) y con legacy openai.ChatCompletion.
    """
    if not OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY no está definido en el .env")

    prompt_system = (
        "Eres un sistema OCR especializado en leer CUENTAKILÓMETROS de coches/motos. "
        "Devuelve SOLO el valor del odómetro como ENTERO (sin puntos, sin comas, sin espacios). "
        "No devuelvas texto adicional."
    )

    prompt_user = (
        "Lee el CUENTAKILÓMETROS (odómetro total) de la imagen y devuelve SOLO el número entero."
    )

    # ---- Intento SDK NUEVO (openai>=1.0) ----
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": prompt_system,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt_user},
                        {"type": "input_image", "image_base64": img_b64},
                    ],
                },
            ],
        )
        return (resp.output_text or "").strip()

    except Exception:
        # ---- Fallback LEGACY (openai<1.0) ----
        import openai
        openai.api_key = OPENAI_API_KEY

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_user},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                        },
                    ],
                },
            ],
            temperature=0,
        )

        return response["choices"][0]["message"]["content"].strip()


# ============================================================
# API pública
# ============================================================
def extraer_km_desde_imagen(ruta_imagen: str) -> int:
    """
    Abre la imagen del cuentakilómetros, la manda a OpenAI y devuelve
    SOLO un int con los km.
    """
    with open(ruta_imagen, "rb") as f:
        img_bytes = f.read()

    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    texto = _call_openai_vision(img_b64)

    km = _normalizar_km(texto)

    # Validación suave (ajusta si quieres):
    # Evita cosas absurdas tipo 0 o 99999999
    if km < 0 or km > 9_999_999:
        raise Exception(f"KM fuera de rango: {km} (texto modelo: {texto!r})")

    return km
