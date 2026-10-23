"""Reglas de negocio de ventas y KPIs. Sin dependencias de HTTP ni de IA.

Convenciones de tipo de dato devueltas al frontend y al asistente:
- "registrado": suma de ventas guardadas.
- "estimado": usa supuestos del catálogo (costo variable unitario, costos fijos).
"""
from __future__ import annotations

import difflib
import unicodedata
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..eventos import bus
from ..models import CANALES, ORIGENES, Cliente, Parametro, Venta

CENTAVO = Decimal("0.01")
PERIODOS = ("hoy", "ayer", "semana", "mes", "mes_anterior", "anio", "todo")


class ErrorNegocio(ValueError):
    """Error de validación con mensaje apto para mostrarse o decirse en voz."""


def hoy() -> date:
    return datetime.now(settings.zona_horaria).date()


def d(valor) -> Decimal:
    return Decimal(str(valor)).quantize(CENTAVO, ROUND_HALF_UP)


def normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.lower().replace("cafeteria ", "").split())


# ------------------------------------------------------------------ periodos
@dataclass(frozen=True)
class Rango:
    inicio: date | None
    fin: date | None
    etiqueta: str


def rango(periodo: str = "mes", base: date | None = None, inicio: date | None = None, fin: date | None = None) -> Rango:
    base = base or hoy()
    if inicio or fin:
        if inicio and fin and inicio > fin:
            raise ErrorNegocio("La fecha inicial es posterior a la final.")
        return Rango(inicio, fin, f"{inicio or 'inicio'} a {fin or 'hoy'}")
    if periodo == "hoy":
        return Rango(base, base, "hoy")
    if periodo == "ayer":
        a = base - timedelta(days=1)
        return Rango(a, a, "ayer")
    if periodo == "semana":
        return Rango(base - timedelta(days=6), base, "últimos 7 días")
    if periodo == "mes":
        return Rango(base.replace(day=1), base, "este mes")
    if periodo == "mes_anterior":
        fin_ant = base.replace(day=1) - timedelta(days=1)
        return Rango(fin_ant.replace(day=1), fin_ant, "el mes pasado")
    if periodo == "anio":
        return Rango(base.replace(month=1, day=1), base, "este año")
    if periodo == "todo":
        return Rango(None, None, "todo el historial")
    raise ErrorNegocio(f"Periodo no reconocido: {periodo}.")


# ------------------------------------------------------------------ parámetros
def parametro(db: Session, clave: str, defecto: Decimal) -> tuple[Decimal, str]:
    p = db.get(Parametro, clave)
    return (Decimal(p.valor), p.tipo_dato) if p else (defecto, "estimado")


def supuestos(db: Session) -> dict:
    cv, tcv = parametro(db, "costo_variable_unitario", settings.costo_variable_unitario)
    cf, tcf = parametro(db, "costos_fijos_mensuales", settings.costos_fijos_mensuales)
    return {"costo_variable_unitario": cv, "tipo_cv": tcv, "costos_fijos_mensuales": cf, "tipo_cf": tcf}


# ------------------------------------------------------------------ clientes
def buscar_clientes(db: Session, nombre: str, limite: int = 3) -> list[Cliente]:
    clave = normalizar(nombre)
    if not clave:
        return []
    exacto = db.scalar(select(Cliente).where(Cliente.nombre_norm == clave))
    if exacto:
        return [exacto]
    todos = db.scalars(select(Cliente)).all()
    por_norm = {c.nombre_norm: c for c in todos}
    parecidos = difflib.get_close_matches(clave, list(por_norm), n=limite, cutoff=0.75)
    contiene = [c for c in todos if clave in c.nombre_norm and c.nombre_norm not in parecidos]
    return [por_norm[n] for n in parecidos] + contiene[: max(0, limite - len(parecidos))]


def obtener_o_crear_cliente(db: Session, nombre: str, tipo: str = "Cafetería") -> tuple[Cliente, bool]:
    encontrados = buscar_clientes(db, nombre, limite=1)
    if encontrados and normalizar(encontrados[0].nombre) == normalizar(nombre):
        return encontrados[0], False
    nombre_limpio = " ".join(nombre.split())
    if nombre_limpio.lower().startswith("cafetería ") or nombre_limpio.lower().startswith("cafeteria "):
        nombre_limpio = nombre_limpio.split(" ", 1)[1]
    cliente = Cliente(nombre=nombre_limpio, nombre_norm=normalizar(nombre_limpio), tipo=tipo)
    db.add(cliente)
    db.flush()
    return cliente, True


# ------------------------------------------------------------------ escritura
def validar(datos: dict) -> dict:
    canal = datos.get("canal")
    if canal not in CANALES:
        raise ErrorNegocio(f"Canal inválido. Usa uno de: {', '.join(CANALES)}.")
    cantidad = int(datos.get("cantidad") or 0)
    if cantidad <= 0:
        raise ErrorNegocio("La cantidad de sobres debe ser mayor que cero.")
    total = datos.get("total_producto")
    if total is None and datos.get("precio_unitario") is not None:
        total = Decimal(str(datos["precio_unitario"])) * cantidad
    if total is None:
        raise ErrorNegocio("Falta el monto de la venta o el precio por sobre.")
    limpio = {
        "canal": canal, "cantidad": cantidad, "total_producto": d(total),
        "ingreso_envio": d(datos.get("ingreso_envio") or 0), "comision": d(datos.get("comision") or 0),
        "costo_logistico": d(datos.get("costo_logistico") or 0), "otros_cargos": d(datos.get("otros_cargos") or 0),
        "fecha": datos.get("fecha"), "producto": datos.get("producto") or "Guacamole Liofilizado 40g",
        "referencia_externa": (datos.get("referencia_externa") or None),
        "origen": datos.get("origen") or "manual", "notas": datos.get("notas"),
        "pendiente_conciliar": bool(datos.get("pendiente_conciliar", False)),
        "mes_reportado": datos.get("mes_reportado"), "payload": datos.get("payload"),
    }
    for k in ("total_producto", "ingreso_envio", "comision", "costo_logistico", "otros_cargos"):
        if limpio[k] < 0:
            raise ErrorNegocio(f"{k.replace('_', ' ')} no puede ser negativo.")
    if limpio["origen"] not in ORIGENES:
        raise ErrorNegocio("Origen inválido.")
    if isinstance(limpio["fecha"], str):
        limpio["fecha"] = date.fromisoformat(limpio["fecha"])
    if limpio["fecha"] is None and limpio["origen"] != "importacion":
        limpio["fecha"] = hoy()  # solo el histórico importado puede quedar sin fecha exacta
    if limpio["fecha"] and limpio["fecha"] > hoy() + timedelta(days=1):
        raise ErrorNegocio("La fecha de la venta no puede estar en el futuro.")
    return limpio


def registrar_venta(db: Session, datos: dict, cliente_nombre: str | None = None, publicar: bool = True) -> Venta:
    limpio = validar(datos)
    cliente = None
    if cliente_nombre:
        cliente, _ = obtener_o_crear_cliente(db, cliente_nombre)
    venta = Venta(**limpio, cliente_id=cliente.id if cliente else None)
    db.add(venta)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ErrorNegocio("Ya existe una venta con esa referencia en ese canal.") from exc
    db.commit()
    if publicar:
        bus.publicar("venta", serializar(venta, db))
    return venta


def upsert_externa(db: Session, datos: dict) -> tuple[Venta, bool]:
    """Alta o actualización idempotente de ventas de plataformas (por canal + referencia)."""
    limpio = validar(datos)
    existente = db.scalar(select(Venta).where(Venta.canal == limpio["canal"],
                                              Venta.referencia_externa == limpio["referencia_externa"]))
    estado = datos.get("estado", "confirmada")
    if existente:
        for k, v in limpio.items():
            setattr(existente, k, v)
        existente.estado = estado
        db.commit()
        bus.publicar("venta", serializar(existente, db))
        return existente, False
    venta = Venta(**limpio, estado=estado)
    db.add(venta)
    db.commit()
    bus.publicar("venta", serializar(venta, db))
    return venta, True


def anular(db: Session, venta_id: int, motivo: str) -> Venta:
    venta = db.get(Venta, venta_id)
    if not venta:
        raise ErrorNegocio("No encontré esa venta.")
    if venta.estado == "anulada":
        raise ErrorNegocio("La venta ya estaba anulada.")
    venta.estado = "anulada"
    venta.notas = ((venta.notas or "") + f"\nAnulada: {motivo}").strip()
    db.commit()
    bus.publicar("venta", serializar(venta, db))
    return venta


# ------------------------------------------------------------------ lectura
def _consulta(db: Session, r: Rango, canal: str | None):
    q = select(Venta).where(Venta.estado == "confirmada")
    if r.inicio:
        q = q.where(Venta.fecha >= r.inicio)
    if r.fin:
        q = q.where(Venta.fecha <= r.fin)
    if canal:
        q = q.where(Venta.canal == canal)
    return db.scalars(q).all()


def resumen(db: Session, r: Rango, canal: str | None = None) -> dict:
    ventas = _consulta(db, r, canal)
    sup = supuestos(db)
    cv = sup["costo_variable_unitario"]
    por_canal: dict[str, dict] = {}
    for v in ventas:
        c = por_canal.setdefault(v.canal, {"canal": v.canal, "ventas": 0, "sobres": 0, "total_producto": Decimal(0),
                                           "neto": Decimal(0), "costo_producto": Decimal(0), "costo_estimado": False,
                                           "pendientes_conciliar": 0})
        c["ventas"] += 1
        c["sobres"] += v.cantidad
        c["total_producto"] += v.total_producto
        c["neto"] += v.neto
        if v.costo_confirmado and v.costo_producto is not None:
            c["costo_producto"] += v.costo_producto
        else:
            c["costo_producto"] += cv * v.cantidad
            c["costo_estimado"] = True
        c["pendientes_conciliar"] += int(v.pendiente_conciliar)
    filas = []
    for c in sorted(por_canal.values(), key=lambda x: -x["total_producto"]):
        contrib = c["neto"] - c["costo_producto"]
        filas.append({**{k: (d(v) if isinstance(v, Decimal) else v) for k, v in c.items()},
                      "contribucion": d(contrib),
                      "contribucion_por_sobre": d(contrib / c["sobres"]) if c["sobres"] else None,
                      "tipo_contribucion": "estimado" if c["costo_estimado"] else "registrado"})
    total = sum((f["total_producto"] for f in filas), Decimal(0))
    sobres = sum(f["sobres"] for f in filas)
    contribucion = sum((f["contribucion"] for f in filas), Decimal(0))
    sin_fecha = 0
    if r.inicio is None and r.fin is None:
        sin_fecha = sum(1 for v in ventas if v.fecha is None)
    return {
        "periodo": r.etiqueta, "inicio": r.inicio, "fin": r.fin, "canal": canal,
        "ventas_producto": d(total), "sobres": sobres, "num_ventas": sum(f["ventas"] for f in filas),
        "neto_canales": d(sum((f["neto"] for f in filas), Decimal(0))),
        "ticket_promedio": d(total / sum(f["ventas"] for f in filas)) if filas else None,
        "contribucion": d(contribucion),
        "tipo_contribucion": "estimado" if any(f["tipo_contribucion"] == "estimado" for f in filas) else "registrado",
        "por_canal": filas, "ventas_sin_fecha_incluidas": sin_fecha,
        "pendientes_conciliar": sum(f["pendientes_conciliar"] for f in filas),
    }


def punto_equilibrio(db: Session, base: date | None = None) -> dict:
    base = base or hoy()
    r = rango("mes", base)
    res = resumen(db, r)
    sup = supuestos(db)
    cf = sup["costos_fijos_mensuales"]
    dias_mes = monthrange(base.year, base.month)[1]
    contrib_unit = (res["contribucion"] / res["sobres"]) if res["sobres"] else None
    meta_sobres = (cf / contrib_unit) if contrib_unit and contrib_unit > 0 else None
    avance = (res["contribucion"] / cf * 100) if cf > 0 else None
    proyeccion = res["contribucion"] / base.day * dias_mes if base.day else Decimal(0)
    return {
        "mes": base.strftime("%Y-%m"), "costos_fijos": d(cf), "tipo_costos_fijos": sup["tipo_cf"],
        "contribucion_mes": res["contribucion"], "contribucion_por_sobre": d(contrib_unit) if contrib_unit else None,
        "sobres_mes": res["sobres"], "meta_sobres": int(meta_sobres.to_integral_value()) + 1 if meta_sobres else None,
        "avance_pct": d(avance) if avance is not None else None,
        "contribucion_proyectada_mes": d(proyeccion),
        "faltante": d(max(cf - res["contribucion"], Decimal(0))),
        "tipo_dato": "estimado",
        "nota": "Contribución = neto de canal menos costo de producto (confirmado o estimado). No es flujo de efectivo.",
    }


def ultimas(db: Session, limite: int = 10, canal: str | None = None) -> list[dict]:
    q = select(Venta).order_by(Venta.creado_en.desc()).limit(min(limite, 50))
    if canal:
        q = q.where(Venta.canal == canal)
    return [serializar(v, db) for v in db.scalars(q).all()]


def serializar(v: Venta, db: Session | None = None) -> dict:
    nombre = None
    if v.cliente_id and db is not None:
        c = db.get(Cliente, v.cliente_id)
        nombre = c.nombre if c else None
    return {
        "id": v.id, "fecha": v.fecha.isoformat() if v.fecha else None, "mes_reportado": v.mes_reportado,
        "canal": v.canal, "cliente": nombre, "referencia": v.referencia_externa, "cantidad": v.cantidad,
        "total_producto": str(v.total_producto), "neto": str(d(v.neto)), "comision": str(v.comision),
        "costo_logistico": str(v.costo_logistico), "origen": v.origen, "estado": v.estado,
        "costo_confirmado": v.costo_confirmado, "pendiente_conciliar": v.pendiente_conciliar,
        "creado_en": v.creado_en.isoformat() if v.creado_en else None,
    }
