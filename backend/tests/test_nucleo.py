"""Pruebas del núcleo: ventas/KPIs, asistente con Claude simulado, conectores y API.

Ejecutar desde backend/:  pytest -q
"""
from __future__ import annotations

import os
import re
import tempfile
from decimal import Decimal
from types import SimpleNamespace

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "prueba.db")
os.environ["APP_TOKEN"] = "secreto-de-prueba"
os.environ["ML_CLIENT_ID"] = "123"
os.environ["ML_CLIENT_SECRET"] = "x"
os.environ["SYNC_HABILITADO"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.ia.asistente import Asistente  # noqa: E402
from app.integraciones import amazon, mercadolibre as ml  # noqa: E402
from app.models import OperacionPendiente, TokenIntegracion, Venta, ahora  # noqa: E402
from app.servicios import ventas as sv  # noqa: E402


@pytest.fixture()
def db():
    dbmod.configurar("sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db"))
    dbmod.init_db()
    with dbmod.SessionLocal() as s:
        yield s


# ------------------------------------------------------------------ ventas y KPIs
def test_registro_y_resumen(db):
    sv.registrar_venta(db, {"canal": "Cafeterías", "cantidad": 15, "total_producto": 1000, "fecha": sv.hoy()}, "Casa Monic")
    sv.registrar_venta(db, {"canal": "Mercado Libre", "cantidad": 2, "total_producto": 122, "comision": 20,
                            "costo_logistico": 60, "fecha": sv.hoy()})
    res = sv.resumen(db, sv.rango("mes"))
    assert res["ventas_producto"] == Decimal("1122.00")
    assert res["sobres"] == 17
    ml_fila = next(f for f in res["por_canal"] if f["canal"] == "Mercado Libre")
    assert ml_fila["neto"] == Decimal("42.00")
    assert ml_fila["tipo_contribucion"] == "estimado"
    pe = sv.punto_equilibrio(db)
    assert pe["tipo_dato"] == "estimado" and pe["meta_sobres"] > 0


def test_validaciones(db):
    with pytest.raises(sv.ErrorNegocio):
        sv.registrar_venta(db, {"canal": "Tianguis", "cantidad": 1, "total_producto": 10})
    with pytest.raises(sv.ErrorNegocio):
        sv.registrar_venta(db, {"canal": "Amazon", "cantidad": 0, "total_producto": 10})
    sv.registrar_venta(db, {"canal": "Amazon", "cantidad": 1, "total_producto": 10, "referencia_externa": "A1"})
    with pytest.raises(sv.ErrorNegocio):
        sv.registrar_venta(db, {"canal": "Amazon", "cantidad": 1, "total_producto": 10, "referencia_externa": "A1"})


def test_cliente_tolerante_a_dictado(db):
    sv.obtener_o_crear_cliente(db, "Casa Monic")
    db.commit()
    assert sv.buscar_clientes(db, "casa mónic")[0].nombre == "Casa Monic"
    assert sv.buscar_clientes(db, "Cafetería Casa Monik")[0].nombre == "Casa Monic"


# ------------------------------------------------------------------ asistente con Claude simulado
class ClaudeFalso:
    """Simula Claude: decide herramientas según el texto del usuario y los resultados previos."""

    def __init__(self, confirmar_en_mismo_turno: bool = False):
        self.confirmar_en_mismo_turno = confirmar_en_mismo_turno
        self.messages = self

    def create(self, **kw):
        mensajes, sistema = kw["messages"], kw["system"]
        ultimo = mensajes[-1]
        if isinstance(ultimo["content"], list):  # llegaron tool_results
            res = ultimo["content"][0]["content"]
            if self.confirmar_en_mismo_turno and '"operacion_id"' in res and "confirmar" not in str(mensajes[-2]):
                op = re.search(r'"operacion_id": "([^"]+)"', res).group(1)
                return _tool("confirmar_operacion", {"operacion_id": op}, "t2")
            return SimpleNamespace(stop_reason="end_turn", content=[{"type": "text", "text": "Hecho: " + res}])
        texto = ultimo["content"].lower()
        if "agrega una venta" in texto:
            return _tool("preparar_venta", {"canal": "Cafeterías", "cliente": "Casa Monic", "cantidad": 15,
                                            "monto_total": 1000}, "t1")
        if texto in ("sí", "si", "confirmo"):
            m = re.search(r"id=([0-9a-f-]{36})", sistema)
            if not m:
                return SimpleNamespace(stop_reason="end_turn", content=[{"type": "text", "text": "No hay nada pendiente."}])
            return _tool("confirmar_operacion", {"operacion_id": m.group(1)}, "t3")
        if "cómo van" in texto:
            return _tool("consultar_ventas", {"periodo": "mes", "canal": "Mercado Libre"}, "t4")
        return SimpleNamespace(stop_reason="end_turn", content=[{"type": "text", "text": "¿Puedes repetir?"}])


def _tool(nombre, entrada, id_):
    return SimpleNamespace(stop_reason="tool_use", content=[{"type": "tool_use", "id": id_, "name": nombre, "input": entrada}])


def test_venta_por_voz_en_dos_turnos(db):
    a = Asistente(cliente=ClaudeFalso())
    r1 = a.responder(db, "sesion-coche-1", "Agrega una venta a Cafetería Casa Monic por $1000 pesos de 15 sobres")
    assert r1.pendiente and "15 sobres" in r1.pendiente["resumen"] and "66.67" in r1.pendiente["resumen"]
    assert db.query(Venta).count() == 0  # aún no se escribe
    r2 = a.responder(db, "sesion-coche-1", "sí")
    assert r2.refrescar and r2.pendiente is None
    v = db.query(Venta).one()
    assert (v.canal, v.cantidad, v.total_producto, v.origen) == ("Cafeterías", 15, Decimal("1000.00"), "voz")
    assert v.cliente.nombre == "Casa Monic"


def test_no_confirma_en_el_mismo_turno(db):
    a = Asistente(cliente=ClaudeFalso(confirmar_en_mismo_turno=True))
    r = a.responder(db, "sesion-coche-2", "Agrega una venta a Cafetería Casa Monic por $1000 pesos de 15 sobres")
    assert db.query(Venta).count() == 0
    assert "posterior" in r.texto or r.pendiente


def test_operacion_expirada(db):
    a = Asistente(cliente=ClaudeFalso())
    a.responder(db, "sesion-coche-3", "Agrega una venta a Cafetería Casa Monic por $1000 pesos de 15 sobres")
    op = db.query(OperacionPendiente).one()
    op.expira_en = ahora().replace(year=2020)
    db.commit()
    r = a.responder(db, "sesion-coche-3", "sí")
    assert "No hay nada pendiente" in r.texto
    assert db.query(Venta).count() == 0


def test_consulta_por_voz(db):
    sv.registrar_venta(db, {"canal": "Mercado Libre", "cantidad": 3, "total_producto": 183, "fecha": sv.hoy()})
    r = Asistente(cliente=ClaudeFalso()).responder(db, "sesion-coche-4", "¿Cómo van las ventas de Mercado Libre?")
    assert "183" in r.texto


# ------------------------------------------------------------------ Mercado Libre
ORDEN_ML = {"id": 2000001, "status": "paid", "date_closed": "2026-10-20T15:30:00.000-04:00",
            "order_items": [{"item": {"title": "Guacamole Liofilizado 40g"}, "quantity": 3, "unit_price": 61.0, "sale_fee": 7.5}],
            "shipping": {"id": 444}, "total_amount": 183.0, "currency_id": "MXN"}


def test_mapeo_orden_ml():
    m = ml.mapear_orden(ORDEN_ML, Decimal("45.50"))
    assert (m["cantidad"], m["total_producto"], m["comision"], m["costo_logistico"]) == (3, Decimal("183.0"), Decimal("22.5"), Decimal("45.50"))
    assert m["pendiente_conciliar"] is False
    assert ml.mapear_orden(ORDEN_ML, None)["pendiente_conciliar"] is True


def test_webhook_ml_idempotente_y_verificado(db):
    db.add(TokenIntegracion(proveedor="mercadolibre", cuenta_id="999", access_token="tok", refresh_token="r",
                            expira_en=ahora().replace(year=2100)))
    db.commit()
    base = {"_id": "n1", "resource": "/orders/2000001", "user_id": 999, "topic": "orders_v2", "application_id": 123}
    assert ml.recibir_notificacion(db, {**base, "application_id": 555}) is None   # otra app
    assert ml.recibir_notificacion(db, {**base, "user_id": 1}) is None            # otro vendedor
    eid = ml.recibir_notificacion(db, base)
    assert eid and ml.recibir_notificacion(db, base) is None                      # duplicado

    def responder(req: httpx.Request):
        assert req.headers["authorization"] == "Bearer tok"
        if req.url.path == "/orders/2000001":
            return httpx.Response(200, json=ORDEN_ML)
        if req.url.path == "/shipments/444/costs":
            return httpx.Response(200, json={"senders": [{"cost": 45.5}]})
        return httpx.Response(404)

    http = httpx.Client(base_url=ml.API, transport=httpx.MockTransport(responder))
    ml.procesar_evento(db, eid, http)
    v = db.query(Venta).one()
    assert (v.canal, v.referencia_externa, v.neto) == ("Mercado Libre", "2000001", Decimal("115.00"))
    ml.sincronizar_orden(db, "2000001", http)  # re-sincronizar no duplica
    assert db.query(Venta).count() == 1


# ------------------------------------------------------------------ Amazon
def test_eventos_financieros_amazon():
    eventos = {"ShipmentEventList": [{"ShipmentItemList": [{
        "QuantityShipped": 2,
        "ItemChargeList": [{"ChargeType": "Principal", "ChargeAmount": {"CurrencyAmount": 120.0}},
                           {"ChargeType": "ShippingCharge", "ChargeAmount": {"CurrencyAmount": 40.0}}],
        "ItemFeeList": [{"FeeType": "Commission", "FeeAmount": {"CurrencyAmount": -18.0}},
                        {"FeeType": "FBAPerUnitFulfillmentFee", "FeeAmount": {"CurrencyAmount": -55.0}}]}]}]}
    orden = {"AmazonOrderId": "701-1", "PurchaseDate": "2026-10-19T18:00:00Z", "OrderStatus": "Shipped",
             "NumberOfItemsShipped": 2, "OrderTotal": {"Amount": "160.00"}}
    m = amazon.mapear(orden, eventos)
    assert (m["total_producto"], m["ingreso_envio"], m["comision"], m["costo_logistico"]) == (
        Decimal("120.0"), Decimal("40.0"), Decimal("18.0"), Decimal("55.0"))
    assert amazon.mapear(orden, None)["pendiente_conciliar"] is True


# ------------------------------------------------------------------ API
def test_api_protegida_y_flujo(db):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/salud").json()["ok"]
        assert c.get("/api/kpis").status_code == 401
        h = {"Authorization": "Bearer secreto-de-prueba"}
        r = c.post("/api/ventas", json={"canal": "Cafeterías", "cantidad": 10, "total_producto": 600, "cliente": "La Esquina"}, headers=h)
        assert r.status_code == 201, r.text
        assert c.post("/api/ventas", json={"canal": "Cafeterías", "cantidad": -1, "total_producto": 1}, headers=h).status_code == 422
        k = c.get("/api/kpis?periodo=mes", headers=h).json()
        assert k["resumen"]["sobres"] >= 10
        assert c.post("/integraciones/mercadolibre/webhook", json={"topic": "orders_v2"}).json()["ok"] is True
        assert c.get("/").status_code == 200


# ------------------------------------------------------------------ conector MCP (app de Claude)
def _rpc(c, metodo, params=None, token="secreto-de-prueba", id_=1):
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return c.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params or {}})


def test_conector_mcp_venta_por_voz(db):
    import json as _json
    from datetime import timedelta
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        assert _rpc(c, "tools/list", token=None).status_code == 401
        ini = _rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "prueba", "version": "1"}})
        assert ini.status_code == 200, ini.text
        assert "Legado Verde" in ini.json()["result"]["serverInfo"]["name"]
        nombres = {t["name"] for t in _rpc(c, "tools/list").json()["result"]["tools"]}
        assert {"consultar_ventas", "preparar_venta", "confirmar_venta"} <= nombres

        def llamar(nombre, args):
            r = _rpc(c, "tools/call", {"name": nombre, "arguments": args}).json()["result"]
            return _json.loads(r["content"][0]["text"])

        prep = llamar("preparar_venta", {"canal": "Cafeterías", "cliente": "Casa Monic", "cantidad": 15, "monto_total": 1000})
        assert "66.67" in prep["resumen"]
        op_id = prep["operacion_id"]
        assert "error" in llamar("confirmar_venta", {"operacion_id": op_id, "frase_del_usuario": "sí"})  # demasiado pronto
        with dbmod.SessionLocal() as s:
            op = s.get(OperacionPendiente, op_id)
            op.creada_en = ahora() - timedelta(seconds=10)
            s.commit()
        assert "error" in llamar("confirmar_venta", {"operacion_id": op_id, "frase_del_usuario": "no, espera"})
        ok = llamar("confirmar_venta", {"operacion_id": op_id, "frase_del_usuario": "Sí, confírmala"})
        assert ok.get("ok") is True, ok
        res = llamar("consultar_ventas", {"periodo": "hoy", "canal": "Cafeterías"})
        assert res["sobres"] == 15 and res["ventas_producto"] == 1000.0
