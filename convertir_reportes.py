"""Convierte reportes descargados de Mercado Libre y Amazon al formato de importación.

    python convertir_reportes.py --ml Ventas_MX.xlsx --amazon CustomTransaction.csv \
        --ml-presentacion MLM3140406273="Paquete de 10":10 \
        --ml-presentacion MLM5724280904="Sobre individual":1 \
        --costo-sobre 45 --salida ventas_plataformas.json

Reglas:
* Una venta por pedido. Folio = número de pedido; clave = plataforma + pedido (no se duplica al reimportar).
* Se omiten ventas canceladas o anuladas por la plataforma.
* Mercado Libre: «Cargo por venta e impuestos» → comisiones (incluye retenciones; se anota).
  «Costos de envío» → logística. «Total» → remanente reportado.
* Amazon (transacciones de liquidación): fila «Pedido» → venta, crédito de envío y tarifa de venta;
  filas «Tarifas de Amazon» del mismo pedido → logística (Easy Ship y su reversión).
  Transferencias, publicidad y ajustes no son ventas: se resumen aparte.
* No se incluyen nombres, direcciones ni datos fiscales de compradores.
* No se generan cobros: un depósito de plataforma cubre varias ventas y se concilia aparte.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

MESES_ES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
            "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
MES_CORTO = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "oct": 10,
             "nov": 11, "dic": 12}
CDMX = timezone(timedelta(hours=-6))  # México centro no aplica horario de verano desde 2022


def _num(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip().replace(",", "")
    return float(v) if v else 0.0


def fecha_ml(texto: str) -> str:
    m = re.match(r"(\d{1,2}) de (\w+) de (\d{4})", texto.strip())
    if not m:
        raise ValueError(f"Fecha de Mercado Libre no reconocida: {texto!r}")
    return f"{int(m.group(3)):04d}-{MESES_ES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def fecha_amazon(texto: str) -> str:
    m = re.match(r"(\d{1,2}) (\w{3})\w* (\d{4}) (\d{1,2}):(\d{2}):(\d{2}) ([ap])\.?\s?m\.? GMT([+-]\d+)", texto.strip(), re.I)
    if not m:
        raise ValueError(f"Fecha de Amazon no reconocida: {texto!r}")
    d, mes, y, h, mi, se, ap, tz = m.groups()
    h = int(h) % 12 + (12 if ap.lower() == "p" else 0)
    dt = datetime(int(y), MES_CORTO[mes.lower()], int(d), h, int(mi), int(se), tzinfo=timezone(timedelta(hours=int(tz))))
    return dt.astimezone(CDMX).date().isoformat()


def ventas_ml(ruta: str, presentaciones: dict[str, tuple[str, int]], costo_sobre: float | None) -> list[dict]:
    import openpyxl
    ws = openpyxl.load_workbook(ruta, data_only=True, read_only=True).active
    filas = list(ws.iter_rows(values_only=True))
    i_enc = next(i for i, f in enumerate(filas) if f and f[0] == "# de venta")
    enc = list(filas[i_enc])

    def col(nombre, desde=0):
        return enc.index(nombre, desde)
    c = {k: col(k) for k in ["# de venta", "Fecha de venta", "Estado", "Unidades", "Ingresos por productos (MXN)",
                             "Cargo por venta e impuestos (MXN)", "Ingresos por envío (MXN)", "Costos de envío (MXN)",
                             "Anulaciones y reembolsos (MXN)", "Total (MXN)", "# de publicación",
                             "Precio unitario de venta de la publicación (MXN)"]}
    salida = []
    for f in filas[i_enc + 1:]:
        if not f or not f[0]:
            continue
        estado = str(f[c["Estado"]] or "")
        if "cancel" in estado.lower() or "anul" in estado.lower():
            continue
        pub = str(f[c["# de publicación"]]).strip()
        if pub not in presentaciones:
            raise ValueError(f"Publicación {pub} sin presentación asignada (usa --ml-presentacion).")
        nombre, sobres = presentaciones[pub]
        unidades = int(_num(f[c["Unidades"]]))
        ingresos = _num(f[c["Ingresos por productos (MXN)"]])
        reembolso = -_num(f[c["Anulaciones y reembolsos (MXN)"]])
        salida.append({
            "clave": f"ml-{f[c['# de venta']]}", "fecha": fecha_ml(str(f[c["Fecha de venta"]])),
            "canal": "Mercado Libre", "referencia": str(f[c["# de venta"]]), "cliente": None,
            "producto": "Guacamole Liofilizado 40g", "sku": pub,
            "presentacion": nombre, "sobres_por_presentacion": sobres, "presentaciones": unidades,
            "precio_presentacion": round(ingresos / unidades, 2) if unidades else _num(f[c["Precio unitario de venta de la publicación (MXN)"]]),
            "descuento": 0, "devolucion": reembolso, "sobres_devueltos": 0 if not reembolso else None,
            "envio": _num(f[c["Ingresos por envío (MXN)"]]),
            "comisiones": round(-_num(f[c["Cargo por venta e impuestos (MXN)"]]), 2),
            "logistica": round(-_num(f[c["Costos de envío (MXN)"]]), 2),
            "costo": round(costo_sobre * sobres * unidades, 2) if costo_sobre is not None else None,
            "costo_confirmado": costo_sobre is not None,
            "remanente": _num(f[c["Total (MXN)"]]),
            "estado": "Entregado" if "entreg" in estado.lower() else "En Camino",
            "notas": f"Reporte de ventas de Mercado Libre ({estado}). Comisiones incluyen impuestos retenidos; "
                     f"separarlos con el reporte de facturación. Publicación {pub}.",
            "cobro": None,
        })
    return salida


def ventas_amazon(ruta: str, presentacion: tuple[str, int], costo_sobre: float | None) -> tuple[list[dict], dict]:
    texto = Path(ruta).read_text(encoding="utf-8-sig")
    lineas = texto.splitlines()
    i = next(i for i, l in enumerate(lineas) if l.startswith('"fecha/hora"'))
    filas = list(csv.DictReader(io.StringIO("\n".join(lineas[i:]))))
    pedidos: dict[str, dict] = {}
    otros = {"Transferencias a tu banco": 0.0, "Publicidad y servicios": 0.0, "Ajustes": 0.0, "Otros": 0.0}
    for f in filas:
        tipo, pid = f["tipo"], f["Id. del pedido"]
        if tipo == "Pedido":
            p = pedidos.setdefault(pid, {"logistica": 0.0})
            p.update(fecha=fecha_amazon(f["fecha/hora"]), unidades=int(_num(f["cantidad"])),
                     ventas=_num(f["ventas de productos"]), envio=_num(f["créditos de envío"]),
                     descuento=-_num(f["descuentos promocionales"]), tarifa=-_num(f["tarifas de venta"]) - _num(f["tarifas fba"]),
                     sku=f["sku"], total=_num(f["total"]))
        elif tipo == "Tarifas de Amazon" and pid:
            pedidos.setdefault(pid, {"logistica": 0.0})["logistica"] += -_num(f["total"])
        elif tipo == "Reembolso" and pid:
            p = pedidos.setdefault(pid, {"logistica": 0.0})
            p["reembolso"] = p.get("reembolso", 0.0) - _num(f["ventas de productos"])
        elif tipo == "Trasferir" or tipo == "Transferir":
            otros["Transferencias a tu banco"] += -_num(f["total"])
        elif tipo == "Tarifa de servicio":
            otros["Publicidad y servicios"] += -_num(f["total"])
        elif tipo == "Ajuste":
            otros["Ajustes"] += -_num(f["total"])
        else:
            otros["Otros"] += -_num(f["total"])
    nombre, sobres = presentacion
    salida = []
    for pid, p in pedidos.items():
        if "fecha" not in p:
            continue  # tarifas de un pedido fuera del rango del reporte
        u = p["unidades"]
        salida.append({
            "clave": f"amz-{pid}", "fecha": p["fecha"], "canal": "Amazon", "referencia": pid, "cliente": None,
            "producto": "Guacamole Liofilizado 40g", "sku": p["sku"], "presentacion": nombre,
            "sobres_por_presentacion": sobres, "presentaciones": u,
            "precio_presentacion": round(p["ventas"] / u, 2), "descuento": round(p["descuento"], 2),
            "devolucion": round(p.get("reembolso", 0.0), 2), "sobres_devueltos": 0 if not p.get("reembolso") else None,
            "envio": round(p["envio"], 2), "comisiones": round(p["tarifa"], 2) + 0.0, "logistica": round(p["logistica"], 2),
            "costo": round(costo_sobre * sobres * u, 2) if costo_sobre is not None else None,
            "costo_confirmado": costo_sobre is not None, "remanente": round(p["total"] - p["logistica"], 2),
            "estado": "Entregado",
            "notas": "Reporte de transacciones de Amazon; fecha = publicación de la transacción (hora de CDMX). "
                     "Logística = cargo Easy Ship y reversión del crédito de envío.",
            "cobro": None,
        })
    return salida, {k: round(v, 2) for k, v in otros.items()}


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--ml")
    a.add_argument("--amazon")
    a.add_argument("--ml-presentacion", action="append", default=[], help='PUBLICACION="Nombre":SOBRES')
    a.add_argument("--amazon-presentacion", default="Sobre individual:1")
    a.add_argument("--costo-sobre", type=float)
    a.add_argument("--salida", default="ventas_plataformas.json")
    x = a.parse_args(argv)
    pres = {}
    for p in x.ml_presentacion:
        pub, resto = p.split("=", 1)
        nombre, sobres = resto.rsplit(":", 1)
        pres[pub.strip()] = (nombre.strip().strip('"'), int(sobres))
    ventas, otros = [], {}
    if x.ml:
        ventas += ventas_ml(x.ml, pres, x.costo_sobre)
    if x.amazon:
        n, s = x.amazon_presentacion.rsplit(":", 1)
        va, otros = ventas_amazon(x.amazon, (n, int(s)), x.costo_sobre)
        ventas += va
    ventas.sort(key=lambda v: (v["fecha"], v["canal"]))
    doc = {"formato": "legado-verde-ventas", "version": 1, "generado_por": "convertir_reportes.py",
           "movimientos_no_venta_amazon": otros, "ventas": ventas}
    Path(x.salida).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(ventas)} ventas → {x.salida}")
    if otros:
        print("Amazon, movimientos que no son ventas:", otros)


if __name__ == "__main__":
    main()
