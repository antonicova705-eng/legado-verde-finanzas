"""Indicadores comerciales, pendientes, serie mensual y simulador (sin Streamlit).

Los estados financieros (EBITDA, utilidad, flujo, balance, punto de equilibrio)
siguen calculándose en ``motor.reporte`` y ``motor.calculo_pe``.
"""
from __future__ import annotations

import importlib
from datetime import date

from . import operaciones as op
from .modelo import importes, pendientes_de_venta
from .util import MESES, fin_de_mes, hoy_local


def _m():
    return importlib.import_module("motor")


def ventas_periodo(datos, inicio, fin, canal=None):
    m = _m()
    return [r for r in datos["operaciones"] if m.en_periodo(r, inicio, fin) and (not canal or r.get("Canal") == canal)]


def ventas_incompletas(datos: dict, inicio: str, fin: str) -> list[str]:
    """Ventas del periodo sin costo, comisión o logística confirmados.

    Las comisiones o logística pendientes se guardan en 0 para el motor; si se
    mostrara EBITDA con ellas, quedaría sobrestimado. Por eso se ocultan.
    """
    return [r["ID"] for r in ventas_periodo(datos, inicio, fin)
            if not r.get("Costo confirmado") or not r.get("Comisiones confirmadas", True)
            or not r.get("Logística confirmada", True)]


def comerciales(datos: dict, inicio: str, fin: str, canal: str | None = None) -> dict:
    ops = ventas_periodo(datos, inicio, fin, canal)
    imp = [importes(r) for r in ops]
    sobres = sum(i["sobres"] or 0 for i in imp)
    devueltos_desconocidos = sum(1 for i in imp if i["sobres_devueltos"] is None)
    margen_pend = sum(1 for i in imp if i["margen_contribucion"] is None)
    netas = sum(i["venta_neta_producto"] for i in imp)
    totales = sum(i["ventas_netas_totales"] for i in imp)
    cobrado = sum(op.cobrado_neto(datos, r["ID"]) for r in ops)
    return {
        "ventas": len(ops),
        "venta_neta_producto": netas,
        "ventas_netas_totales": totales,
        "ingreso_envio": sum(i["ingreso_envio"] for i in imp),
        "sobres": sobres,
        "sobres_netos": None if devueltos_desconocidos else sobres - sum(i["sobres_devueltos"] for i in imp),
        "devueltos_desconocidos": devueltos_desconocidos,
        "ticket": (netas / len(ops)) if ops else None,
        "margen_contribucion": None if (margen_pend or not ops) else sum(i["margen_contribucion"] for i in imp),
        "margen_pendientes": margen_pend,
        "cobrado": cobrado,
        "por_cobrar": totales - cobrado,
        "por_canal": _por_canal(ops),
    }


def _por_canal(ops):
    out = {}
    for r in ops:
        out[r["Canal"]] = out.get(r["Canal"], 0.0) + importes(r)["venta_neta_producto"]
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def cobertura_completa(datos, inicio, fin) -> bool:
    return any(c["Inicio"] <= inicio and c["Fin"] >= fin for c in datos.get("cobertura", []))


def pendientes(datos: dict, inicio: str, fin: str) -> list[dict]:
    """Lista de información faltante, con su efecto en los reportes."""
    m = _m()
    out = []

    def agregar(tema, ids, efecto):
        if ids:
            out.append({"Tema": tema, "Registros": len(ids), "IDs": ", ".join(map(str, ids[:12])) + (" …" if len(ids) > 12 else ""),
                        "Efecto": efecto})
    activos = [r for r in datos["operaciones"] if m.activo(r)]
    agregar("Ventas sin fecha exacta", [r["ID"] for r in activos if not r.get("Fecha")],
            "Excluidas de todos los reportes. Los resúmenes heredados deben desglosarse y luego anularse.")
    periodo = [r for r in activos if m.en_periodo(r, inicio, fin)]
    agregar("Costo de ventas sin confirmar", [r["ID"] for r in periodo if not r.get("Costo confirmado")],
            "Margen, utilidad bruta, EBITDA y utilidad neta aparecen como «No disponible».")
    agregar("Comisiones sin confirmar", [r["ID"] for r in periodo if not r.get("Comisiones confirmadas", True)],
            "El margen de contribución por venta no se calcula.")
    agregar("Logística sin confirmar", [r["ID"] for r in periodo if not r.get("Logística confirmada", True)],
            "El margen de contribución por venta no se calcula.")
    agregar("Sobres devueltos desconocidos", [r["ID"] for r in periodo if r.get("Sobres devueltos") is None],
            "Los sobres netos vendidos no se calculan.")
    agregar("Liquidación de plataforma pendiente", [r["ID"] for r in periodo if r.get("Liquidación") == "Pendiente"],
            "Un pedido pagado no es un depósito: el efectivo se registra al conciliar la liquidación.")
    agregar("Ajustes heredados sin clasificar", [r["ID"] for r in periodo if r.get("Ajustes")],
            "Requieren clasificación contable.")
    sin_ref = [a.get("Referencia") for a in datos.get("asientos", [])
               if not a.get("Anulada") and a.get("Referencia pendiente") and inicio <= a.get("Fecha", "") <= fin]
    agregar("Cobros sin referencia bancaria", sin_ref, "El efectivo cuenta, pero falta el comprobante para conciliar.")
    if not datos.get("apertura_confirmada"):
        out.append({"Tema": "Balance de apertura", "Registros": 1, "IDs": "",
                    "Efecto": "Saldos de efectivo y situación financiera incompletos."})
    if not cobertura_completa(datos, inicio, fin):
        out.append({"Tema": "Cobertura del periodo sin confirmar", "Registros": 1, "IDs": f"{inicio} a {fin}",
                    "Efecto": "Los reportes del periodo son preliminares."})
    return out


def serie_mensual(datos: dict, anio: int) -> list[dict]:
    """Ventas netas de producto por mes. Variación solo entre meses completos y confirmados."""
    m = _m()
    filas, anterior = [], None
    hoy = hoy_local()
    for mes in range(1, 13):
        ini = date(anio, mes, 1).isoformat()
        fin = fin_de_mes(anio, mes).isoformat()
        ops = [r for r in datos["operaciones"] if m.en_periodo(r, ini, fin)]
        v = sum(importes(r)["venta_neta_producto"] for r in ops)
        completo = cobertura_completa(datos, ini, fin) and date.fromisoformat(fin) < hoy
        mostrado = v if (ops or completo) else None
        variacion = None
        if anterior and anterior["Completo"] and completo and anterior["Ventas netas MXN"]:
            variacion = (v / anterior["Ventas netas MXN"] - 1) * 100
        fila = {"Mes": MESES[mes - 1], "Ventas netas MXN": mostrado,
                "Variación %": variacion, "Estado": "Completo" if completo else "Parcial o sin confirmar",
                "Completo": completo}
        filas.append(fila)
        anterior = fila
    return filas


def promedios_por_canal(datos: dict) -> dict:
    """Supuestos históricos por canal: precio por sobre y % de comisión (solo con datos confirmados)."""
    m = _m()
    acum = {}
    for r in datos["operaciones"]:
        if not m.activo(r) or not r.get("Fecha"):
            continue
        a = acum.setdefault(r["Canal"], {"sobres": 0, "neta": 0.0, "com": 0.0, "neta_com": 0.0, "log": 0.0})
        i = importes(r)
        a["sobres"] += r.get("Cantidad") or 0
        a["neta"] += i["venta_neta_producto"]
        if r.get("Comisiones confirmadas", True):
            a["com"] += i["comisiones"] or 0
            a["neta_com"] += i["venta_neta_producto"]
        if r.get("Logística confirmada", True):
            a["log"] += i["logistica"] or 0
    out = {}
    for c, a in acum.items():
        out[c] = {"precio": a["neta"] / a["sobres"] if a["sobres"] else None,
                  "comision_pct": (a["com"] / a["neta_com"] * 100) if a["neta_com"] else None,
                  "logistica_sobre": a["log"] / a["sobres"] if a["sobres"] else None}
    return out


def simular(volumen: float, costo_variable: float, fijos: float, mezcla: list[dict]) -> dict:
    """Proyección mensual. ``mezcla``: [{Canal, % volumen, Precio por sobre, Comisión %, Logística por sobre}]."""
    total_pct = sum(float(x.get("% volumen") or 0) for x in mezcla)
    if total_pct <= 0:
        raise ValueError("Asigna porcentaje de volumen al menos a un canal.")
    filas = []
    for x in mezcla:
        pct = float(x.get("% volumen") or 0) / total_pct
        if pct <= 0:
            continue
        sobres = volumen * pct
        precio = float(x.get("Precio por sobre") or 0)
        ventas = sobres * precio
        com = ventas * float(x.get("Comisión %") or 0) / 100
        log = sobres * float(x.get("Logística por sobre") or 0)
        cv = sobres * costo_variable
        filas.append({"Canal": x["Canal"], "Sobres": sobres, "Ventas": ventas, "Costo variable": cv,
                      "Comisiones": com, "Logística": log, "Contribución": ventas - cv - com - log})
    ventas = sum(f["Ventas"] for f in filas)
    contrib = sum(f["Contribución"] for f in filas)
    margen = contrib / ventas if ventas else None
    contrib_sobre = contrib / volumen if volumen else None
    return {"filas": filas, "ventas": ventas, "contribucion": contrib, "margen": margen, "fijos": fijos,
            "resultado": contrib - fijos,
            "pe_sobres": (fijos / contrib_sobre) if contrib_sobre and contrib_sobre > 0 else None,
            "pe_ventas": (fijos / margen) if margen and margen > 0 else None}


def historico_reportado(datos: dict) -> list[dict]:
    """Cifras heredadas SIN fecha exacta ni verificación (resúmenes previos al sistema).

    Se muestran aparte para dar contexto; no entran a estados financieros ni a
    indicadores del periodo hasta que se fechen o se desglosen.
    """
    m = _m()
    filas = []
    for r in datos["operaciones"]:
        if not m.activo(r) or r.get("Fecha"):
            continue
        filas.append({"Periodo reportado": r.get("Mes") or "Sin periodo", "Canal": r.get("Canal"),
                      "Sobres": r.get("Cantidad") or 0, "Ventas reportadas": float(r.get("Ventas Producto") or 0),
                      "Remanente reportado": r.get("Remanente"), "ID": r["ID"]})
    return filas
