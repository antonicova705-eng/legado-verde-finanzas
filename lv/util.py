"""Utilidades comunes: zona horaria, formato, huellas e identificadores."""
from __future__ import annotations

import calendar
import hashlib
import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Mexico_City")

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def ahora_local() -> datetime:
    return datetime.now(ZONA)


def hoy_local() -> date:
    return ahora_local().date()


def ahora_iso() -> str:
    return ahora_local().isoformat(timespec="seconds")


def fecha_local_de_iso(texto: str | None) -> str | None:
    """Convierte una marca ISO 8601 con zona (p. ej. de una API) a fecha local YYYY-MM-DD."""
    if not texto:
        return None
    t = texto.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZONA)
    return dt.astimezone(ZONA).date().isoformat()


def resolver_fecha(texto: str | None, hoy: date | None = None) -> str | None:
    """Resuelve 'hoy', 'ayer' o una fecha ISO. Devuelve None si no se puede (nunca adivina)."""
    if texto is None:
        return None
    hoy = hoy or hoy_local()
    t = str(texto).strip().lower()
    if t in ("hoy", "today"):
        return hoy.isoformat()
    if t in ("ayer", "yesterday"):
        return (hoy - timedelta(days=1)).isoformat()
    try:
        return date.fromisoformat(t).isoformat()
    except ValueError:
        return None


def fin_de_mes(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def moneda(v, sufijo: str = " MXN") -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "No disponible"
    return f"${v:,.2f}{sufijo}"


def numero(v) -> float | None:
    """Convierte a float; '' o None significan desconocido (None), nunca cero."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip().replace("$", "").replace(",", "")
        if v == "":
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"Valor numérico inválido: {v!r}")
    if not math.isfinite(f):
        raise ValueError(f"Valor no finito: {v!r}")
    return f


def huella(obj) -> str:
    """Hash estable de un objeto JSON (para detectar cambios y duplicados)."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()[:24]
