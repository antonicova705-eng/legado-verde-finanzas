"""Herramientas (tool use) que Claude puede invocar y su ejecución contra la base de datos.

Seguridad de escritura: `preparar_venta` NO escribe; crea una OperacionPendiente.
`confirmar_operacion` solo la aplica si la confirmación llega en un turno POSTERIOR
del usuario (impuesto en código, no en el prompt), dentro de su vigencia.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CANALES, OperacionPendiente, ahora
from ..servicios import ventas as sv

VIGENCIA = timedelta(minutes=5)

HERRAMIENTAS: list[dict[str, Any]] = [
    {
        "name": "consultar_ventas",
        "description": "Totales de ventas, sobres, neto de canal y contribución en un periodo, opcionalmente de un canal. "
                       "Úsala para cualquier pregunta de '¿cómo van las ventas…?'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {"type": "string", "enum": list(sv.PERIODOS), "description": "Periodo relativo a hoy."},
                "canal": {"type": "string", "enum": list(CANALES)},
                "fecha_inicio": {"type": "string", "description": "YYYY-MM-DD; solo para rangos explícitos."},
                "fecha_fin": {"type": "string", "description": "YYYY-MM-DD; solo para rangos explícitos."},
            },
            "required": ["periodo"],
        },
    },
    {
        "name": "punto_de_equilibrio",
        "description": "Avance del mes hacia el punto de equilibrio (estimación con costos del catálogo).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "ultimas_ventas",
        "description": "Lista las ventas más recientes, opcionalmente de un canal.",
        "input_schema": {
            "type": "object",
            "properties": {"limite": {"type": "integer", "minimum": 1, "maximum": 10},
                           "canal": {"type": "string", "enum": list(CANALES)}},
            "required": [],
        },
    },
    {
        "name": "buscar_cliente",
        "description": "Busca clientes por nombre aproximado (tolera errores de dictado).",
        "input_schema": {"type": "object", "properties": {"nombre": {"type": "string"}}, "required": ["nombre"]},
    },
    {
        "name": "preparar_venta",
        "description": "Prepara (sin guardar) el registro de una venta dictada por el usuario y devuelve un resumen "
                       "que DEBES leerle para que confirme. Si dice el total, usa monto_total; si dice precio por "
                       "sobre, usa precio_unitario. Nunca inventes datos faltantes: pregunta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "canal": {"type": "string", "enum": list(CANALES)},
                "cliente": {"type": "string", "description": "Nombre del cliente o negocio, sin la palabra 'cafetería'."},
                "cantidad": {"type": "integer", "minimum": 1, "description": "Número de sobres."},
                "monto_total": {"type": "number", "minimum": 0, "description": "Total en pesos MXN por los sobres."},
                "precio_unitario": {"type": "number", "minimum": 0},
                "fecha": {"type": "string", "description": "YYYY-MM-DD. Omitir si es hoy."},
                "notas": {"type": "string"},
            },
            "required": ["canal", "cantidad"],
        },
    },
    {
        "name": "confirmar_operacion",
        "description": "Aplica una operación pendiente SOLO cuando el usuario la confirmó explícitamente en su último mensaje "
                       "(por ejemplo: 'sí', 'confirmo', 'adelante').",
        "input_schema": {"type": "object", "properties": {"operacion_id": {"type": "string"}}, "required": ["operacion_id"]},
    },
    {
        "name": "cancelar_operacion",
        "description": "Descarta una operación pendiente cuando el usuario no la confirma o pide corregirla.",
        "input_schema": {"type": "object", "properties": {"operacion_id": {"type": "string"}}, "required": ["operacion_id"]},
    },
]


def _pesos(valor: Decimal | None) -> str:
    return "sin dato" if valor is None else f"${valor:,.2f}"


@dataclass
class Contexto:
    db: Session
    sesion_id: str
    turno: int
    acciones: list[dict] = field(default_factory=list)


class Ejecutor:
    def __init__(self, ctx: Contexto):
        self.ctx = ctx

    def ejecutar(self, nombre: str, entrada: dict) -> dict:
        metodo = getattr(self, f"_{nombre}", None)
        if metodo is None:
            return {"error": f"Herramienta desconocida: {nombre}"}
        try:
            return metodo(**entrada)
        except sv.ErrorNegocio as e:
            return {"error": str(e)}
        except (TypeError, ValueError) as e:
            return {"error": f"Datos inválidos: {e}"}

    # ---------------- lectura
    def _consultar_ventas(self, periodo: str = "mes", canal: str | None = None,
                          fecha_inicio: str | None = None, fecha_fin: str | None = None) -> dict:
        r = sv.rango(periodo, inicio=date.fromisoformat(fecha_inicio) if fecha_inicio else None,
                     fin=date.fromisoformat(fecha_fin) if fecha_fin else None)
        res = sv.resumen(self.ctx.db, r, canal)
        return _json(res)

    def _punto_de_equilibrio(self) -> dict:
        return _json(sv.punto_equilibrio(self.ctx.db))

    def _ultimas_ventas(self, limite: int = 5, canal: str | None = None) -> dict:
        return {"ventas": sv.ultimas(self.ctx.db, limite, canal)}

    def _buscar_cliente(self, nombre: str) -> dict:
        return {"coincidencias": [{"id": c.id, "nombre": c.nombre, "tipo": c.tipo}
                                  for c in sv.buscar_clientes(self.ctx.db, nombre)]}

    # ---------------- escritura en dos fases
    def _preparar_venta(self, canal: str, cantidad: int, cliente: str | None = None, monto_total: float | None = None,
                        precio_unitario: float | None = None, fecha: str | None = None, notas: str | None = None) -> dict:
        if monto_total is None and precio_unitario is None:
            raise sv.ErrorNegocio("Falta el monto: pregunta el total o el precio por sobre.")
        datos = {"canal": canal, "cantidad": cantidad, "fecha": fecha or sv.hoy().isoformat(),
                 "total_producto": monto_total, "precio_unitario": precio_unitario,
                 "origen": "voz", "notas": notas}
        limpio = sv.validar(datos)  # valida sin escribir
        cliente_existente, cliente_nuevo = None, False
        if cliente:
            coincidencias = sv.buscar_clientes(self.ctx.db, cliente, limite=1)
            if coincidencias:
                cliente_existente = coincidencias[0].nombre
            else:
                cliente_nuevo = True
        nombre_cliente = cliente_existente or cliente
        # Una sola operación pendiente por sesión: la nueva reemplaza a la anterior.
        for op in self.ctx.db.scalars(select(OperacionPendiente).where(
                OperacionPendiente.sesion_id == self.ctx.sesion_id, OperacionPendiente.estado == "pendiente")):
            op.estado = "cancelada"
        unitario = limpio["total_producto"] / limpio["cantidad"]
        resumen = (f"{limpio['cantidad']} sobres a {nombre_cliente or 'cliente sin nombre'}"
                   f"{' (cliente nuevo)' if cliente_nuevo else ''}, canal {canal}, "
                   f"total {_pesos(limpio['total_producto'])} ({_pesos(sv.d(unitario))} por sobre), "
                   f"fecha {limpio['fecha'].isoformat()}")
        op = OperacionPendiente(
            id=str(uuid.uuid4()), sesion_id=self.ctx.sesion_id, turno=self.ctx.turno, tipo="venta",
            datos={**{k: (str(v) if isinstance(v, (Decimal, date)) else v) for k, v in limpio.items() if k != "payload"},
                   "cliente": nombre_cliente},
            resumen=resumen, expira_en=ahora() + VIGENCIA)
        self.ctx.db.add(op)
        self.ctx.db.commit()
        self.ctx.acciones.append({"tipo": "pendiente", "operacion_id": op.id, "resumen": resumen})
        return {"operacion_id": op.id, "resumen": resumen, "cliente_nuevo": cliente_nuevo,
                "instruccion": "Lee el resumen y pide confirmación. No confirmes en este turno."}

    def _confirmar_operacion(self, operacion_id: str) -> dict:
        op = self.ctx.db.get(OperacionPendiente, operacion_id)
        if not op or op.sesion_id != self.ctx.sesion_id:
            raise sv.ErrorNegocio("No hay una operación pendiente con ese identificador.")
        if op.estado != "pendiente":
            raise sv.ErrorNegocio(f"La operación ya está {op.estado}.")
        if op.turno >= self.ctx.turno:
            raise sv.ErrorNegocio("La confirmación debe venir del usuario en un mensaje posterior al resumen.")
        expira = op.expira_en if op.expira_en.tzinfo else op.expira_en.replace(tzinfo=ahora().tzinfo)
        if expira < ahora():
            op.estado = "expirada"
            self.ctx.db.commit()
            raise sv.ErrorNegocio("La operación expiró; vuelve a dictar la venta.")
        datos = dict(op.datos)
        cliente = datos.pop("cliente", None)
        datos["origen"] = "voz"
        venta = sv.registrar_venta(self.ctx.db, datos, cliente_nombre=cliente)
        op.estado, op.resultado_id = "aplicada", venta.id
        self.ctx.db.commit()
        self.ctx.acciones.append({"tipo": "venta_creada", "venta_id": venta.id})
        return {"ok": True, "venta_id": venta.id, "resumen": op.resumen}

    def _cancelar_operacion(self, operacion_id: str) -> dict:
        op = self.ctx.db.get(OperacionPendiente, operacion_id)
        if not op or op.sesion_id != self.ctx.sesion_id or op.estado != "pendiente":
            raise sv.ErrorNegocio("No hay una operación pendiente que cancelar.")
        op.estado = "cancelada"
        self.ctx.db.commit()
        self.ctx.acciones.append({"tipo": "cancelada", "operacion_id": op.id})
        return {"ok": True}


def pendiente_actual(db: Session, sesion_id: str) -> OperacionPendiente | None:
    op = db.scalar(select(OperacionPendiente).where(OperacionPendiente.sesion_id == sesion_id,
                                                    OperacionPendiente.estado == "pendiente")
                   .order_by(OperacionPendiente.creada_en.desc()))
    if op:
        expira = op.expira_en if op.expira_en.tzinfo else op.expira_en.replace(tzinfo=ahora().tzinfo)
        if expira < ahora():
            op.estado = "expirada"
            db.commit()
            return None
    return op


def _json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    return obj
