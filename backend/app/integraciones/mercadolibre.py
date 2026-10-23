"""Conector Mercado Libre (México): OAuth 2.0, notificaciones `orders_v2` y reconciliación.

Principios:
- El webhook responde 200 de inmediato y solo encola; el procesamiento ocurre en segundo plano.
- La notificación NO se usa como fuente de datos: se verifica app/vendedor y se consulta la orden con el token.
  Así un POST falsificado no puede inyectar ventas.
- Idempotencia por `_id` de notificación y por (canal, referencia_externa) en ventas.
- Reconciliación periódica con /orders/search por si se pierden notificaciones (ML reintenta solo ~1 hora).

Campos a validar con una orden real de varias unidades antes de producción:
`order_items[].sale_fee` (se trata como comisión POR UNIDAD) y el costo de envío del vendedor
en /shipments/{id}/costs. Si no se pueden obtener, la venta queda con pendiente_conciliar=True.
"""
from __future__ import annotations

import logging
import secrets
import time
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import EventoWebhook, TokenIntegracion, ahora
from ..servicios import ventas as sv

log = logging.getLogger("legado.ml")
API = "https://api.mercadolibre.com"
PROVEEDOR = "mercadolibre"
_estados_oauth: dict[str, float] = {}


class ErrorML(RuntimeError):
    pass


def _http() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=20, headers={"Accept": "application/json"})


def _cliente(http: httpx.Client | None):
    """Usa el cliente inyectado sin cerrarlo, o crea uno temporal."""
    return nullcontext(http) if http is not None else _http()


# ------------------------------------------------------------------ OAuth 2.0
def redirect_uri() -> str:
    return f"{settings.base_url}/integraciones/mercadolibre/callback"


def url_autorizacion() -> str:
    if not settings.ml_client_id:
        raise ErrorML("Falta ML_CLIENT_ID.")
    estado = secrets.token_urlsafe(24)
    _estados_oauth[estado] = time.time() + 600
    return settings.ml_auth_url + "?" + urlencode({"response_type": "code", "client_id": settings.ml_client_id,
                                                    "redirect_uri": redirect_uri(), "state": estado})


def validar_estado(estado: str) -> bool:
    vence = _estados_oauth.pop(estado, 0)
    return vence > time.time()


def _guardar_token(db: Session, data: dict) -> TokenIntegracion:
    tok = db.get(TokenIntegracion, PROVEEDOR) or TokenIntegracion(proveedor=PROVEEDOR)
    tok.access_token = data["access_token"]
    tok.refresh_token = data.get("refresh_token") or tok.refresh_token  # el refresh token rota: guardar siempre el nuevo
    tok.cuenta_id = str(data.get("user_id") or tok.cuenta_id or "")
    tok.expira_en = ahora() + timedelta(seconds=int(data.get("expires_in", 21600)) - 120)
    db.merge(tok)
    db.commit()
    return tok


def intercambiar_codigo(db: Session, codigo: str, http: httpx.Client | None = None) -> TokenIntegracion:
    with _cliente(http) as c:
        r = c.post("/oauth/token", data={"grant_type": "authorization_code", "client_id": settings.ml_client_id,
                                         "client_secret": settings.ml_client_secret, "code": codigo,
                                         "redirect_uri": redirect_uri()})
    if r.status_code != 200:
        raise ErrorML(f"OAuth rechazado: {r.status_code} {r.text[:200]}")
    return _guardar_token(db, r.json())


def token_vigente(db: Session, http: httpx.Client | None = None) -> TokenIntegracion:
    tok = db.get(TokenIntegracion, PROVEEDOR)
    if not tok:
        raise ErrorML("Mercado Libre no está conectado. Abre /integraciones/mercadolibre/conectar.")
    expira = tok.expira_en if tok.expira_en.tzinfo else tok.expira_en.replace(tzinfo=timezone.utc)
    if expira > ahora():
        return tok
    with _cliente(http) as c:
        r = c.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": settings.ml_client_id,
                                         "client_secret": settings.ml_client_secret,
                                         "refresh_token": tok.refresh_token})
    if r.status_code != 200:
        raise ErrorML(f"No se pudo renovar el token: {r.status_code}. Vuelve a conectar la cuenta.")
    return _guardar_token(db, r.json())


def _get(db: Session, ruta: str, params: dict | None = None, http: httpx.Client | None = None) -> dict:
    tok = token_vigente(db, http)
    with _cliente(http) as cliente:
        return _get_con_reintentos(db, cliente, tok, ruta, params, http)


def _get_con_reintentos(db, cliente, tok, ruta, params, http):
    for intento in range(4):
        r = cliente.get(ruta, params=params, headers={"Authorization": f"Bearer {tok.access_token}"})
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(2 ** intento, 8))
            continue
        if r.status_code == 401 and intento == 0:
            tok.expira_en = ahora() - timedelta(seconds=1)
            db.commit()
            tok = token_vigente(db, http)
            continue
        if r.status_code != 200:
            raise ErrorML(f"GET {ruta} -> {r.status_code}: {r.text[:200]}")
        return r.json()
    raise ErrorML(f"GET {ruta}: reintentos agotados")


# ------------------------------------------------------------------ Webhook
def recibir_notificacion(db: Session, payload: dict) -> int | None:
    """Registra la notificación si es válida y nueva. Devuelve el id del evento a procesar o None."""
    if str(payload.get("application_id")) != str(settings.ml_client_id):
        log.warning("Notificación ML de otra aplicación: %s", payload.get("application_id"))
        return None
    tok = db.get(TokenIntegracion, PROVEEDOR)
    if tok and tok.cuenta_id and str(payload.get("user_id")) != tok.cuenta_id:
        log.warning("Notificación ML de otro vendedor: %s", payload.get("user_id"))
        return None
    if payload.get("topic") not in ("orders_v2", "shipments"):
        return None
    evento = EventoWebhook(proveedor=PROVEEDOR, evento_id=str(payload.get("_id") or payload.get("resource")),
                           topic=payload["topic"], resource=str(payload.get("resource", "")))
    db.add(evento)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None  # duplicado: ML reintenta si no recibió 200 a tiempo
    return evento.id


def procesar_evento(db: Session, evento_id: int, http: httpx.Client | None = None) -> None:
    evento = db.get(EventoWebhook, evento_id)
    if not evento or evento.procesado_en:
        return
    evento.intentos += 1
    try:
        if evento.topic == "orders_v2":
            orden_id = evento.resource.rstrip("/").split("/")[-1]
            sincronizar_orden(db, orden_id, http)
        evento.procesado_en, evento.error = ahora(), None
    except Exception as e:  # se registra y la reconciliación lo reintenta
        evento.error = str(e)[:500]
        log.exception("Error procesando evento ML %s", evento_id)
    db.commit()


# ------------------------------------------------------------------ Mapeo
def costo_envio_vendedor(costos: dict | None) -> Decimal | None:
    """De /shipments/{id}/costs: suma lo que paga el vendedor (senders[].cost)."""
    if not costos:
        return None
    senders = costos.get("senders") or []
    if not senders:
        return None
    return sum((Decimal(str(s.get("cost") or 0)) for s in senders), Decimal(0))


def mapear_orden(orden: dict, costo_envio: Decimal | None) -> dict:
    items = orden.get("order_items") or []
    cantidad = sum(int(i.get("quantity") or 0) for i in items)
    total = sum((Decimal(str(i.get("unit_price") or 0)) * int(i.get("quantity") or 0) for i in items), Decimal(0))
    comision = sum((Decimal(str(i.get("sale_fee") or 0)) * int(i.get("quantity") or 0) for i in items), Decimal(0))
    creada = orden.get("date_closed") or orden.get("date_created")
    fecha = datetime.fromisoformat(creada.replace("Z", "+00:00")).astimezone(settings.zona_horaria).date() if creada else None
    estado = "anulada" if orden.get("status") in ("cancelled", "invalid") else "confirmada"
    titulos = ", ".join(sorted({(i.get("item") or {}).get("title", "") for i in items if i.get("item")}))[:120]
    return {
        "canal": "Mercado Libre", "referencia_externa": str(orden["id"]),
        "fecha": fecha, "cantidad": cantidad or 1, "total_producto": total, "comision": comision,
        "costo_logistico": costo_envio or Decimal(0), "pendiente_conciliar": costo_envio is None and bool(orden.get("shipping", {}).get("id")),
        "producto": titulos or "Guacamole Liofilizado 40g", "origen": "mercadolibre", "estado": estado,
        "payload": {"status": orden.get("status"), "pack_id": orden.get("pack_id"), "shipping_id": (orden.get("shipping") or {}).get("id"),
                    "total_amount": orden.get("total_amount"), "currency": orden.get("currency_id")},
    }


def sincronizar_orden(db: Session, orden_id: str, http: httpx.Client | None = None) -> None:
    orden = _get(db, f"/orders/{orden_id}", http=http)
    if orden.get("status") not in ("paid", "cancelled", "invalid", "partially_refunded"):
        return  # pagos pendientes: se registrarán al confirmarse
    envio = None
    shipping_id = (orden.get("shipping") or {}).get("id")
    if shipping_id:
        try:
            envio = costo_envio_vendedor(_get(db, f"/shipments/{shipping_id}/costs", http=http))
        except ErrorML as e:
            log.warning("Costo de envío no disponible para %s: %s", shipping_id, e)
    sv.upsert_externa(db, mapear_orden(orden, envio))


def reconciliar(db: Session, desde: date, http: httpx.Client | None = None) -> int:
    """Recorre las órdenes desde una fecha. Cubre notificaciones perdidas y envíos no conciliados."""
    tok = token_vigente(db, http)
    offset, procesadas = 0, 0
    while True:
        pagina = _get(db, "/orders/search", {"seller": tok.cuenta_id, "order.date_created.from": f"{desde.isoformat()}T00:00:00.000-00:00",
                                             "sort": "date_asc", "offset": offset, "limit": 50}, http=http)
        for orden in pagina.get("results", []):
            sincronizar_orden(db, str(orden["id"]), http)
            procesadas += 1
        offset += 50
        if offset >= int((pagina.get("paging") or {}).get("total", 0)):
            return procesadas
