"""Reglas que convierten partidas de plataformas en ventas del sistema.

Reglas explícitas
-----------------
1. Identidad: plataforma + cuenta + pedido + partida (``Clave``). El ID de la
   venta es determinista, de modo que reintentos y caídas nunca duplican.
   Los eventos usan las entidades de motor.evento («Venta», «Anulación de venta»)
   para que todo cambio invalide la cobertura confirmada, igual que una captura manual.
2. Solo partidas *reconocidas* entran a ``operaciones``. Pendientes y
   canceladas antes de incorporarse se quedan en la base de integraciones.
3. Antes de incorporar una partida nueva se buscan capturas manuales parecidas
   (mismo canal, ±3 días, mismos sobres e importe ±1 MXN). Si hay coincidencia,
   queda en revisión hasta que el usuario elija incorporar, vincular o ignorar.
4. SKU sin mapear o moneda distinta de MXN → revisión (no se adivinan sobres).
5. Campos propiedad de la plataforma: cantidades, precios, descuentos,
   reembolsos, comisiones estimadas (mientras no estén confirmadas), estado. Campos internos que NUNCA se sobrescriben:
   costo de ventas, cliente, notas, folio interno y cobros.
6. Si un campo propiedad de la plataforma fue editado a mano después de la
   última sincronización, la actualización queda en conflicto, salvo que la
   regla de conciliación sea «plataforma prevalece».
7. Si cambian los sobres de una venta con costo confirmado, el costo se
   conserva pero pierde la confirmación hasta revisarlo.
8. Cancelación en plataforma de una venta ya incorporada: se anula con el
   motivo «Cancelada en plataforma» si no tiene cobros; con cobros, revisión.
9. Nunca se crean cobros: un pedido pagado no es un depósito bancario. La
   liquidación queda «Pendiente» hasta conciliarla.
"""
from __future__ import annotations

import copy
import importlib
from datetime import date

from .. import operaciones as op
from ..modelo import construir_venta, config_completa
from ..util import ahora_iso, huella
from .estado import ESTADOS_LOCALES as E

CAMPOS_PLATAFORMA = ["Fecha", "Presentación", "Presentaciones", "Sobres por presentación", "Precio presentación",
                     "Cantidad", "Precio", "Ventas Producto", "Descuento", "Devolución", "Sobres devueltos",
                     "Comisiones", "SKU"]


def _valores_plataforma(r: dict) -> dict:
    return {k: r.get(k) for k in CAMPOS_PLATAFORMA}


def id_venta(p: dict) -> str:
    pref = "MLAPI" if p["plataforma"] == "Mercado Libre" else "AMZAPI"
    return f"{pref}-{p['pedido']}-{huella(p['partida'])[:6]}"


def _entrada(datos: dict, p: dict) -> dict:
    cfg = config_completa(datos)
    pres = cfg["skus"].get(p.get("sku") or "")
    q = p["cantidad"]
    unit = p["precio_unitario"]
    return {
        "fecha": p["fecha_pedido"], "canal": p["plataforma"], "referencia": f"{p['pedido']}/{p['partida']}",
        "producto": p.get("titulo") or None, "sku": p.get("sku"), "presentacion": pres,
        "presentaciones": q, "precio_presentacion": unit,
        "descuento": p.get("descuento_total") or 0.0,
        "devolucion": p.get("reembolsado") or 0.0,
        "sobres_devueltos": p.get("unidades_devueltas") if p.get("unidades_devueltas") is not None else None,
        "envio": p.get("envio_cobrado") or 0.0,
        "comisiones": p.get("comision"), "comisiones_confirmadas": False,  # se confirman al conciliar liquidación
        "logistica": p.get("logistica"), "logistica_confirmada": False,
        "estado": p.get("entrega") or "Pendiente", "estado_cobro": "Pendiente", "origen": p["plataforma"],
    }


def _posibles_duplicados(datos: dict, venta: dict) -> list[str]:
    f = date.fromisoformat(venta["Fecha"])
    out = []
    for r in datos["operaciones"]:
        if r.get("Anulada") or r.get("Origen") in ("Mercado Libre", "Amazon") or r.get("Canal") != venta["Canal"]:
            continue
        if r.get("Fecha"):
            if abs((date.fromisoformat(r["Fecha"]) - f).days) > 3:
                continue
        elif r.get("Origen") != "Heredado sin verificar":
            continue
        if r.get("Fecha") and r.get("Cantidad") == venta["Cantidad"] and \
                abs(float(r.get("Ventas Producto") or 0) - venta["Ventas Producto"]) <= 1:
            out.append(r["ID"])
    return out


def resumenes_heredados(datos: dict, canal: str) -> list[str]:
    """Registros heredados sin fecha del mismo canal: riesgo de doble conteo al fecharlos."""
    return [r["ID"] for r in datos["operaciones"]
            if r.get("Canal") == canal and not r.get("Fecha") and not r.get("Anulada")]


def conciliar(datos: dict, p: dict, decision: dict | None = None) -> tuple[str, str | None, str | None]:
    """Aplica una partida a ``datos``. Devuelve (estado_local, venta_id, mensaje)."""
    m = importlib.import_module("motor")
    cfg = config_completa(datos)
    prioridad = cfg.get("conciliacion", {}).get("prioridad", "manual")
    clave = p["clave"]
    existente = op.por_clave(datos, clave)
    dec = (decision or {}).get("decision")

    if dec == "ignorar":
        return E["IGNORADO"], None, "Ignorado por decisión del usuario."
    if dec == "vincular" and not existente:
        objetivo = op.por_id(datos, decision.get("venta_id") or "")
        if not objetivo or objetivo.get("Anulada"):
            return E["REV_OTRO"], None, "La venta elegida para vincular ya no existe o está anulada."
        antes = copy.deepcopy(objetivo)
        objetivo.update({"Clave": clave, "Origen pedido": p["pedido"], "Origen partida": p["partida"],
                         "Origen cuenta": p["cuenta"], "Origen estado": p["estado_plataforma"],
                         "Vinculada a plataforma": p["plataforma"]})
        objetivo["Origen valores"] = _valores_plataforma(objetivo)
        m.evento(datos, "Venta", antes, objetivo)
        return E["INCORPORADO"], objetivo["ID"], "Vinculada a una captura manual (sin duplicar)."

    if not existente:
        if p["clase"] == "pendiente":
            return E["PENDIENTE"], None, None
        if p["clase"] == "cancelada":
            return E["CANCELADO"], None, "Cancelado antes de reconocerse; no afecta reportes."
        if p["clase"] == "revision":
            return E["REV_OTRO"], None, f"Estado de plataforma no clasificado: {p['estado_plataforma']}."
        if (p.get("moneda") or "MXN") != "MXN":
            return E["REV_MONEDA"], None, f"Moneda {p.get('moneda')}."
        if not cfg["skus"].get(p.get("sku") or ""):
            return E["REV_SKU"], None, f"Asigna una presentación al SKU «{p.get('sku')}» en Configuración."
        if p.get("precio_unitario") is None:
            return E["REV_OTRO"], None, "La plataforma no informó el precio."
        venta = construir_venta(datos, _entrada(datos, p))
        if dec != "incorporar":
            dups = _posibles_duplicados(datos, venta)
            if dups:
                return E["REV_DUP"], None, "Coincide con: " + ", ".join(dups)
        venta.update({"ID": id_venta(p), "Clave": clave, "Origen cuenta": p["cuenta"], "Origen pedido": p["pedido"],
                      "Origen partida": p["partida"], "Origen estado": p["estado_plataforma"],
                      "Origen sincronizado": ahora_iso(), "Liquidación": "Pendiente",
                      "Comisión fuente": p.get("comision_fuente")})
        if p.get("descuento_por_conciliar") or p.get("reembolso_multipartida"):
            venta["Notas"] = "Descuentos o reembolsos por conciliar con la liquidación de la plataforma."
        venta["Origen valores"] = _valores_plataforma(venta)
        m.validar_venta(venta, datos["operaciones"] + [venta])
        datos["operaciones"].append(venta)
        m.evento(datos, "Venta", None, venta)
        return E["INCORPORADO"], venta["ID"], None

    # ------------------------------------------------ actualización de una venta existente
    vid = existente["ID"]
    if existente.get("Anulada"):
        if p["clase"] == "cancelada":
            return E["CANCELADO"], vid, None
        return E["REV_OTRO"], vid, "La venta está anulada en el sistema pero activa en la plataforma."
    if p["clase"] == "cancelada":
        if op.cobrado_neto(datos, vid) > 0.005:
            return E["REV_OTRO"], vid, "Cancelada en plataforma con cobros registrados: registra el reembolso."
        antes = copy.deepcopy(existente)
        existente.update({"Anulada": True, "Estado": "Cancelado", "Motivo anulación": "Cancelada en plataforma",
                          "Origen estado": p["estado_plataforma"], "Modificado": ahora_iso()})
        m.evento(datos, "Anulación de venta", antes, existente)
        return E["CANCELADO"], vid, None
    if p["clase"] != "reconocida":
        return E["REV_OTRO"], vid, f"La plataforma regresó el pedido a «{p['estado_plataforma']}»."
    if not existente.get("Origen valores"):
        # Venta vinculada a una captura manual: la plataforma no reescribe sus importes.
        antes = copy.deepcopy(existente)
        existente["Origen estado"] = p["estado_plataforma"]
        if antes != existente:
            m.evento(datos, "Venta", antes, existente)
        return E["INCORPORADO"], vid, None
    editado = _valores_plataforma(existente) != existente.get("Origen valores")
    if editado and prioridad != "plataforma":
        return E["REV_CONFLICTO"], vid, ("La venta se editó a mano y la plataforma informó cambios. "
                                         "Revisa y decide; no se sobrescribió nada.")
    pres = config_completa(datos)["skus"].get(p.get("sku") or "") or existente["Presentación"]
    nueva = construir_venta(datos, {**_entrada(datos, p), "presentacion": pres}, anterior=existente)
    antes = copy.deepcopy(existente)
    cambios = {k: nueva[k] for k in CAMPOS_PLATAFORMA}
    if cambios["Cantidad"] != existente.get("Cantidad") and existente.get("Costo confirmado"):
        cambios["Costo confirmado"] = False
        cambios["Notas"] = ((existente.get("Notas") or "") + " Revisar costo: cambió la cantidad en plataforma.").strip()
    if existente.get("Comisiones confirmadas") or p.get("comision") is None:
        # Una comisión confirmada a mano (o con la liquidación) no se reemplaza por la estimación de la API.
        cambios.pop("Comisiones")
    existente.update(cambios)
    existente.update({"Estado": nueva["Estado"] if existente.get("Estado") != "Entregado" else "Entregado",
                      "Origen estado": p["estado_plataforma"], "Origen sincronizado": ahora_iso(),
                      "Modificado": ahora_iso()})
    existente["Origen valores"] = _valores_plataforma(existente)
    if antes != existente:
        m.validar_venta(existente, datos["operaciones"])
        m.evento(datos, "Venta", antes, existente)
    return E["INCORPORADO"], vid, None
