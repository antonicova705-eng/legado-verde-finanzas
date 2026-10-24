"""Cliente oficial de Mercado Libre (API REST + OAuth 2.0).

Endpoints usados (documentación de developers.mercadolibre):
* ``POST /oauth/token``: renovación del token; el refresh token **rota** en cada
  uso, por eso se guarda el nuevo en la base de integraciones.
* ``GET /orders/search?seller=…&order.date_last_updated.from/to``: búsqueda
  paginada (offset/limit). La API conserva órdenes de hasta 12 meses.
* ``GET /orders/{id}``: detalle, usado al procesar notificaciones ``orders_v2``.

Reglas de reconocimiento (documentadas también en el README):
* ``paid`` y ``partially_refunded`` → venta reconocida en la fecha de cierre
  (``date_closed``; si falta, ``date_created``), en hora de Ciudad de México.
* ``confirmed``, ``payment_required``, ``payment_in_process``, ``partially_paid``
  → pedido pendiente: se guarda en preparación pero no entra a reportes.
* ``cancelled`` / ``pending_cancel`` → cancelación.
* Un pedido pagado NO es un depósito: no se crean cobros; la liquidación queda
  pendiente hasta conciliarla.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from ..util import ahora_local, fecha_local_de_iso
from .estado import Estado, iso_utc
from .http import ClienteHTTP, ErrorAPI

API = "https://api.mercadolibre.com"
AUTH_MX = "https://auth.mercadolibre.com.mx/authorization"
PLATAFORMA = "Mercado Libre"

RECONOCIDOS = {"paid", "partially_refunded"}
PENDIENTES = {"confirmed", "payment_required", "payment_in_process", "partially_paid"}
CANCELADOS = {"cancelled", "pending_cancel", "invalid"}


def configuracion() -> dict:
    return {k: os.environ.get(k) for k in ("ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_SELLER_ID",
                                           "ML_REDIRECT_URI", "ML_REFRESH_TOKEN")}


def configurada() -> bool:
    c = configuracion()
    return all(c[k] for k in ("ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_SELLER_ID"))


def url_autorizacion() -> str:
    c = configuracion()
    return f"{AUTH_MX}?response_type=code&client_id={c['ML_CLIENT_ID']}&redirect_uri={c['ML_REDIRECT_URI']}"


class MercadoLibre:
    plataforma = PLATAFORMA

    def __init__(self, estado: Estado, http: ClienteHTTP | None = None, cfg: dict | None = None):
        self.cfg = cfg or configuracion()
        self.estado = estado
        self.http = http or ClienteHTTP()
        self.cuenta = str(self.cfg["ML_SELLER_ID"])

    # ------------------------------------------------------------ autenticación
    def intercambiar_codigo(self, codigo: str):
        r = self.http.json("POST", f"{API}/oauth/token", formulario={
            "grant_type": "authorization_code", "client_id": self.cfg["ML_CLIENT_ID"],
            "client_secret": self.cfg["ML_CLIENT_SECRET"], "code": codigo,
            "redirect_uri": self.cfg["ML_REDIRECT_URI"]})
        self._guardar(r)

    def _guardar(self, r: dict):
        if str(r.get("user_id", self.cuenta)) != self.cuenta:
            raise ErrorAPI(None, "La cuenta autorizada no coincide con ML_SELLER_ID.")
        self.estado.guardar_token(PLATAFORMA, self.cuenta, r["access_token"], r.get("expires_in", 21600),
                                  r.get("refresh_token"))

    def token(self) -> str:
        tok = self.estado.token(PLATAFORMA, self.cuenta)
        if self.estado.vigente(tok):
            return tok["access_token"]
        refresh = (tok or {}).get("refresh_token") or self.cfg.get("ML_REFRESH_TOKEN")
        if not refresh:
            raise ErrorAPI(None, "Falta autorizar la cuenta de Mercado Libre (no hay refresh token).")
        r = self.http.json("POST", f"{API}/oauth/token", formulario={
            "grant_type": "refresh_token", "client_id": self.cfg["ML_CLIENT_ID"],
            "client_secret": self.cfg["ML_CLIENT_SECRET"], "refresh_token": refresh})
        self._guardar(r)
        return r["access_token"]

    def _get(self, ruta: str, params: dict | None = None):
        return self.http.json("GET", f"{API}{ruta}", params=params,
                              encabezados={"Authorization": f"Bearer {self.token()}"})

    # ------------------------------------------------------------ consulta
    def pedidos_actualizados(self, desde: datetime, hasta: datetime):
        """Itera pedidos modificados en la ventana, incluidos los cancelados."""
        vistos = set()
        for filtro in ({}, {"order.status": "cancelled"}):
            offset, limite = 0, 50
            while True:
                params = {"seller": self.cuenta, "order.date_last_updated.from": iso_utc(desde).replace("Z", ".000-00:00"),
                          "order.date_last_updated.to": iso_utc(hasta).replace("Z", ".000-00:00"),
                          "sort": "date_asc", "offset": offset, "limit": limite, **filtro}
                pagina = self._get("/orders/search", params)
                resultados = pagina.get("results", [])
                yield ("pagina", None)
                for o in resultados:
                    if o["id"] not in vistos:
                        vistos.add(o["id"])
                        yield ("pedido", o)
                total = pagina.get("paging", {}).get("total", 0)
                offset += limite
                if not resultados or offset >= total:
                    break

    def pedido(self, pedido_id: str) -> dict:
        return self._get(f"/orders/{pedido_id}")

    # ------------------------------------------------------------ normalización
    def normalizar(self, o: dict) -> list[dict]:
        estado = o.get("status")
        clase = ("reconocida" if estado in RECONOCIDOS else "pendiente" if estado in PENDIENTES
                 else "cancelada" if estado in CANCELADOS else "revision")
        fecha = fecha_local_de_iso(o.get("date_closed") or o.get("date_created"))
        reembolsado = 0.0
        hubo_reembolso = False
        for p in o.get("payments") or []:
            v = p.get("transaction_amount_refunded")
            if v:
                reembolsado += float(v)
                hubo_reembolso = True
        items = o.get("order_items") or []
        partidas = []
        for idx, it in enumerate(items):
            item = it.get("item", {})
            q = int(it.get("quantity") or 0)
            unit = float(it.get("unit_price") or 0)
            fee = it.get("sale_fee")
            descuentos = it.get("discounts") or []
            partida = f"{item.get('id')}:{item.get('variation_id') or 0}"
            partidas.append({
                "clave": f"{PLATAFORMA}|{self.cuenta}|{o['id']}|{partida}",
                "plataforma": PLATAFORMA, "cuenta": self.cuenta, "pedido": str(o["id"]), "partida": partida,
                "sku": item.get("seller_sku") or item.get("seller_custom_field"),
                "titulo": item.get("title"), "cantidad": q, "precio_unitario": unit,
                # unit_price ya incluye descuentos; la porción que absorbe el vendedor se concilia con la liquidación.
                "descuento_total": 0.0, "descuento_por_conciliar": bool(descuentos),
                "moneda": it.get("currency_id") or o.get("currency_id"),
                "comision": round(float(fee) * q, 2) if fee is not None else None,
                "comision_fuente": "sale_fee × cantidad (estimada; confirmar con la liquidación)" if fee is not None else None,
                "envio_cobrado": None, "logistica": None,
                # Reembolsos se reportan por pedido; si hay varias partidas se asignan solo a la primera y se marca revisión.
                "reembolsado": (reembolsado if idx == 0 else 0.0) if hubo_reembolso else 0.0,
                "reembolso_multipartida": hubo_reembolso and len(items) > 1,
                "unidades_devueltas": None if hubo_reembolso else 0,
                "estado_plataforma": estado, "clase": clase, "fecha_pedido": fecha,
                "actualizado": o.get("date_last_updated") or o.get("last_updated"),
                "pack_id": o.get("pack_id"), "entrega": "Pendiente",
            })
        return partidas

    def ventana_incremental(self, cursor: str | None, desde_inicial: datetime) -> tuple[datetime, datetime]:
        hasta = ahora_local() - timedelta(minutes=1)
        # La búsqueda de órdenes descarta minutos y segundos: se traslapan 2 horas para no perder
        # cambios. Volver a leer un pedido es inofensivo (la carga es idempotente).
        desde = datetime.fromisoformat(cursor) - timedelta(hours=2) if cursor else desde_inicial
        return desde, hasta
