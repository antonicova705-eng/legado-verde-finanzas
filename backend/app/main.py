"""API de Legado Verde: KPIs, ventas, asistente de voz/texto, eventos en tiempo real e integraciones."""
from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from . import db as dbmod
from .config import settings
from .eventos import bus
from .ia.asistente import Asistente
from .integraciones import amazon, mercadolibre as ml
from .mcp_servidor import app_mcp, mcp, renovar
from .models import CANALES, Cliente
from .servicios import ventas as sv
from .voz.transcripcion import ErrorTranscripcion, transcribir

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("legado")
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
asistente = Asistente()


# ------------------------------------------------------------------ ciclo de vida
async def _sincronizador() -> None:
    """Sincronización desatendida: reconciliación de ML y Amazon cada SYNC_MINUTOS."""
    while True:
        await asyncio.sleep(settings.sync_minutos * 60)
        await asyncio.to_thread(sincronizar_todo)


def sincronizar_todo() -> dict:
    resultado: dict[str, str] = {}
    with dbmod.SessionLocal() as db:
        if db.get(ml.TokenIntegracion, ml.PROVEEDOR):
            try:
                resultado["mercadolibre"] = f"{ml.reconciliar(db, sv.hoy() - timedelta(days=2))} órdenes"
            except Exception as e:
                log.exception("Sync ML")
                resultado["mercadolibre"] = f"error: {e}"
        if amazon.configurado():
            try:
                n = amazon.sincronizar(db, datetime.now(settings.zona_horaria) - timedelta(days=2))
                p = amazon.reconciliar_pendientes(db)
                resultado["amazon"] = f"{n} órdenes, {p} pendientes revisadas"
            except Exception as e:
                log.exception("Sync Amazon")
                resultado["amazon"] = f"error: {e}"
    if resultado:
        bus.publicar("sync", resultado)
    return resultado


@asynccontextmanager
async def lifespan(_: FastAPI):
    dbmod.init_db()
    if settings.importar_historico_base:  # idempotente: carga jul–oct 2026 sin duplicar
        from scripts.importar_historico import HISTORICO_BASE, importar
        await asyncio.to_thread(importar, HISTORICO_BASE)
    bus.vincular(asyncio.get_running_loop())
    tarea = asyncio.create_task(_sincronizador()) if settings.sync_habilitado else None
    renovar(servidor_mcp)
    async with mcp.session_manager.run():  # servidor MCP para la app de Claude
        yield
    if tarea:
        tarea.cancel()


servidor_mcp = app_mcp()  # crea el session manager antes del lifespan
app = FastAPI(title="Legado Verde", version="2.0.0", lifespan=lifespan)
app.mount("/mcp", servidor_mcp)


class _BarraMCP:
    """Acepta /mcp y /mcp/ por igual: los clientes MCP no siguen redirecciones 307 en POST."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


app.add_middleware(_BarraMCP)


# ------------------------------------------------------------------ seguridad
def autorizado(request: Request, token: str | None = Query(default=None)) -> None:
    """Token de acceso único (app personal). EventSource no envía headers, por eso se acepta ?token=."""
    if not settings.app_token:
        return
    cabecera = request.headers.get("authorization", "")
    recibido = cabecera.removeprefix("Bearer ").strip() or (token or "")
    if not hmac.compare_digest(recibido.encode(), settings.app_token.encode()):
        raise HTTPException(401, "Token inválido")


Protegido = Depends(autorizado)


def _error(e: Exception, codigo: int = 422):
    raise HTTPException(codigo, str(e)) from e


# ------------------------------------------------------------------ esquemas
class VentaEntrada(BaseModel):
    canal: Literal[CANALES]  # type: ignore[valid-type]
    cantidad: int = Field(gt=0)
    total_producto: float | None = Field(default=None, ge=0)
    precio_unitario: float | None = Field(default=None, ge=0)
    cliente: str | None = Field(default=None, max_length=120)
    fecha: date | None = None
    ingreso_envio: float = Field(default=0, ge=0)
    comision: float = Field(default=0, ge=0)
    costo_logistico: float = Field(default=0, ge=0)
    referencia_externa: str | None = Field(default=None, max_length=80)
    notas: str | None = Field(default=None, max_length=500)


class Mensaje(BaseModel):
    sesion_id: str = Field(min_length=8, max_length=64)
    texto: str = Field(min_length=1, max_length=1000)
    modo: Literal["voz", "texto"] = "voz"


# ------------------------------------------------------------------ API de negocio
@app.get("/api/salud")
def salud():
    return {"ok": True, "ia": bool(settings.anthropic_api_key), "stt_respaldo": bool(settings.openai_api_key),
            "mercadolibre": bool(settings.ml_client_id), "amazon": amazon.configurado()}


@app.get("/api/kpis", dependencies=[Protegido])
def kpis(periodo: str = "mes", canal: str | None = None, db: Session = Depends(dbmod.get_db)):
    try:
        r = sv.rango(periodo)
        return {"resumen": sv.resumen(db, r, canal), "equilibrio": sv.punto_equilibrio(db), "supuestos": sv.supuestos(db)}
    except sv.ErrorNegocio as e:
        _error(e)


@app.get("/api/ventas", dependencies=[Protegido])
def listar(limite: int = Query(20, ge=1, le=50), canal: str | None = None, db: Session = Depends(dbmod.get_db)):
    return sv.ultimas(db, limite, canal)


@app.post("/api/ventas", status_code=201, dependencies=[Protegido])
def crear(v: VentaEntrada, db: Session = Depends(dbmod.get_db)):
    try:
        datos = v.model_dump(exclude={"cliente"})
        venta = sv.registrar_venta(db, {**datos, "origen": "manual"}, cliente_nombre=v.cliente)
        return sv.serializar(venta, db)
    except sv.ErrorNegocio as e:
        _error(e)


@app.post("/api/ventas/{venta_id}/anular", dependencies=[Protegido])
def anular(venta_id: int, motivo: str = Query(..., min_length=3), db: Session = Depends(dbmod.get_db)):
    try:
        return sv.serializar(sv.anular(db, venta_id, motivo), db)
    except sv.ErrorNegocio as e:
        _error(e)


@app.post("/api/asistente", dependencies=[Protegido])
def conversar(m: Mensaje, db: Session = Depends(dbmod.get_db)):
    if not settings.anthropic_api_key and asistente._cliente is None:
        raise HTTPException(503, "Configura ANTHROPIC_API_KEY para usar el asistente.")
    try:
        r = asistente.responder(db, m.sesion_id, m.texto, m.modo)
    except Exception as e:
        log.exception("Asistente")
        raise HTTPException(502, "El asistente no respondió. Intenta de nuevo.") from e
    return {"texto": r.texto, "acciones": r.acciones, "pendiente": r.pendiente, "refrescar": r.refrescar}


@app.post("/api/voz/transcribir", dependencies=[Protegido])
async def voz(audio: UploadFile = File(...), db: Session = Depends(dbmod.get_db)):
    contenido = await audio.read()
    nombres = [c.nombre for c in db.query(Cliente).limit(40)]
    try:
        texto = await asyncio.to_thread(transcribir, contenido, audio.filename or "audio.webm",
                                        audio.content_type or "", nombres)
    except ErrorTranscripcion as e:
        _error(e, 400)
    return {"texto": texto}


@app.get("/api/eventos", dependencies=[Protegido])
async def eventos(request: Request):
    cola = bus.suscribir()

    async def flujo():
        try:
            yield {"event": "hola", "data": "{}"}
            while not await request.is_disconnected():
                try:
                    yield await asyncio.wait_for(cola.get(), timeout=25)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}  # mantiene viva la conexión en redes móviles
        finally:
            bus.cancelar(cola)

    return EventSourceResponse(flujo())


@app.post("/api/sincronizar", dependencies=[Protegido])
async def sincronizar_ahora():
    return await asyncio.to_thread(sincronizar_todo)


# ------------------------------------------------------------------ Mercado Libre
@app.get("/integraciones/mercadolibre/conectar", dependencies=[Protegido])
def ml_conectar():
    try:
        return RedirectResponse(ml.url_autorizacion())
    except ml.ErrorML as e:
        _error(e, 400)


@app.get("/integraciones/mercadolibre/callback", response_class=HTMLResponse)
def ml_callback(code: str, state: str, db: Session = Depends(dbmod.get_db)):
    if not ml.validar_estado(state):
        raise HTTPException(400, "Estado OAuth inválido o vencido. Vuelve a conectar.")
    try:
        tok = ml.intercambiar_codigo(db, code)
    except ml.ErrorML as e:
        _error(e, 400)
    return f"<p>Mercado Libre conectado (vendedor {tok.cuenta_id}). Ya puedes cerrar esta ventana.</p>"


@app.post("/integraciones/mercadolibre/webhook")
async def ml_webhook(request: Request, tareas: BackgroundTasks):
    """Responde 200 siempre que el cuerpo sea JSON; el procesamiento ocurre fuera de la petición."""
    try:
        payload = await request.json()
    except Exception:
        return {"ok": False}
    with dbmod.SessionLocal() as db:
        evento_id = ml.recibir_notificacion(db, payload)
    if evento_id:
        tareas.add_task(_procesar_ml, evento_id)
    return {"ok": True}


def _procesar_ml(evento_id: int) -> None:
    with dbmod.SessionLocal() as db:
        ml.procesar_evento(db, evento_id)


# ------------------------------------------------------------------ frontend
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/", include_in_schema=False)
    def inicio():
        return FileResponse(FRONTEND / "index.html")
