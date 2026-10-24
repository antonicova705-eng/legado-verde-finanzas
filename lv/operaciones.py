"""Operaciones de negocio sobre ``datos``: ventas, cobros, anulaciones.

Todas las funciones modifican el diccionario recibido en memoria. La
persistencia atómica la da ``persistencia.Repositorio.transaccion``: una venta
y su cobro se guardan en la misma escritura, o no se guarda ninguno.

Idempotencia
------------
Cada alta puede traer una ``clave`` (la genera el formulario, el importador o
el sincronizador). Si ya existe un registro con esa clave, la operación no crea
nada y devuelve el registro existente. Así un doble clic, un reintento o una
importación repetida no duplican ventas ni cobros.
"""
from __future__ import annotations

import copy
import importlib
from uuid import uuid4

from .modelo import construir_venta, importes, tipo_canal
from .util import ahora_iso, huella, numero


def _motor():
    try:
        return importlib.import_module("motor")
    except ModuleNotFoundError as e:  # pragma: no cover - mensaje para el despliegue
        raise RuntimeError("Falta motor.py junto a app.py; es necesario para ventas y contabilidad.") from e


class Duplicado(Exception):
    """La operación ya se había registrado (misma clave)."""

    def __init__(self, registro: dict, mensaje: str):
        super().__init__(mensaje)
        self.registro = registro


def huella_registro(r: dict | None) -> str | None:
    if r is None:
        return None
    sin_meta = {k: v for k, v in r.items() if k not in ("Modificado",)}
    return huella(sin_meta)


def por_clave(datos: dict, clave: str | None) -> dict | None:
    if not clave:
        return None
    for r in datos.get("operaciones", []):
        if r.get("Clave") == clave:
            return r
    return None


def asiento_por_clave(datos: dict, clave: str | None) -> dict | None:
    if not clave:
        return None
    for a in datos.get("asientos", []):
        if a.get("Clave") == clave:
            return a
    return None


def por_id(datos: dict, vid: str) -> dict | None:
    return next((r for r in datos.get("operaciones", []) if r.get("ID") == vid), None)


def cobrado_neto(datos: dict, venta_id: str) -> float:
    """Efectivo neto cobrado de una venta (cobros − reembolsos) según asientos activos."""
    total = 0.0
    for a in datos.get("asientos", []):
        if a.get("Anulada") or a.get("Venta ID") != venta_id:
            continue
        for l in a.get("Líneas", []):
            if l.get("Cuenta") == "Efectivo":
                total += float(l.get("Debe") or 0) - float(l.get("Haber") or 0)
    return round(total, 2)


def _actualizar_estado_cobro(datos: dict, venta: dict) -> None:
    total = round(importes(venta)["ventas_netas_totales"], 2)
    c = cobrado_neto(datos, venta["ID"])
    if c <= 0.005:
        nuevo = "Pendiente" if venta.get("Estado cobro") in ("Parcial", "Cobrado") else venta.get("Estado cobro", "Por confirmar")
    elif c + 0.005 >= total:
        nuevo = "Cobrado"
    else:
        nuevo = "Parcial"
    venta["Estado cobro"] = nuevo


# ------------------------------------------------------------------ cobros
def registrar_cobro(datos: dict, venta_id: str, fecha: str, importe, medio: str | None = None,
                    referencia: str | None = None, clave: str | None = None,
                    tipo: str = "Cobro de venta") -> dict:
    """Crea el asiento de cobro (o reembolso) vinculado a una venta.

    * Fecha e importe deben ser explícitos.
    * ``referencia`` es la referencia bancaria o recibo; si no se conoce queda
      pendiente y el asiento usa una referencia interna única (no inventa una
      bancaria).
    """
    m = _motor()
    existente = asiento_por_clave(datos, clave)
    if existente:
        raise Duplicado(existente, "Este cobro ya estaba registrado; no se volvió a crear.")
    venta = por_id(datos, venta_id)
    if venta is None or venta.get("Anulada"):
        raise ValueError("La venta vinculada no existe o está anulada.")
    if not venta.get("Fecha"):
        raise ValueError("Primero confirma la fecha de la venta.")
    importe = numero(importe)
    if importe is None or importe <= 0:
        raise ValueError("Indica un importe de cobro mayor que cero.")
    if not fecha:
        raise ValueError("Indica la fecha real del cobro.")
    if fecha < venta["Fecha"]:
        raise ValueError("El cobro no puede ser anterior a la venta; registra anticipos con «Otro asiento».")
    ref_banco = (referencia or "").strip() or None
    if ref_banco and any((a.get("Referencia") or "").casefold() == ref_banco.casefold() for a in datos["asientos"]):
        raise ValueError("Ya existe un asiento con esa referencia, incluso si fue anulado.")
    previos = sum(1 for a in datos["asientos"] if a.get("Venta ID") == venta_id)
    ref_asiento = ref_banco or f"INT-{venta_id[:12]}-{previos + 1}"
    total = round(importes(venta)["ventas_netas_totales"], 2)
    ya = cobrado_neto(datos, venta_id)
    delta = importe if tipo == "Cobro de venta" else -importe
    if delta > 0 and ya + delta > total + 0.005:
        raise ValueError(f"El cobro supera el saldo por cobrar ({total - ya:,.2f} MXN).")
    if delta < 0 and ya + delta < -0.005:
        raise ValueError("El reembolso supera el efectivo cobrado de esta venta.")
    lineas = ([m.cargo("Efectivo", importe), m.abono("Clientes", importe)] if delta > 0
              else [m.cargo("Clientes", importe), m.abono("Efectivo", importe)])
    asiento = m.fila_asiento(fecha, lineas, Tipo=tipo, Flujo="Operación", Referencia=ref_asiento,
                             **{"Venta ID": venta_id, "Clave": clave, "Medio": medio,
                                "Referencia bancaria": ref_banco,
                                "Referencia pendiente": ref_banco is None,
                                "Concepto": f"{tipo} {venta.get('Referencia') or venta_id}"})
    datos["asientos"].append(asiento)
    antes = copy.deepcopy(venta)
    _actualizar_estado_cobro(datos, venta)
    m.evento(datos, "Asiento", None, asiento)
    if antes != venta:
        m.evento(datos, "Venta", antes, venta)
    return asiento


# ------------------------------------------------------------------ ventas
def folio_interno(venta: dict) -> str:
    return f"INT-{venta['Fecha'].replace('-', '')}-{venta['ID'].replace('-', '')[-6:].upper()}"


def registrar_venta(datos: dict, entrada: dict, cobro: dict | None = None) -> tuple[dict, dict | None]:
    """Alta de venta y, opcionalmente, su cobro, en una sola modificación de ``datos``.

    ``cobro``: {"fecha", "importe", "medio", "referencia"}. Si cualquier
    validación falla se lanza la excepción antes de tocar ``datos``.
    """
    m = _motor()
    clave = entrada.get("clave")
    existente = por_clave(datos, clave)
    if existente:
        raise Duplicado(existente, f"La venta ya estaba registrada con ID {existente['ID']}; no se duplicó.")
    trabajo = copy.deepcopy(datos)  # se valida todo sobre una copia
    venta = construir_venta(trabajo, entrada)
    venta["ID"] = entrada.get("id") or str(uuid4())
    if por_id(trabajo, venta["ID"]):
        raise ValueError(f"Ya existe una venta con ID {venta['ID']}.")
    if not venta["Referencia"]:
        # motor.validar_venta exige folio único por canal. Si no se capturó, se genera uno
        # interno identificable (no se inventa una referencia externa).
        venta["Referencia"] = folio_interno(venta)
        venta["Folio interno"] = True
    if venta["Referencia"]:
        for r in trabajo["operaciones"]:
            if (not r.get("Anulada") and r.get("Canal") == venta["Canal"]
                    and (r.get("Referencia") or "").casefold() == venta["Referencia"].casefold()):
                raise ValueError(f"Ya existe una venta activa con el folio {venta['Referencia']} en {venta['Canal']}.")
    m.validar_venta(venta, trabajo["operaciones"])
    trabajo["operaciones"].append(venta)
    m.evento(trabajo, "Venta", None, venta)
    asiento = None
    if cobro:
        asiento = registrar_cobro(trabajo, venta["ID"], cobro.get("fecha"), cobro.get("importe"),
                                  medio=cobro.get("medio"), referencia=cobro.get("referencia"),
                                  clave=(clave + ":cobro") if clave else None)
    datos.clear()
    datos.update(trabajo)
    return por_id(datos, venta["ID"]), asiento


def editar_venta(datos: dict, venta_id: str, entrada: dict, huella_esperada: str | None) -> dict:
    m = _motor()
    anterior = por_id(datos, venta_id)
    if anterior is None:
        raise ValueError("La venta ya no existe.")
    if anterior.get("Anulada"):
        raise ValueError("Una venta anulada queda bloqueada; crea una nueva con otro folio.")
    if huella_esperada and huella_registro(anterior) != huella_esperada:
        raise ValueError("Otra sesión o la sincronización modificó esta venta mientras la editabas. "
                         "Recarga para ver la versión vigente; no se sobrescribió nada.")
    nuevo = construir_venta(datos, entrada, anterior=anterior)
    nuevo["ID"] = venta_id
    if not nuevo["Referencia"]:
        nuevo["Referencia"] = anterior.get("Referencia") or folio_interno(nuevo)
    if nuevo.get("Origen") in ("Mercado Libre", "Amazon"):
        # La sincronización no sobrescribirá campos editados a mano (ver conciliación).
        nuevo["Edición manual"] = ahora_iso()
    otras = [r for r in datos["operaciones"] if r["ID"] != venta_id]
    m.validar_venta(nuevo, otras + [nuevo])
    i = next(i for i, r in enumerate(datos["operaciones"]) if r["ID"] == venta_id)
    datos["operaciones"][i] = nuevo
    m.evento(datos, "Venta", anterior, nuevo)
    total = round(importes(nuevo)["ventas_netas_totales"], 2)
    if cobrado_neto(datos, venta_id) > total + 0.005:
        raise ValueError("El nuevo total queda por debajo de lo ya cobrado. Registra primero un reembolso.")
    _actualizar_estado_cobro(datos, nuevo)
    return nuevo


def anular_venta(datos: dict, venta_id: str, huella_esperada: str | None, motivo: str) -> dict:
    m = _motor()
    anterior = por_id(datos, venta_id)
    if anterior is None or anterior.get("Anulada"):
        raise ValueError("La venta no existe o ya estaba anulada.")
    if huella_esperada and huella_registro(anterior) != huella_esperada:
        raise ValueError("La venta cambió desde que la abriste. Recarga antes de anular.")
    if not (motivo or "").strip():
        raise ValueError("Indica el motivo de la anulación.")
    nuevo = {**anterior, "Anulada": True, "Estado": "Cancelado", "Motivo anulación": motivo.strip(),
             "Modificado": ahora_iso()}
    i = next(i for i, r in enumerate(datos["operaciones"]) if r["ID"] == venta_id)
    datos["operaciones"][i] = nuevo
    m.evento(datos, "Anulación de venta", anterior, nuevo)
    return nuevo


def es_marketplace(datos: dict, r: dict) -> bool:
    return tipo_canal(datos, r.get("Canal", "")) == "Marketplace"
