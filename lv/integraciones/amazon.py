"""Cliente de Amazon Selling Partner API (SP-API) para México.

* Autenticación: Login with Amazon (LWA), ``grant_type=refresh_token``. Desde
  2023 SP-API no requiere firma AWS SigV4; basta ``x-amz-access-token``.
* Pedidos: Orders API **v2026-01-01**, ``GET /orders/2026-01-01/orders`` con
  ``lastUpdatedAfter``, ``paginationToken`` e ``includedData``. Amazon anunció
  que las operaciones v0 (getOrders, getOrderItems…) deben migrarse antes del
  27-mar-2027, por eso se usa la versión nueva.
  Límite publicado: 0.0056 solicitudes/s con ráfaga de 20 → el cliente respeta
  ese ritmo; una sincronización grande puede tardar varios minutos.
* Comisiones y reembolsos: Finances API v0
  ``GET /finances/v0/orders/{orderId}/financialEvents`` (aparecen después del
  envío). Mientras no existan, quedan como pendientes.

Reglas de reconocimiento:
* ``UNSHIPPED``, ``PARTIALLY_SHIPPED``, ``SHIPPED`` → reconocida (fecha de creación).
* ``PENDING``, ``PENDING_AVAILABILITY``, ``INVOICE_UNCONFIRMED`` → pendiente.
* ``CANCELLED`` → cancelación. ``UNFULFILLABLE`` → revisión.

Campos marcados «por validar» se mapearon desde la referencia publicada y deben
comprobarse con la primera respuesta real de tu cuenta (el JSON original se
conserva para ello).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from ..util import ahora_local, fecha_local_de_iso
from .estado import Estado, iso_utc
from .http import ClienteHTTP, ErrorAPI, LimiteRitmo

PLATAFORMA = "Amazon"
LWA = "https://api.amazon.com/auth/o2/token"
MARKETPLACE_MX = "A1AM78C64UM0Y8"
RECONOCIDOS = {"UNSHIPPED", "PARTIALLY_SHIPPED", "SHIPPED"}
PENDIENTES = {"PENDING", "PENDING_AVAILABILITY", "INVOICE_UNCONFIRMED"}


def configuracion() -> dict:
    c = {k: os.environ.get(k) for k in ("AMZ_LWA_CLIENT_ID", "AMZ_LWA_CLIENT_SECRET", "AMZ_REFRESH_TOKEN",
                                        "AMZ_SELLER_ID", "AMZ_MARKETPLACE_ID", "AMZ_ENDPOINT")}
    c["AMZ_MARKETPLACE_ID"] = c["AMZ_MARKETPLACE_ID"] or MARKETPLACE_MX
    c["AMZ_ENDPOINT"] = c["AMZ_ENDPOINT"] or "https://sellingpartnerapi-na.amazon.com"
    return c


def configurada() -> bool:
    c = configuracion()
    return all(c[k] for k in ("AMZ_LWA_CLIENT_ID", "AMZ_LWA_CLIENT_SECRET", "AMZ_REFRESH_TOKEN", "AMZ_SELLER_ID"))


def _monto(m) -> float | None:
    if not isinstance(m, dict):
        return None
    v = m.get("amount", m.get("Amount", m.get("CurrencyAmount")))
    return float(v) if v is not None else None


def _moneda(m) -> str | None:
    if not isinstance(m, dict):
        return None
    return m.get("currencyCode") or m.get("CurrencyCode")


class Amazon:
    plataforma = PLATAFORMA

    def __init__(self, estado: Estado, http: ClienteHTTP | None = None, cfg: dict | None = None,
                 dormir=None):
        self.cfg = cfg or configuracion()
        self.estado = estado
        self.http = http or ClienteHTTP()
        self.cuenta = str(self.cfg["AMZ_SELLER_ID"])
        kw = {"dormir": dormir} if dormir else {}
        self.limite_pedidos = LimiteRitmo(0.0056, 20, **kw)
        self.limite_finanzas = LimiteRitmo(0.5, 30, **kw)

    def token(self) -> str:
        tok = self.estado.token(PLATAFORMA, self.cuenta)
        if self.estado.vigente(tok):
            return tok["access_token"]
        if not self.cfg.get("AMZ_REFRESH_TOKEN"):
            raise ErrorAPI(None, "Falta autorizar la cuenta de Amazon (AMZ_REFRESH_TOKEN).")
        r = self.http.json("POST", LWA, formulario={
            "grant_type": "refresh_token", "refresh_token": self.cfg["AMZ_REFRESH_TOKEN"],
            "client_id": self.cfg["AMZ_LWA_CLIENT_ID"], "client_secret": self.cfg["AMZ_LWA_CLIENT_SECRET"]})
        # El refresh token de LWA no rota: permanece solo en la variable de entorno.
        self.estado.guardar_token(PLATAFORMA, self.cuenta, r["access_token"], r.get("expires_in", 3600))
        return r["access_token"]

    def _get(self, ruta: str, params: dict | None, limite: LimiteRitmo):
        return self.http.json("GET", self.cfg["AMZ_ENDPOINT"] + ruta, params=params,
                              encabezados={"x-amz-access-token": self.token()}, limite=limite)

    def pedidos_actualizados(self, desde: datetime, hasta: datetime):
        token_pagina = None
        while True:
            params = {"marketplaceIds": self.cfg["AMZ_MARKETPLACE_ID"], "maxResultsPerPage": 100,
                      "includedData": "PROCEEDS,PROMOTION,CANCELLATION,FULFILLMENT"}
            if token_pagina:
                params["paginationToken"] = token_pagina
            else:
                params["lastUpdatedAfter"] = iso_utc(desde)
                params["lastUpdatedBefore"] = iso_utc(hasta)
            pagina = self._get("/orders/2026-01-01/orders", params, self.limite_pedidos)
            yield ("pagina", None)
            for o in pagina.get("orders", []):
                yield ("pedido", o)
            token_pagina = (pagina.get("pagination") or {}).get("nextToken")
            if not token_pagina:
                break

    def pedido(self, pedido_id: str) -> dict:
        r = self._get(f"/orders/2026-01-01/orders/{pedido_id}",
                      {"includedData": "PROCEEDS,PROMOTION,CANCELLATION,FULFILLMENT"}, self.limite_pedidos)
        return r.get("order", r)

    def eventos_financieros(self, pedido_id: str) -> dict:
        """Comisiones y reembolsos por SKU. Vacío mientras Amazon no los publique."""
        r = self._get(f"/finances/v0/orders/{pedido_id}/financialEvents", {"MaxResultsPerPage": 100},
                      self.limite_finanzas)
        ev = (r.get("payload") or {}).get("FinancialEvents") or {}
        por_sku: dict[str, dict] = {}
        for nombre, signo in (("ShipmentEventList", 1), ("RefundEventList", -1)):
            for e in ev.get(nombre) or []:
                for it in e.get("ShipmentItemList") or e.get("ShipmentItemAdjustmentList") or []:
                    sku = it.get("SellerSKU")
                    d = por_sku.setdefault(sku, {"comision": 0.0, "reembolso": 0.0, "con_cargos": False,
                                                 "unidades_reembolsadas": 0})
                    for fee in it.get("ItemFeeList") or it.get("ItemFeeAdjustmentList") or []:
                        v = _monto(fee.get("FeeAmount"))
                        if v is not None:
                            d["comision"] += -v  # Amazon reporta cargos como negativos
                            d["con_cargos"] = True
                    if signo < 0:
                        for ch in it.get("ItemChargeAdjustmentList") or []:
                            v = _monto(ch.get("ChargeAmount"))
                            if v is not None and ch.get("ChargeType") == "Principal":
                                d["reembolso"] += -v
                        d["unidades_reembolsadas"] += int(it.get("QuantityShipped") or 0)
        return por_sku

    def normalizar(self, o: dict, finanzas: dict | None = None) -> list[dict]:
        ful = o.get("fulfillment") or {}
        estado = ful.get("fulfillmentStatus") or o.get("OrderStatus")
        clase = ("reconocida" if estado in RECONOCIDOS else "pendiente" if estado in PENDIENTES
                 else "cancelada" if estado == "CANCELLED" else "revision")
        fecha = fecha_local_de_iso(o.get("createdTime"))
        partidas = []
        for it in o.get("orderItems") or []:
            prod = it.get("product") or {}
            precio = prod.get("price") or {}
            unit = _monto(precio.get("unitPrice"))
            q = int(it.get("quantityOrdered") or 0)
            promo = 0.0
            promo_ok = True
            for b in (it.get("promotion") or {}).get("breakdowns") or []:
                v = _monto(b.get("discountAmount") or b.get("amount"))  # por validar con respuesta real
                if v is None:
                    promo_ok = False
                else:
                    promo += abs(v)
            sku = prod.get("sellerSku")
            fin = (finanzas or {}).get(sku) or {}
            partidas.append({
                "clave": f"{PLATAFORMA}|{self.cuenta}|{o['orderId']}|{it.get('orderItemId')}",
                "plataforma": PLATAFORMA, "cuenta": self.cuenta, "pedido": str(o["orderId"]),
                "partida": str(it.get("orderItemId")), "sku": sku, "titulo": prod.get("title"),
                "cantidad": q, "precio_unitario": unit,
                "descuento_total": round(promo, 2) if promo_ok else None, "descuento_por_conciliar": not promo_ok,
                "moneda": _moneda(precio.get("unitPrice")) or "MXN",
                "comision": round(fin["comision"], 2) if fin.get("con_cargos") else None,
                "comision_fuente": "Finances API (eventos financieros)" if fin.get("con_cargos") else None,
                "envio_cobrado": None, "logistica": None,
                "reembolsado": round(fin.get("reembolso", 0.0), 2),
                "reembolso_multipartida": False,
                "unidades_devueltas": fin.get("unidades_reembolsadas") if fin else 0,
                "estado_plataforma": estado, "clase": clase, "fecha_pedido": fecha,
                "actualizado": o.get("lastUpdatedTime"), "pack_id": None,
                "entrega": "Entregado" if estado == "SHIPPED" else "Pendiente",
            })
        if not partidas and clase != "pendiente":
            raise ErrorAPI(None, f"Pedido {o.get('orderId')} sin partidas en la respuesta.")
        return partidas

    def ventana_incremental(self, cursor: str | None, desde_inicial: datetime) -> tuple[datetime, datetime]:
        # Por precaución (requisito documentado en v0): lastUpdatedBefore al menos 2 minutos en el pasado.
        hasta = ahora_local() - timedelta(minutes=3)
        desde = datetime.fromisoformat(cursor) - timedelta(minutes=15) if cursor else desde_inicial
        return desde, hasta
