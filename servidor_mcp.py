"""Conector de Legado Verde para Claude (servidor MCP remoto, Streamable HTTP).

Permite decirle a Claude —también en modo de voz o en el coche— «¿cuánto vendí
este mes?» o «registra una venta de 10 sobres a la cafetería a $70». Usa la
misma base que el tablero Streamlit (``DATABASE_URL``) y las mismas reglas.

Variables de entorno:
    DATABASE_URL   base PostgreSQL compartida con Streamlit (obligatoria en producción)
    MCP_TOKEN      clave larga y aleatoria; Claude la envía en la URL (?key=) o como Bearer
    PUBLIC_HOST    dominio público (en Render se toma solo de RENDER_EXTERNAL_HOSTNAME)
    PORT           puerto (Render lo define)

Ejecutar:  python servidor_mcp.py
URL para Claude:  https://PUBLIC_HOST/mcp?key=MCP_TOKEN
"""
from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from lv import voz  # noqa: E402
from lv.almacen_sql import Pendientes, url_base  # noqa: E402
from lv.arranque import abrir, ruta_base  # noqa: E402

INSTRUCCIONES = """Conector financiero de Legado Verde (guacamole liofilizado en sobres de 40 g, Jalisco).
El usuario suele hablar por voz y puede ir manejando: responde en una o dos frases cortas, sin listas
ni tablas, con cifras redondeadas dichas con naturalidad. Usa el campo resumen_para_voz.
- Toda cifra sale de estas herramientas; nunca inventes ventas, clientes, precios ni montos.
- Distingue venta neta, margen de contribución y utilidad; las ventas estimadas no son registros verificados.
- Para registrar: llama preparar_venta, lee el resumen y espera la respuesta del usuario.
  Solo si dice que sí, llama confirmar_venta con su frase literal. Si duda o corrige, cancela y prepara de nuevo.
- Si falta el precio o la cantidad, pregúntalos; no los supongas.
- «La cafetería X» significa canal Cafeterías y cliente X."""

Canal = Literal["Cafeterías", "Venta directa", "Mercado Libre", "Amazon", "Shopify", "Otros canales"]
Periodo = Literal["hoy", "ayer", "semana", "mes", "mes_anterior", "anio", "todo"]
LECTURA = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
ESCRITURA = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

_repo = None
_pend = None


def recursos():
    global _repo, _pend
    if _repo is None:
        _repo = abrir()
        url = url_base()
        _pend = Pendientes(url) if url else Pendientes(str(Path(ruta_base()).with_name("pendientes_voz.sqlite3")), "sqlite")
    return _repo, _pend


servidor = MCPServer("Legado Verde Finanzas", instructions=INSTRUCCIONES)


@servidor.tool(annotations=LECTURA)
def consultar_ventas(periodo: Periodo = "mes", canal: Canal | None = None) -> dict:
    """Ventas, sobres, venta neta y margen de contribución de un periodo (opcionalmente de un canal)."""
    repo, _ = recursos()
    return voz.consultar(repo.leer()[1], periodo, canal)


@servidor.tool(annotations=LECTURA)
def ultimas_ventas(cantidad: int = 5) -> dict:
    """Las ventas más recientes con fecha, canal, sobres y venta neta."""
    repo, _ = recursos()
    return voz.ultimas(repo.leer()[1], cantidad)


@servidor.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def preparar_venta(canal: Canal, unidades: int, precio_por_unidad: float,
                   presentacion: str = "Sobre individual", fecha: str = "hoy", cliente: str | None = None,
                   folio: str | None = None, cobrada: bool = False, medio_cobro: str | None = None,
                   referencia_cobro: str | None = None, comision: float | None = None,
                   costo_envio: float | None = None, notas: str | None = None) -> dict:
    """Prepara una venta SIN guardarla y devuelve un resumen para leer al usuario.

    unidades = presentaciones vendidas (sobres individuales o paquetes). precio_por_unidad = precio de
    cada presentación. fecha: «hoy», «ayer» o AAAA-MM-DD (hora de Ciudad de México). cobrada=True solo
    si el usuario dijo que ya le pagaron.
    """
    repo, pend = recursos()
    return voz.preparar(repo, pend, {k: v for k, v in locals().items() if k not in ("repo", "pend")})


@servidor.tool(annotations=ESCRITURA)
def confirmar_venta(operacion_id: str, frase_usuario: str) -> dict:
    """Guarda la venta preparada. frase_usuario = lo que dijo el usuario al confirmar, textual."""
    repo, pend = recursos()
    return voz.confirmar(repo, pend, operacion_id, frase_usuario)


@servidor.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
def cancelar_venta(operacion_id: str) -> dict:
    """Descarta una venta preparada que el usuario no confirmó."""
    _, pend = recursos()
    return voz.cancelar(pend, operacion_id)


class Autenticacion:
    """Exige MCP_TOKEN (en ?key= o Authorization: Bearer) en /mcp. /salud queda abierto."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        ruta = scope.get("path", "")
        if ruta in ("/salud", "/"):
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
            return await send({"type": "http.response.body", "body": b"ok"})
        clave = parse_qs(scope.get("query_string", b"").decode()).get("key", [""])[0]
        cab = dict(scope.get("headers") or [])
        auth = cab.get(b"authorization", b"").decode()
        if auth.lower().startswith("bearer "):
            clave = clave or auth[7:]
        if not self.token or not hmac.compare_digest(clave.encode(), self.token.encode()):
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
            return await send({"type": "http.response.body", "body": b"No autorizado"})
        if ruta == "/mcp/":  # los clientes MCP no siguen redirecciones en POST
            scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
        return await self.app(scope, receive, send)


def crear_app():
    token = os.environ.get("MCP_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("Define MCP_TOKEN con al menos 24 caracteres aleatorios.")
    host = (os.environ.get("PUBLIC_HOST") or os.environ.get("RENDER_EXTERNAL_HOSTNAME") or "").strip()
    seguridad = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(host),
        allowed_hosts=[host, "127.0.0.1:*", "localhost:*"] if host else [],
        allowed_origins=[f"https://{host}", "https://claude.ai"] if host else [])
    app = servidor.streamable_http_app(stateless_http=True, json_response=True, transport_security=seguridad,
                                       host="0.0.0.0")
    return Autenticacion(app, token)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(crear_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), proxy_headers=True,
                forwarded_allow_ips="*")
