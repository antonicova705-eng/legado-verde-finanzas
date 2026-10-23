"""Speech-to-text de respaldo con OpenAI (Whisper / gpt-4o-transcribe).

La captura de audio ocurre en el navegador (el servidor no tiene acceso al micrófono del coche).
Ruta principal: Web Speech API en el teléfono (sin costo, baja latencia).
Ruta de respaldo: el navegador graba con MediaRecorder y envía el audio aquí.
"""
from __future__ import annotations

import httpx

from ..config import settings

URL = "https://api.openai.com/v1/audio/transcriptions"
MAX_BYTES = 25 * 1024 * 1024  # límite de la API
TIPOS = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/m4a", "audio/aac"}
# Vocabulario del negocio: mejora el reconocimiento de nombres propios y términos.
VOCABULARIO = ("Legado Verde, guacamole liofilizado, sobres, Mercado Libre, Amazon, cafetería, Shopify, "
               "punto de equilibrio, comisión, contribución, recompra")


class ErrorTranscripcion(RuntimeError):
    pass


def transcribir(audio: bytes, nombre: str, tipo: str, clientes: list[str] | None = None,
                cliente_http: httpx.Client | None = None) -> str:
    if not settings.openai_api_key:
        raise ErrorTranscripcion("Falta OPENAI_API_KEY para la transcripción de respaldo.")
    if not audio:
        raise ErrorTranscripcion("El audio llegó vacío.")
    if len(audio) > MAX_BYTES:
        raise ErrorTranscripcion("El audio excede 25 MB.")
    tipo_base = (tipo or "").split(";")[0].strip().lower()
    if tipo_base not in TIPOS:
        raise ErrorTranscripcion(f"Formato de audio no soportado: {tipo_base or 'desconocido'}.")
    prompt = VOCABULARIO + (", " + ", ".join(clientes[:40]) if clientes else "")
    http = cliente_http or httpx.Client(timeout=30)
    try:
        r = http.post(URL, headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                      files={"file": (nombre or "audio.webm", audio, tipo_base)},
                      data={"model": settings.modelo_stt, "language": "es", "prompt": prompt,
                            "response_format": "json", "temperature": "0"})
    except httpx.HTTPError as e:
        raise ErrorTranscripcion(f"No se pudo contactar el servicio de transcripción: {e}") from e
    finally:
        if cliente_http is None:
            http.close()
    if r.status_code != 200:
        raise ErrorTranscripcion(f"Transcripción rechazada ({r.status_code}): {r.text[:200]}")
    return (r.json().get("text") or "").strip()
