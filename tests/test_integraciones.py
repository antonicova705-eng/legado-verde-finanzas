"""Pruebas de sincronización con APIs SIMULADAS (no hay conexión real a Mercado Libre ni Amazon)."""
import json
import unittest
import urllib.parse
from datetime import datetime

from base import CasoBase

from lv import operaciones as op
from lv.integraciones.amazon import Amazon
from lv.integraciones.estado import ESTADOS_LOCALES as E
from lv.integraciones.estado import Estado
from lv.integraciones.http import ClienteHTTP
from lv.integraciones.mercadolibre import MercadoLibre
from lv.integraciones.sincronizador import Sincronizador
from lv.util import ZONA

CFG_ML = {"ML_CLIENT_ID": "app1", "ML_CLIENT_SECRET": "SECRETO-NO-DEBE-APARECER", "ML_SELLER_ID": "777",
          "ML_REDIRECT_URI": "https://x", "ML_REFRESH_TOKEN": "RT-inicial"}
CFG_AMZ = {"AMZ_LWA_CLIENT_ID": "lwa", "AMZ_LWA_CLIENT_SECRET": "s", "AMZ_REFRESH_TOKEN": "Atzr|x",
           "AMZ_SELLER_ID": "A1SELLER", "AMZ_MARKETPLACE_ID": "A1AM78C64UM0Y8",
           "AMZ_ENDPOINT": "https://sellingpartnerapi-na.amazon.com"}


def orden_ml(oid, status="paid", q=2, precio=61.0, sku="LV-40G", fee=9.15, refunded=None, fecha="2026-10-10T12:00:00.000-06:00"):
    pago = {"id": 1, "status": "approved", "transaction_amount": q * precio}
    if refunded:
        pago["transaction_amount_refunded"] = refunded
    return {"id": oid, "status": status, "date_created": fecha, "date_closed": fecha,
            "date_last_updated": fecha, "currency_id": "MXN",
            "order_items": [{"item": {"id": "MLM1", "title": "Guacamole", "seller_sku": sku, "variation_id": None},
                             "quantity": q, "unit_price": precio, "sale_fee": fee, "currency_id": "MXN"}],
            "payments": [pago]}


class FalsoML:
    """Simula /oauth/token, /orders/search (paginado) y /orders/{id}."""

    def __init__(self, ordenes, fallar_en_offset=None):
        self.ordenes = ordenes
        self.fallar_en_offset = fallar_en_offset
        self.refresh_vigente = "RT-inicial"
        self.llamadas = []

    def solicitar(self, metodo, url, enc, cuerpo, tiempo):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.llamadas.append((metodo, u.path, q))
        if u.path == "/oauth/token":
            f = dict(urllib.parse.parse_qsl(cuerpo.decode()))
            if f.get("refresh_token") != self.refresh_vigente:
                return 400, {}, b'{"error":"invalid_grant"}'
            self.refresh_vigente = "RT-" + str(len(self.llamadas))  # rota
            return 200, {}, json.dumps({"access_token": "AT", "expires_in": 21600, "user_id": 777,
                                        "refresh_token": self.refresh_vigente}).encode()
        assert enc["Authorization"] == "Bearer AT"
        if u.path == "/orders/search":
            off, lim = int(q["offset"]), int(q["limit"])
            if self.fallar_en_offset is not None and off == self.fallar_en_offset:
                return 503, {"Retry-After": "0"}, b"caido"
            base = [o for o in self.ordenes if (o["status"] == "cancelled") == (q.get("order.status") == "cancelled")]
            return 200, {}, json.dumps({"results": base[off:off + lim], "paging": {"total": len(base), "offset": off, "limit": lim}}).encode()
        if u.path.startswith("/orders/"):
            oid = int(u.path.split("/")[-1])
            o = next(o for o in self.ordenes if o["id"] == oid)
            return 200, {}, json.dumps(o).encode()
        return 404, {}, b""


class PruebasIntegraciones(CasoBase):
    def setUp(self):
        super().setUp()
        self.estado = Estado(self.integ)

        def conf(d):
            d["config"]["skus"] = {"LV-40G": "Sobre individual"}
        self.repo.transaccion(conf)

    def sinc_ml(self, falso):
        http = ClienteHTTP(falso, intentos=2, dormir=lambda s: None)
        ml = MercadoLibre(self.estado, http, CFG_ML)
        self.estado.cuenta(ml.plataforma, ml.cuenta)
        return Sincronizador(self.repo, self.estado, [ml])

    def ventas_ml(self):
        return [r for r in self.datos()["operaciones"] if r.get("Origen") == "Mercado Libre"]

    def test_inicial_paginada_idempotente_y_estados(self):
        ordenes = [orden_ml(1000 + i) for i in range(60)] + [orden_ml(2001, status="payment_in_process"),
                                                              orden_ml(2002, status="cancelled")]
        falso = FalsoML(ordenes)
        s = self.sinc_ml(falso)
        r = s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual(r["estado"], "Correcta", r)
        self.assertEqual(r["incorporados"], 60)
        self.assertGreaterEqual(r["paginas"], 3)  # 2 páginas de 50 + página de cancelados
        v = self.ventas_ml()
        self.assertEqual(len(v), 60)
        self.assertEqual(v[0]["Cantidad"], 2)
        self.assertEqual(v[0]["Fecha"], "2026-10-10")
        self.assertFalse(v[0]["Comisiones confirmadas"])  # estimada desde sale_fee
        self.assertEqual(v[0]["Liquidación"], "Pendiente")
        self.assertEqual(self.datos()["asientos"], [])  # pagado ≠ depósito: sin cobros
        res = self.estado.resumen()
        self.assertEqual(res[E["PENDIENTE"]], 1)
        self.assertEqual(res[E["CANCELADO"]], 1)
        # repetir: nada nuevo
        r2 = s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual((r2["nuevos"], r2["cambios"]), (0, 0))
        self.assertEqual(len(self.ventas_ml()), 60)
        # el refresh token rotó y quedó guardado; los secretos no aparecen en la bitácora
        self.assertNotEqual(self.estado.token("Mercado Libre", "777")["refresh_token"], "RT-inicial")
        self.assertNotIn("SECRETO", json.dumps(self.estado.corridas(), default=str))

    def test_cambios_reembolso_cancelacion_y_costo_preservado(self):
        o = orden_ml(5000)
        falso = FalsoML([o])
        s = self.sinc_ml(falso)
        s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        v = self.ventas_ml()[0]
        # el usuario confirma el costo (campo interno)
        self.repo.transaccion(lambda d: op.por_id(d, v["ID"]).update({"Costo de ventas": 50.0, "Costo confirmado": True}))
        o.update(status="partially_refunded", date_last_updated="2026-10-12T10:00:00.000-06:00")
        o["payments"][0]["transaction_amount_refunded"] = 61.0
        r = s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual(r["cambios"], 1)
        v2 = op.por_id(self.datos(), v["ID"])
        self.assertEqual(v2["Devolución"], 61.0)
        self.assertIsNone(v2["Sobres devueltos"])  # unidades devueltas: desconocidas
        self.assertEqual(v2["Costo de ventas"], 50.0)
        self.assertTrue(v2["Costo confirmado"])
        o.update(status="cancelled", date_last_updated="2026-10-13T10:00:00.000-06:00")
        s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        v3 = op.por_id(self.datos(), v["ID"])
        self.assertTrue(v3["Anulada"])
        self.assertEqual(v3["Motivo anulación"], "Cancelada en plataforma")
        self.assertEqual(len(self.ventas_ml()), 1)

    def test_edicion_manual_genera_conflicto(self):
        o = orden_ml(6000)
        falso = FalsoML([o])
        s = self.sinc_ml(falso)
        s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        v = self.ventas_ml()[0]
        self.repo.transaccion(lambda d: op.por_id(d, v["ID"]).update({"Descuento": 10.0}))
        o.update(quantity=3, date_last_updated="2026-10-14T10:00:00.000-06:00")
        o["order_items"][0]["quantity"] = 3
        s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        v2 = op.por_id(self.datos(), v["ID"])
        self.assertEqual(v2["Cantidad"], 2)  # no se sobrescribió
        self.assertEqual(v2["Descuento"], 10.0)
        self.assertEqual(self.estado.resumen().get(E["REV_CONFLICTO"]), 1)

    def test_interrupcion_y_recuperacion(self):
        ordenes = [orden_ml(7000 + i) for i in range(70)]
        falso = FalsoML(ordenes, fallar_en_offset=50)
        s = self.sinc_ml(falso)
        r = s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual(r["estado"], "Error")
        self.assertIsNone(self.estado.cuenta("Mercado Libre", "777")["cursor"])  # no avanzó
        parciales = len(self.ventas_ml())
        self.assertLessEqual(parciales, 50)
        falso.fallar_en_offset = None
        r = s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual(r["estado"], "Correcta")
        self.assertEqual(len(self.ventas_ml()), 70)
        ids = [x["ID"] for x in self.ventas_ml()]
        self.assertEqual(len(ids), len(set(ids)))
        # incremental posterior usa el cursor y no duplica
        r = s.sincronizar("Mercado Libre")
        self.assertEqual(r["estado"], "Correcta")
        self.assertEqual(len(self.ventas_ml()), 70)

    def test_posible_duplicado_con_captura_manual_y_vinculacion(self):
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(canal="Mercado Libre", fecha="2026-10-11",
                                                                            presentaciones=2, precio_presentacion=61.0)))
        falso = FalsoML([orden_ml(8000)])
        s = self.sinc_ml(falso)
        s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual(self.ventas_ml(), [])
        rev = self.estado.pedidos([E["REV_DUP"]])
        self.assertEqual(len(rev), 1)
        manual = next(r for r in self.datos()["operaciones"] if r.get("Canal") == "Mercado Libre" and r.get("Fecha"))
        self.estado.decidir(rev[0]["clave"], "vincular", manual["ID"])
        s.incorporar()
        d = self.datos()
        activos_ml = [r for r in d["operaciones"] if r.get("Canal") == "Mercado Libre" and r.get("Fecha") and not r.get("Anulada")]
        self.assertEqual(len(activos_ml), 1)
        self.assertEqual(activos_ml[0]["Origen pedido"], "8000")

    def test_sku_sin_mapear(self):
        falso = FalsoML([orden_ml(9000, sku="PAQ-3")])
        s = self.sinc_ml(falso)
        s.sincronizar("Mercado Libre", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual(self.estado.resumen().get(E["REV_SKU"]), 1)

        def conf(d):
            d["config"]["presentaciones"].append({"Nombre": "Paquete 3", "Sobres": 3})
            d["config"]["skus"]["PAQ-3"] = "Paquete 3"
        self.repo.transaccion(conf)
        s.incorporar()
        v = self.ventas_ml()[0]
        self.assertEqual((v["Presentaciones"], v["Cantidad"]), (2, 6))

    def test_notificacion_webhook(self):
        import webhook_ml
        o = orden_ml(9100)
        falso = FalsoML([o])
        s = self.sinc_ml(falso)
        self.assertFalse(webhook_ml.aceptar({"topic": "orders_v2", "resource": "/orders/9100", "application_id": "otra",
                                             "user_id": 777}, self.estado, "app1", "777"))
        self.assertTrue(webhook_ml.aceptar({"topic": "orders_v2", "resource": "/orders/9100", "application_id": "app1",
                                            "user_id": 777}, self.estado, "app1", "777"))
        r = s.procesar_cola()
        self.assertEqual(r["incorporados"], 1)
        self.assertEqual(len(self.ventas_ml()), 1)


class FalsoAmazon:
    def __init__(self):
        self.esperas = []

    def solicitar(self, metodo, url, enc, cuerpo, tiempo):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.netloc == "api.amazon.com":
            return 200, {}, json.dumps({"access_token": "Atza|AT", "expires_in": 3600}).encode()
        assert enc["x-amz-access-token"] == "Atza|AT"
        if u.path == "/orders/2026-01-01/orders":
            def orden(i, st):
                return {"orderId": f"702-{i}", "createdTime": "2026-10-05T18:00:00Z", "lastUpdatedTime": "2026-10-06T18:00:00Z",
                        "fulfillment": {"fulfillmentStatus": st},
                        "orderItems": [{"orderItemId": f"OI{i}", "quantityOrdered": 1,
                                        "product": {"sellerSku": "LV-40G", "price": {"unitPrice": {"amount": "60.00", "currencyCode": "MXN"}}}}]}
            if "paginationToken" not in q:
                return 200, {}, json.dumps({"orders": [orden(1, "SHIPPED"), orden(2, "PENDING")], "pagination": {"nextToken": "T2"}}).encode()
            return 200, {}, json.dumps({"orders": [orden(3, "CANCELLED")]}).encode()
        if u.path.startswith("/finances/v0/orders/"):
            return 200, {}, json.dumps({"payload": {"FinancialEvents": {"ShipmentEventList": [{"ShipmentItemList": [
                {"SellerSKU": "LV-40G", "QuantityShipped": 1,
                 "ItemFeeList": [{"FeeType": "Commission", "FeeAmount": {"CurrencyCode": "MXN", "CurrencyAmount": -9.0}},
                                 {"FeeType": "FBAPerUnitFulfillmentFee", "FeeAmount": {"CurrencyCode": "MXN", "CurrencyAmount": -45.0}}]}]}]}}}).encode()
        return 404, {}, b""


class PruebasAmazon(CasoBase):
    def test_amazon_paginacion_finanzas_y_ritmo(self):
        def conf(d):
            d["config"]["skus"] = {"LV-40G": "Sobre individual"}
        self.repo.transaccion(conf)
        estado = Estado(self.integ)
        falso = FalsoAmazon()
        esperas = []
        amz = Amazon(estado, ClienteHTTP(falso, dormir=lambda s: None), CFG_AMZ, dormir=esperas.append)
        estado.cuenta("Amazon", amz.cuenta)
        s = Sincronizador(self.repo, estado, [amz])
        r = s.sincronizar("Amazon", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual(r["estado"], "Correcta", r)
        ventas = [x for x in self.datos()["operaciones"] if x.get("Origen") == "Amazon"]
        self.assertEqual(len(ventas), 1)
        self.assertEqual(ventas[0]["Comisiones"], 54.0)
        self.assertEqual(ventas[0]["Fecha"], "2026-10-05")  # 18:00Z = 12:00 en CDMX
        self.assertEqual(estado.resumen()[E["PENDIENTE"]], 1)
        self.assertEqual(estado.resumen()[E["CANCELADO"]], 1)
        # repetir no duplica
        s.sincronizar("Amazon", datetime(2026, 7, 1, tzinfo=ZONA), tipo="inicial")
        self.assertEqual(len([x for x in self.datos()["operaciones"] if x.get("Origen") == "Amazon"]), 1)


if __name__ == "__main__":
    unittest.main()
