"""Servidor MCP remoto: expone los datos de Legado Verde como conector personalizado de Claude.

Así la voz la maneja la app de Claude (modo de voz en iOS/Android): tú hablas con Claude,
Claude llama estas herramientas y el tablero web se actualiza por SSE.

Montado en /mcp (Streamable HTTP, sin estado, respuestas JSON). Autenticación: token fijo
MCP_TOKEN, en el header `Authorization: Bearer …` o, si tu plan no permite headers, en la URL
(`/mcp/?key=…`). Toda la lógica reutiliza ia/herramientas.py y servicios/ventas.py.

Seguridad de escritura (aquí no hay "turnos" como en el asistente propio):
1. preparar_venta no escribe; crea una operación pendiente que vence en 5 minutos.
2. confirmar_venta exige: la frase literal del usuario con una afirmación clara y que hayan
   pasado al menos MIN_ESPERA segundos desde la preparación (tiempo de leer el resumen y oír la respuesta).
3. Además, Claude pide tu aprobación para herramientas de escritura salvo que la marques como "permitir siempre".
"""
from __future__ import annotations

import hmac
import re
from typing import Literal
from urllib.parse import parse_qs, urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from . import db as dbmod
from .config import settings
from .ia.herramientas import Contexto, Ejecutor
from .models import OperacionPendiente, ahora
from .servicios import ventas as sv

SESION = "claude-mcp"
MIN_ESPERA = 4  # segundos
AFIRMATIVO = re.compile(r"\b(s[ií]|confirm[oa]|dale|adelante|correcto|as[ií] es|ok(ay)?|de acuerdo|h[aá]zlo|registra(la)?)\b", re.I)
NEGATIVO = re.compile(r"\b(no|cancela|espera|alto|corrige|cambia)\b", re.I)

Canal = Literal["Mercado Libre", "Amazon", "Cafeterías", "Tienda en línea", "Venta directa", "Otros"]
Periodo = Literal["hoy", "ayer", "semana", "mes", "mes_anterior", "anio", "todo"]

INSTRUCCIONES = """Conector financiero de Legado Verde (guacamole liofilizado, sobres de 40 g, Jalisco).
El usuario suele hablar por voz y puede ir manejando: responde en 1 o 2 frases cortas, sin listas,
con cifras redondeadas dichas de forma natural.
- Toda cifra sale de estas herramientas; no inventes ventas, clientes ni montos.
- Distingue ventas, neto de canal, contribución (estimada si así viene) y utilidad.
- Para registrar una venta: llama preparar_venta, lee el resumen y pregunta "¿Lo confirmo?".
  Espera la respuesta del usuario. Solo entonces llama confirmar_venta con su frase literal.
- "Cafetería X" significa canal Cafeterías y cliente X."""


def _seguridad() -> TransportSecuritySettings:
    host = urlparse(settings.base_url).netloc
    hosts = [host, "127.0.0.1:*", "localhost:*", "testserver"]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                     allowed_origins=[settings.base_url, "https://claude.ai"])


mcp = FastMCP("Legado Verde Finanzas", instructions=INSTRUCCIONES, stateless_http=True, json_response=True,
              streamable_http_path="/", transport_security=_seguridad())

LECTURA = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _ejecutar(nombre: str, entrada: dict, turno: int = 0) -> dict:
    with dbmod.SessionLocal() as db:
        return Ejecutor(Contexto(db=db, sesion_id=SESION, turno=turno)).ejecutar(nombre, entrada)


@mcp.tool(annotations=LECTURA)
def consultar_ventas(periodo: Periodo = "mes", canal: Canal | None = None) -> dict:
    """Totales de ventas, sobres, neto de canal y contribución en un periodo, opcionalmente de un canal."""
    return _ejecutar("consultar_ventas", {"periodo": periodo, "canal": canal})


@mcp.tool(annotations=LECTURA)
def punto_de_equilibrio() -> dict:
    """Avance del mes hacia el punto de equilibrio (estimación con los costos del catálogo)."""
    return _ejecutar("punto_de_equilibrio", {})


@mcp.tool(annotations=LECTURA)
def ultimas_ventas(limite: int = 5, canal: Canal | None = None) -> dict:
    """Ventas más recientes (máximo 10), opcionalmente de un canal."""
    return _ejecutar("ultimas_ventas", {"limite": max(1, min(limite, 10)), "canal": canal})


@mcp.tool(annotations=LECTURA)
def buscar_cliente(nombre: str) -> dict:
    """Busca clientes por nombre aproximado (tolera errores de dictado)."""
    return _ejecutar("buscar_cliente", {"nombre": nombre})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def preparar_venta(canal: Canal, cantidad: int, cliente: str | None = None, monto_total: float | None = None,
                   precio_unitario: float | None = None, fecha: str | None = None, notas: str | None = None) -> dict:
    """Prepara SIN GUARDAR una venta dictada. Devuelve un resumen que debes leer al usuario y pedirle confirmación.
    Usa monto_total si dijo el total o precio_unitario si dijo el precio por sobre. Fecha YYYY-MM-DD (omitir si es hoy)."""
    return _ejecutar("preparar_venta", {"canal": canal, "cantidad": cantidad, "cliente": cliente, "monto_total": monto_total,
                                        "precio_unitario": precio_unitario, "fecha": fecha, "notas": notas})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def confirmar_venta(operacion_id: str, frase_del_usuario: str) -> dict:
    """Guarda una venta preparada. Llámala SOLO después de que el usuario respondió al resumen;
    frase_del_usuario es su respuesta literal (por ejemplo "sí, confírmala")."""
    with dbmod.SessionLocal() as db:
        op = db.get(OperacionPendiente, operacion_id)
        if not op or op.sesion_id != SESION or op.estado != "pendiente":
            return {"error": "No hay una venta pendiente con ese identificador."}
        if NEGATIVO.search(frase_del_usuario) or not AFIRMATIVO.search(frase_del_usuario):
            return {"error": "La frase no es una confirmación clara. Pregunta de nuevo o cancela."}
        creada = op.creada_en if op.creada_en.tzinfo else op.creada_en.replace(tzinfo=ahora().tzinfo)
        if (ahora() - creada).total_seconds() < MIN_ESPERA:
            return {"error": "Primero lee el resumen al usuario y espera su respuesta antes de confirmar."}
        # Confirmación válida: se aplica con un turno posterior al de la preparación.
        return Ejecutor(Contexto(db=db, sesion_id=SESION, turno=op.turno + 1)).ejecutar(
            "confirmar_operacion", {"operacion_id": operacion_id})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def cancelar_venta(operacion_id: str) -> dict:
    """Descarta una venta preparada que el usuario no confirmó o quiere corregir."""
    return _ejecutar("cancelar_operacion", {"operacion_id": operacion_id})


# ------------------------------------------------------------------ autenticación ASGI
class ConToken:
    """Exige MCP_TOKEN en Authorization: Bearer o en ?key= antes de llegar al servidor MCP."""

    def __init__(self, app, token: str | None):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            recibido = headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not recibido:
                recibido = (parse_qs(scope.get("query_string", b"").decode()).get("key") or [""])[0]
            if not hmac.compare_digest(recibido.encode(), self.token.encode()):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b'{"error":"token invalido"}'})
                return
        await self.app(scope, receive, send)


def app_mcp():
    return ConToken(mcp.streamable_http_app(), settings.mcp_token or settings.app_token)


def renovar(envoltura: ConToken) -> None:
    """Crea un session manager nuevo por cada arranque del lifespan (el del SDK solo puede correr una vez)."""
    mcp._session_manager = None  # noqa: SLF001 — el SDK no expone un reinicio público
    envoltura.app = mcp.streamable_http_app()
