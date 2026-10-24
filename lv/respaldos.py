"""Validación de respaldos JSON antes de restaurarlos."""
from __future__ import annotations

import importlib
import json

CLAVES_OBLIGATORIAS = ["operaciones", "catalogo", "config", "asientos", "historial",
                       "cobertura", "apertura_confirmada"]


def serializar(datos: dict) -> bytes:
    """Respaldo completo. No incluye credenciales: viven en otra base y en secretos."""
    return json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def validar(restaurado: dict, actual: dict | None = None) -> tuple[list[str], dict]:
    """Devuelve (errores, resumen). Sin errores, el respaldo puede restaurarse."""
    m = importlib.import_module("motor")
    errores: list[str] = []
    if not isinstance(restaurado, dict):
        return ["El archivo no contiene un objeto JSON de respaldo."], {}
    for k in CLAVES_OBLIGATORIAS:
        if k not in restaurado:
            errores.append(f"El respaldo no contiene «{k}».")
    if errores:
        return errores, {}
    ops = restaurado["operaciones"]
    ids = [r.get("ID") for r in ops]
    if None in ids:
        errores.append("Hay ventas sin ID.")
    if len(set(ids)) != len(ids):
        errores.append("El respaldo contiene IDs de venta duplicados.")
    claves = [r.get("Clave") for r in ops if r.get("Clave")]
    if len(set(claves)) != len(claves):
        errores.append("El respaldo contiene claves de idempotencia duplicadas.")
    cfg = restaurado["config"]
    try:
        if float(cfg["vol_prod"]) <= 0 or float(cfg["precio_venta"]) <= 0:
            errores.append("Configuración inválida: volumen y precio deben ser positivos.")
        m.costos_catalogo(restaurado["catalogo"], cfg["tc_usd"], cfg["vol_prod"])
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as e:
        errores.append(f"Catálogo o configuración inválidos: {e}")
    for r in ops:
        if r.get("Fecha"):
            try:
                m.validar_venta(r, ops)
            except (ValueError, KeyError, TypeError) as e:
                errores.append(f"Venta {r.get('ID')}: {e}")
    for a in restaurado["asientos"]:
        try:
            m.fila_asiento(a["Fecha"], a["Líneas"])
        except (ValueError, KeyError, TypeError) as e:
            errores.append(f"Asiento {a.get('ID')}: {e}")
    try:
        json.dumps(restaurado, allow_nan=False)
    except ValueError as e:
        errores.append(f"Contiene valores no válidos (NaN/infinito): {e}")
    resumen = {
        "Ventas en respaldo": len(ops),
        "Ventas activas": sum(1 for r in ops if not r.get("Anulada")),
        "Asientos": len(restaurado["asientos"]),
        "Eventos de historial": len(restaurado["historial"]),
    }
    if actual is not None:
        ids_act = {r.get("ID") for r in actual.get("operaciones", [])}
        ids_res = set(ids)
        resumen["Ventas actuales que desaparecerían"] = len(ids_act - ids_res)
        resumen["Ventas nuevas respecto a la base actual"] = len(ids_res - ids_act)
    return errores, resumen
