"""Importa el histórico a la nueva base sin inventar fechas.

Uso (desde backend/):
  python -m scripts.importar_historico --respaldo respaldo_legado_verde.json   # respaldo de la app Streamlit
  python -m scripts.importar_historico --historico-base                        # registros reportados jul–oct 2026

Reglas:
- Los registros sin fecha exacta se guardan con fecha=None y su etiqueta en mes_reportado.
- otros_cargos = deducciones de la plataforma no explicadas por comisión/logística, para que el
  neto coincida con el remanente reportado; si existen, la venta queda pendiente_conciliar.
- Idempotente: usa (canal, referencia) como llave.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal

from app import db as dbmod
from app.models import CANALES, Venta
from app.servicios import ventas as sv

HISTORICO_BASE = [
    {"Mes": "Julio 2026", "Canal": "Mercado Libre", "Referencia": "ML-JUL-01", "Cantidad": 22, "Ventas Producto": 1341.0, "Remanente": 450.90, "Ingresos Envío": 0.0, "Comisiones": 150.0, "Costos Logísticos": 0.0},
    {"Mes": "Agosto 2026", "Canal": "Mercado Libre", "Referencia": "ML-AGO-01", "Cantidad": 17, "Ventas Producto": 1044.0, "Remanente": 538.88, "Ingresos Envío": 0.0, "Comisiones": 120.0, "Costos Logísticos": 0.0},
    {"Mes": "Septiembre 2026", "Canal": "Mercado Libre", "Referencia": "ML-SEP-01", "Cantidad": 22, "Ventas Producto": 1342.0, "Remanente": 873.92, "Ingresos Envío": 0.0, "Comisiones": 150.0, "Costos Logísticos": 0.0},
    {"Mes": "Octubre 2026 (Parcial)", "Canal": "Mercado Libre", "Referencia": "ML-OCT-01", "Cantidad": 15, "Ventas Producto": 895.0, "Remanente": 638.40, "Ingresos Envío": 0.0, "Comisiones": 95.0, "Costos Logísticos": 0.0},
    {"Mes": "Julio - Sept 2026", "Canal": "Amazon", "Referencia": "AMZ-RESUMEN", "Cantidad": 7, "Ventas Producto": 420.0, "Remanente": -75.67, "Ingresos Envío": 264.18, "Comisiones": 382.93, "Costos Logísticos": 30.15},
    {"Mes": "Pendiente de Fechar", "Canal": "Cafeterías", "Referencia": "CAF-LOTE-1", "Cantidad": 250, "Ventas Producto": 15000.0, "Remanente": 15000.0, "Ingresos Envío": 0.0, "Comisiones": 0.0, "Costos Logísticos": 0.0},
]
RENOMBRAR = {"Tienda en línea (Shopify)": "Tienda en línea", "Otros canales": "Otros"}


def convertir(r: dict) -> dict | None:
    if r.get("Anulada") or r.get("Estado") == "Cancelado":
        return None
    canal = RENOMBRAR.get(r["Canal"], r["Canal"])
    canal = canal if canal in CANALES else "Otros"
    venta = Decimal(str(r["Ventas Producto"])) - Decimal(str(r.get("Descuento", 0))) - Decimal(str(r.get("Devolución", 0)))
    envio, com, log = (Decimal(str(r.get(k, 0) or 0)) for k in ("Ingresos Envío", "Comisiones", "Costos Logísticos"))
    remanente = Decimal(str(r.get("Remanente", venta + envio - com - log)))
    otros = venta + envio - com - log - remanente
    datos = {
        "canal": canal, "referencia_externa": r.get("Referencia") or r.get("ID"), "cantidad": int(r["Cantidad"]),
        "total_producto": venta, "ingreso_envio": envio, "comision": com, "costo_logistico": log,
        "otros_cargos": max(otros, Decimal(0)), "fecha": r.get("Fecha") if r.get("Fecha confirmada") else None,
        "mes_reportado": r.get("Mes"), "origen": "importacion", "pendiente_conciliar": otros > Decimal("0.01"),
        "notas": "Importado del sistema anterior" + (f"; ajuste reportado {r['Ajustes']}" if r.get("Ajustes") else ""),
    }
    if otros < 0:
        datos["notas"] += f"; remanente mayor al calculado por {-otros}"
    return datos


def importar(registros: list[dict]) -> tuple[int, int]:
    dbmod.init_db()
    nuevos = actualizados = 0
    with dbmod.SessionLocal() as db:
        for r in registros:
            datos = convertir(r)
            if not datos:
                continue
            existe = db.query(Venta).filter_by(canal=datos["canal"], referencia_externa=datos["referencia_externa"]).first()
            venta, creada = sv.upsert_externa(db, datos)
            if r.get("Costo confirmado") and r.get("Costo de ventas") is not None:
                venta.costo_producto, venta.costo_confirmado = Decimal(str(r["Costo de ventas"])), True
                db.commit()
            nuevos += int(creada and not existe)
            actualizados += int(bool(existe))
    return nuevos, actualizados


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--respaldo", help="JSON exportado desde la app Streamlit (Respaldo completo)")
    p.add_argument("--historico-base", action="store_true")
    a = p.parse_args()
    if a.respaldo:
        with open(a.respaldo, encoding="utf-8") as f:
            regs = json.load(f)["operaciones"]
    elif a.historico_base:
        regs = HISTORICO_BASE
    else:
        p.error("Indica --respaldo o --historico-base")
    n, u = importar(regs)
    print(f"Importación terminada: {n} nuevas, {u} actualizadas.")
