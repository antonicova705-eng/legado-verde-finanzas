"""Modelo de ventas: configuración, presentaciones, migración y cálculos.

Reglas documentadas
-------------------
* ``Cantidad`` conserva su significado original: **sobres equivalentes vendidos**.
  ``Presentaciones`` es el número de unidades vendidas tal como se venden
  (sobres individuales o paquetes) y ``Sobres por presentación`` las convierte.
* ``Precio`` conserva su significado original: precio por **sobre** antes de
  descuentos (``Precio presentación`` / ``Sobres por presentación``), de modo que
  ``Ventas Producto = Presentaciones × Precio presentación`` ≈ ``Cantidad × Precio``.
* ``Devolución`` es dinero devuelto al cliente. ``Sobres devueltos`` son unidades.
  Sobres netos vendidos = ``Cantidad`` − ``Sobres devueltos``. El costo de ventas
  se captura neto (sin el costo de lo que regresó a inventario).
* Un dato desconocido se guarda como ``None`` o con su bandera de pendiente;
  nunca se interpreta como cero confirmado.
"""
from __future__ import annotations

import copy
from datetime import date

from . import ESQUEMA
from .util import MESES, ahora_iso, numero

CANALES_BASE = [
    {"Nombre": "Mercado Libre", "Activo": True, "Tipo": "Marketplace"},
    {"Nombre": "Amazon", "Activo": True, "Tipo": "Marketplace"},
    {"Nombre": "Cafeterías", "Activo": True, "Tipo": "Directo"},
    {"Nombre": "Venta directa", "Activo": True, "Tipo": "Directo"},
    # Shopify queda configurable: activo para capturar, sin asumir ventas.
    {"Nombre": "Shopify", "Activo": True, "Tipo": "Tienda en línea"},
    {"Nombre": "Otros canales", "Activo": True, "Tipo": "Directo"},
]

PRESENTACIONES_BASE = [{"Nombre": "Sobre individual", "Sobres": 1}]

# «Cancelado» no se ofrece: en motor.activo() equivale a anular la venta. Para eso está «Anular».
ESTADOS_ENTREGA = ["Entregado", "En Camino", "Pendiente", "Resumen Global"]
ESTADOS_COBRO = ["Por confirmar", "Pendiente", "Parcial", "Cobrado"]

ORIGEN_MANUAL = "Captura manual"
ORIGEN_HEREDADO = "Heredado sin verificar"
ORIGEN_IMPORTACION = "Importación (Claude/archivo)"
ORIGEN_ML = "Mercado Libre"
ORIGEN_AMZ = "Amazon"

PRODUCTO_BASE = "Guacamole Liofilizado 40g"


# ------------------------------------------------------------------ configuración
def config_completa(datos: dict) -> dict:
    """Devuelve la configuración con valores por omisión, sin modificar ``datos``."""
    cfg = copy.deepcopy(datos.get("config", {}))
    cfg.setdefault("tc_usd", 20.0)
    cfg.setdefault("vol_prod", 1000)
    cfg.setdefault("precio_venta", 60.0)
    cfg.setdefault("canales", copy.deepcopy(CANALES_BASE))
    cfg.setdefault("presentaciones", copy.deepcopy(PRESENTACIONES_BASE))
    cfg.setdefault("skus", {})
    return cfg


def canales(datos: dict, solo_activos: bool = True) -> list[str]:
    cfg = config_completa(datos)
    nombres = [c["Nombre"] for c in cfg["canales"] if c.get("Activo", True) or not solo_activos]
    # Canales usados por registros existentes siempre se muestran.
    for r in datos.get("operaciones", []):
        if r.get("Canal") and r["Canal"] not in nombres:
            nombres.append(r["Canal"])
    return nombres


def tipo_canal(datos: dict, canal: str) -> str:
    for c in config_completa(datos)["canales"]:
        if c["Nombre"] == canal:
            return c.get("Tipo", "Directo")
    return "Directo"


def presentaciones(datos: dict) -> dict[str, int]:
    return {p["Nombre"]: int(p["Sobres"]) for p in config_completa(datos)["presentaciones"]}


def validar_presentaciones(lista: list[dict]) -> list[dict]:
    limpias, vistos = [], set()
    for p in lista:
        nombre = str(p.get("Nombre", "")).strip()
        if not nombre:
            continue
        sobres = p.get("Sobres")
        if sobres is None or int(sobres) < 1:
            raise ValueError(f"La presentación «{nombre}» debe tener al menos 1 sobre.")
        if nombre.casefold() in vistos:
            raise ValueError(f"Presentación repetida: {nombre}")
        vistos.add(nombre.casefold())
        limpias.append({"Nombre": nombre, "Sobres": int(sobres)})
    if not any(p["Nombre"] == "Sobre individual" and p["Sobres"] == 1 for p in limpias):
        raise ValueError("Conserva la presentación «Sobre individual» con 1 sobre.")
    return limpias


# ------------------------------------------------------------------ migración
def migrar_v2(datos: dict) -> bool:
    """Agrega campos nuevos sin alterar IDs ni valores existentes. Idempotente.

    Devuelve True si hubo cambios que deban guardarse.
    """
    cambio = False
    cfg = datos.setdefault("config", {})
    for k, v in (("canales", CANALES_BASE), ("presentaciones", PRESENTACIONES_BASE), ("skus", {})):
        if k not in cfg:
            cfg[k] = copy.deepcopy(v)
            cambio = True
    for k in ("asientos", "historial", "cobertura"):
        if k not in datos:
            datos[k] = []
            cambio = True
    datos.setdefault("apertura_confirmada", False)
    datos.setdefault("fecha_apertura", None)
    for r in datos.get("operaciones", []):
        if r.get("Esquema", 1) >= ESQUEMA:
            continue
        fechada = bool(r.get("Fecha")) and bool(r.get("Fecha confirmada"))
        defaults = {
            "Origen": ORIGEN_MANUAL if fechada else ORIGEN_HEREDADO,
            "Presentación": "Sobre individual",
            "Presentaciones": r.get("Cantidad"),
            "Sobres por presentación": 1,
            "Precio presentación": r.get("Precio"),
            # Si no hubo dinero devuelto, tampoco se registraron unidades devueltas.
            "Sobres devueltos": 0 if not r.get("Devolución") else None,
            "Descuento": r.get("Descuento", 0.0),
            "Devolución": r.get("Devolución", 0.0),
            # Un registro capturado con el formulario anterior tenía comisión y
            # logística explícitas; los heredados no están verificados.
            "Comisiones confirmadas": fechada,
            "Logística confirmada": fechada,
            "SKU": None,
            "Clave": None,
        }
        for k, v in defaults.items():
            if k not in r:
                r[k] = v
        r["Esquema"] = ESQUEMA
        cambio = True
    return cambio


# ------------------------------------------------------------------ cálculos
def importes(r: dict) -> dict:
    """Desglose de una venta. Los valores None significan desconocido."""
    bruta = float(r.get("Ventas Producto") or 0)
    desc = float(r.get("Descuento") or 0)
    dev = float(r.get("Devolución") or 0)
    neta = bruta - desc - dev
    envio = float(r.get("Ingresos Envío") or 0)
    com = float(r.get("Comisiones") or 0)
    log = float(r.get("Costos Logísticos") or 0)
    com_ok = bool(r.get("Comisiones confirmadas", True))
    log_ok = bool(r.get("Logística confirmada", True))
    costo = r.get("Costo de ventas") if r.get("Costo confirmado") else None
    total = neta + envio
    margen = None
    if costo is not None and com_ok and log_ok:
        margen = total - float(costo) - com - log
    sobres = r.get("Cantidad")
    dev_u = r.get("Sobres devueltos")
    return {
        "venta_bruta": bruta,
        "descuento": desc,
        "devolucion": dev,
        "venta_neta_producto": neta,
        "ingreso_envio": envio,
        "ventas_netas_totales": total,
        "comisiones": com if com_ok else None,
        "logistica": log if log_ok else None,
        "costo_ventas": costo,
        "margen_contribucion": margen,
        # Estimación de lo que liquidaría una plataforma; no es un depósito recibido.
        "deposito_estimado": (total - com - log) if (com_ok and log_ok) else None,
        "sobres": sobres,
        "sobres_devueltos": dev_u,
        "sobres_netos": (sobres - dev_u) if (sobres is not None and dev_u is not None) else None,
    }


def pendientes_de_venta(r: dict) -> list[str]:
    p = []
    if not r.get("Fecha"):
        p.append("Fecha")
    if not r.get("Costo confirmado"):
        p.append("Costo de ventas")
    if not r.get("Comisiones confirmadas", True):
        p.append("Comisiones")
    if not r.get("Logística confirmada", True):
        p.append("Logística")
    if r.get("Sobres devueltos") is None:
        p.append("Sobres devueltos")
    if r.get("Liquidación") == "Pendiente":
        p.append("Liquidación de plataforma")
    if r.get("Ajustes"):
        p.append("Ajustes sin clasificar")
    return p


def construir_venta(datos: dict, e: dict, anterior: dict | None = None) -> dict:
    """Construye un registro de venta compatible con el formato existente.

    ``e`` usa nombres simples: fecha, canal, referencia, producto, presentacion,
    presentaciones, precio_presentacion, descuento, devolucion, sobres_devueltos,
    envio, comisiones, comisiones_confirmadas, logistica, logistica_confirmada,
    costo, costo_confirmado, estado, estado_cobro, cliente, sku, notas, clave,
    origen, remanente, ajustes.
    """
    pres = presentaciones(datos)
    nombre_pres = e.get("presentacion") or "Sobre individual"
    if nombre_pres not in pres:
        raise ValueError(f"Presentación no configurada: {nombre_pres}. Agrégala en Configuración.")
    por = pres[nombre_pres]
    n = e.get("presentaciones")
    if n is None or int(n) != float(n) or int(n) < 1:
        raise ValueError("La cantidad de presentaciones debe ser un entero mayor que cero.")
    n = int(n)
    precio_p = numero(e.get("precio_presentacion"))
    if precio_p is None or precio_p < 0:
        raise ValueError("Indica el precio por presentación (puede ser 0 solo si fue una cortesía real).")
    if not e.get("fecha"):
        raise ValueError("La fecha de la venta es obligatoria.")
    canal = e.get("canal")
    if not canal:
        raise ValueError("Indica el canal.")
    bruta = round(n * precio_p, 2)
    desc = numero(e.get("descuento")) or 0.0
    dev = numero(e.get("devolucion")) or 0.0
    if desc < 0 or dev < 0:
        raise ValueError("Descuento y devolución no pueden ser negativos.")
    if desc + dev > bruta + 0.005:
        raise ValueError("Descuentos más devoluciones no pueden superar la venta bruta.")
    sobres = n * por
    dev_u = e.get("sobres_devueltos")
    if "sobres_devueltos" not in e and dev == 0:
        dev_u = 0  # sin dinero devuelto ni dato explícito: no hubo unidades devueltas
    if dev_u is not None:
        dev_u = int(dev_u)
        if dev_u < 0 or dev_u > sobres:
            raise ValueError("Los sobres devueltos deben estar entre 0 y los sobres vendidos.")
    costo = numero(e.get("costo"))
    costo_ok = bool(e.get("costo_confirmado")) and costo is not None
    if costo is not None and costo < 0:
        raise ValueError("El costo de ventas no puede ser negativo.")
    com = numero(e.get("comisiones"))
    log = numero(e.get("logistica"))
    envio = numero(e.get("envio")) or 0.0
    for nombre, v in (("Comisiones", com), ("Logística", log), ("Envío", envio)):
        if v is not None and v < 0:
            raise ValueError(f"{nombre} no puede ser negativo.")
    base = copy.deepcopy(anterior) if anterior else {}
    f = date.fromisoformat(e["fecha"])
    base.update({
        "Fecha": f.isoformat(),
        "Fecha confirmada": True,
        "Mes": f"{MESES[f.month - 1]} {f.year}",
        "Canal": canal,
        "Referencia": (e.get("referencia") or "").strip(),
        "Producto": (e.get("producto") or PRODUCTO_BASE).strip(),
        "SKU": e.get("sku"),
        "Cliente": (e.get("cliente") or None),
        "Presentación": nombre_pres,
        "Presentaciones": n,
        "Sobres por presentación": por,
        "Precio presentación": precio_p,
        "Cantidad": sobres,
        "Precio": round(precio_p / por, 6),
        "Ventas Producto": bruta,
        "Descuento": desc,
        "Devolución": dev,
        "Sobres devueltos": dev_u,
        "Costo de ventas": costo if costo_ok else None,
        "Costo confirmado": costo_ok,
        "Ingresos Envío": envio,
        # Motor espera números: un pendiente se guarda en 0 con su bandera en False.
        "Comisiones": com if com is not None else 0.0,
        "Comisiones confirmadas": com is not None and bool(e.get("comisiones_confirmadas", True)),
        "Costos Logísticos": log if log is not None else 0.0,
        "Logística confirmada": log is not None and bool(e.get("logistica_confirmada", True)),
        "Remanente": numero(e.get("remanente")) if e.get("remanente") is not None else base.get("Remanente", 0.0),
        "Ajustes": numero(e.get("ajustes")) if e.get("ajustes") is not None else base.get("Ajustes", 0.0),
        "Estado": e.get("estado") or base.get("Estado") or "Entregado",
        "Estado cobro": e.get("estado_cobro") or base.get("Estado cobro") or "Por confirmar",
        "Notas": e.get("notas") or base.get("Notas"),
        "Anulada": False,
        "Esquema": ESQUEMA,
        "Modificado": ahora_iso(),
    })
    base.setdefault("Origen", e.get("origen") or ORIGEN_MANUAL)
    base.setdefault("Creado", ahora_iso())
    if e.get("clave") and not base.get("Clave"):
        base["Clave"] = e["clave"]
    return base
