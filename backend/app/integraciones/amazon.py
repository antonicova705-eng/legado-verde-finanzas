"""Conector Amazon Selling Partner API (México, región NA).

Diferencia clave con Mercado Libre: Amazon NO envía webhooks HTTP. Las notificaciones
(`ORDER_CHANGE`) llegan a una cola Amazon SQS (o EventBridge) que debemos consumir.
Este módulo ofrece las dos rutas:
1. consumir_sqs(): long-polling de la cola (requiere boto3 y credenciales AWS de la cola).
2. sincronizar(): polling incremental del Orders API (sin AWS); recomendado para empezar.

Autenticación: Login with Amazon (LWA) con refresh token de una app privada autorizada
desde Seller Central. Desde 2023 SP-API ya no exige firma AWS SigV4; basta el header x-amz-access-token.

Comisiones y logística salen del Finances API (eventos financieros por orden), que se
publican días después del envío: mientras no existan, la venta queda pendiente_conciliar.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import TokenIntegracion, Venta, ahora
from ..servicios import ventas as sv

log = logging.getLogger("legado.amazon")
LWA_URL = "https://api.amazon.com/auth/o2/token"
PROVEEDOR = "amazon"
# Clasificación de cargos de Finances API (FeeType)
TARIFAS_LOGISTICAS = {"FBAPerUnitFulfillmentFee", "FBAPerOrderFulfillmentFee", "FBAWeightBasedFee",
                      "ShippingChargeback", "ShippingHB", "FBAInboundTransportationFee"}


class ErrorAmazon(RuntimeError):
    pass


def configurado() -> bool:
    return bool(settings.amz_client_id and settings.amz_client_secret and settings.amz_refresh_token)


def _cliente(http: httpx.Client | None):
    return nullcontext(http) if http is not None else httpx.Client(timeout=30)


def token(db: Session, http: httpx.Client | None = None) -> str:
    tok = db.get(TokenIntegracion, PROVEEDOR)
    if tok:
        expira = tok.expira_en if tok.expira_en.tzinfo else tok.expira_en.replace(tzinfo=timezone.utc)
        if expira > ahora():
            return tok.access_token
    with _cliente(http) as c:
        r = c.post(LWA_URL, data={"grant_type": "refresh_token", "refresh_token": settings.amz_refresh_token,
                                  "client_id": settings.amz_client_id, "client_secret": settings.amz_client_secret})
    if r.status_code != 200:
        raise ErrorAmazon(f"LWA rechazó el refresh token: {r.status_code} {r.text[:200]}")
    data = r.json()
    tok = tok or TokenIntegracion(proveedor=PROVEEDOR)
    tok.access_token = data["access_token"]
    tok.refresh_token = None  # el refresh token vive en variables de entorno, no en BD
    tok.expira_en = ahora() + timedelta(seconds=int(data.get("expires_in", 3600)) - 120)
    db.merge(tok)
    db.commit()
    return tok.access_token


def _get(db: Session, ruta: str, params: dict | None = None, http: httpx.Client | None = None) -> dict:
    acceso = token(db, http)
    with _cliente(http) as c:
        for intento in range(5):
            r = c.get(settings.amz_endpoint + ruta, params=params,
                      headers={"x-amz-access-token": acceso, "Accept": "application/json"})
            if r.status_code == 429 or r.status_code >= 500:  # cuotas bajas en Orders/Finances: backoff
                time.sleep(min(2 ** intento, 30))
                continue
            if r.status_code != 200:
                raise ErrorAmazon(f"GET {ruta} -> {r.status_code}: {r.text[:300]}")
            return r.json().get("payload", {})
    raise ErrorAmazon(f"GET {ruta}: reintentos agotados")


# ------------------------------------------------------------------ Mapeo
def _monto(m: dict | None) -> Decimal:
    if not m:
        return Decimal(0)
    return Decimal(str(m.get("CurrencyAmount", m.get("Amount", 0)) or 0))


def resumir_eventos(eventos: dict) -> dict | None:
    """Suma cargos y tarifas de ShipmentEventList (venta) y RefundEventList (reembolsos)."""
    envios = eventos.get("ShipmentEventList") or []
    if not envios:
        return None
    principal = envio = comision = logistica = otros = Decimal(0)
    cantidad = 0
    for ev in envios:
        for item in ev.get("ShipmentItemList") or []:
            cantidad += int(item.get("QuantityShipped") or 0)
            for cargo in item.get("ItemChargeList") or []:
                monto = _monto(cargo.get("ChargeAmount"))
                if cargo.get("ChargeType") == "Principal":
                    principal += monto
                elif cargo.get("ChargeType", "").startswith("Shipping"):
                    envio += monto
            for tarifa in item.get("ItemFeeList") or []:
                monto = -_monto(tarifa.get("FeeAmount"))  # Amazon reporta tarifas en negativo
                if tarifa.get("FeeType") in TARIFAS_LOGISTICAS:
                    logistica += monto
                elif tarifa.get("FeeType") in ("Commission", "FixedClosingFee", "VariableClosingFee"):
                    comision += monto
                else:
                    otros += monto
    reembolsos = sum((-_monto(c.get("ChargeAmount")) for ev in eventos.get("RefundEventList") or []
                      for item in ev.get("ShipmentItemAdjustmentList") or [] for c in item.get("ItemChargeAdjustmentList") or []),
                     Decimal(0))
    return {"principal": principal, "envio": envio, "comision": comision, "logistica": logistica,
            "otros": otros + max(reembolsos, Decimal(0)), "cantidad": cantidad}


def mapear(orden: dict, eventos: dict | None) -> dict:
    fecha = datetime.fromisoformat(orden["PurchaseDate"].replace("Z", "+00:00")).astimezone(settings.zona_horaria).date()
    cantidad = int(orden.get("NumberOfItemsShipped") or 0) + int(orden.get("NumberOfItemsUnshipped") or 0)
    estado = "anulada" if orden.get("OrderStatus") == "Canceled" else "confirmada"
    res = resumir_eventos(eventos or {})
    base = {"canal": "Amazon", "referencia_externa": orden["AmazonOrderId"], "fecha": fecha, "origen": "amazon",
            "estado": estado, "payload": {"OrderStatus": orden.get("OrderStatus"),
                                          "FulfillmentChannel": orden.get("FulfillmentChannel")}}
    if res:
        return {**base, "cantidad": res["cantidad"] or cantidad or 1, "total_producto": res["principal"],
                "ingreso_envio": res["envio"], "comision": res["comision"], "costo_logistico": res["logistica"],
                "otros_cargos": res["otros"], "pendiente_conciliar": False}
    total = _monto(orden.get("OrderTotal"))
    return {**base, "cantidad": cantidad or 1, "total_producto": total, "pendiente_conciliar": True}


# ------------------------------------------------------------------ Sincronización
def sincronizar_orden(db: Session, orden: dict, http: httpx.Client | None = None) -> None:
    if orden.get("OrderStatus") in ("Pending", "PendingAvailability"):
        return
    eventos = None
    if orden.get("OrderStatus") in ("Shipped", "PartiallyShipped", "InvoiceUnconfirmed"):
        eventos = _get(db, f"/finances/v0/orders/{orden['AmazonOrderId']}/financialEvents", http=http).get("FinancialEvents")
    sv.upsert_externa(db, mapear(orden, eventos))


def sincronizar(db: Session, desde: datetime, http: httpx.Client | None = None) -> int:
    params = {"MarketplaceIds": settings.amz_marketplace_id,
              "LastUpdatedAfter": desde.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    procesadas = 0
    while True:
        pagina = _get(db, "/orders/v0/orders", params, http)
        for orden in pagina.get("Orders", []):
            sincronizar_orden(db, orden, http)
            procesadas += 1
        siguiente = pagina.get("NextToken")
        if not siguiente:
            return procesadas
        params = {"MarketplaceIds": settings.amz_marketplace_id, "NextToken": siguiente}


def reconciliar_pendientes(db: Session, dias: int = 30, http: httpx.Client | None = None) -> int:
    """Reintenta Finances API para ventas aún sin cargos (se publican días después del envío)."""
    limite = sv.hoy() - timedelta(days=dias)
    pendientes = db.scalars(select(Venta).where(Venta.canal == "Amazon", Venta.pendiente_conciliar.is_(True),
                                                Venta.fecha >= limite)).all()
    for v in pendientes:
        orden = _get(db, f"/orders/v0/orders/{v.referencia_externa}", http=http)
        if orden:
            sincronizar_orden(db, orden, http)
    return len(pendientes)


def consumir_sqs(db_factory, max_mensajes: int = 10) -> int:
    """Consume notificaciones ORDER_CHANGE desde SQS. Requiere `pip install boto3` y AWS_* en entorno."""
    if not settings.amz_sqs_url:
        return 0
    import boto3  # dependencia opcional
    sqs = boto3.client("sqs")
    resp = sqs.receive_message(QueueUrl=settings.amz_sqs_url, MaxNumberOfMessages=max_mensajes, WaitTimeSeconds=20)
    n = 0
    for msg in resp.get("Messages", []):
        try:
            cuerpo = json.loads(msg["Body"])
            orden_id = cuerpo["Payload"]["OrderChangeNotification"]["AmazonOrderId"]
            with db_factory() as db:
                orden = _get(db, f"/orders/v0/orders/{orden_id}")
                sincronizar_orden(db, orden)
            sqs.delete_message(QueueUrl=settings.amz_sqs_url, ReceiptHandle=msg["ReceiptHandle"])
            n += 1
        except Exception:  # el mensaje vuelve a la cola tras el visibility timeout
            log.exception("Error procesando mensaje SQS de Amazon")
    return n
