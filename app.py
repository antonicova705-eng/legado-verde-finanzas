"""Legado Verde · Sistema financiero (Streamlit).

Requiere ``motor.py`` (contabilidad y almacenamiento con control de versiones)
en la misma carpeta. La lógica nueva vive en el paquete ``lv``.
"""
from __future__ import annotations

import copy
import json
import math
import os
from datetime import date, datetime, timedelta
from uuid import uuid4

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lv import importacion, reportes, respaldos, ui
from lv import operaciones as op
from lv.modelo import (ESTADOS_COBRO, ESTADOS_ENTREGA, ORIGEN_AMZ, ORIGEN_ML, canales, config_completa,
                       construir_venta, importes, pendientes_de_venta, presentaciones, validar_presentaciones)
from lv.util import MESES, ZONA, fin_de_mes, hoy_local, moneda

st.set_page_config(page_title="Legado Verde · Finanzas", page_icon="🥑", layout="wide",
                   initial_sidebar_state="expanded")
ui.estilos()

try:
    import motor as M
except ModuleNotFoundError:
    st.error("Falta el archivo motor.py junto a app.py. Contiene la contabilidad y el almacenamiento; "
             "sin él la aplicación no puede abrir la base de datos.")
    st.stop()

from lv.arranque import abrir, ruta_base  # noqa: E402  (requiere motor)

PAGINAS = ["Inicio", "Ventas", "Costos y gastos", "Finanzas", "Simulador", "Configuración y respaldos"]
VISTAS_VENTAS = ["Registro de ventas", "Registrar o editar", "Cobros", "Importar", "Historial"]


@st.cache_resource
def repositorio():
    return abrir()


repo = repositorio()
revision, datos = repo.leer()  # verdad del servidor en cada ejecución; no se copia a session_state
cfg = config_completa(datos)
ss = st.session_state
ss.setdefault("pagina", "Inicio")
ss.setdefault("ventas_vista", VISTAS_VENTAS[0])


# ====================================================================== utilidades de UI
def avisar(texto: str, tipo: str = "success"):
    ss["aviso"] = (tipo, texto)


def mostrar_aviso():
    if "aviso" in ss:
        tipo, texto = ss.pop("aviso")
        getattr(st, tipo)(texto)


def ejecutar(fn, exito: str | None = None, rerun: bool = True):
    """Aplica una transacción. Devuelve el resultado o None si falló (mostrando el error)."""
    try:
        res = repo.transaccion(fn)
    except op.Duplicado as d:
        avisar(str(d), "info")
        if rerun:
            st.rerun()
        return d.registro
    except (ValueError, RuntimeError, KeyError, TypeError) as e:
        st.error(f"No se guardó: {e}")
        return None
    if exito:
        avisar(exito)
    if rerun:
        st.rerun()
    return res


def ir_a_registrar():
    ss["pagina"] = "Ventas"
    ss["ventas_vista"] = "Registrar o editar"
    ss["venta_sel"] = "Nueva venta"


def etiqueta_periodo() -> str:
    a, b = date.fromisoformat(inicio), date.fromisoformat(fin)
    if a.day == 1 and b == fin_de_mes(a.year, a.month):
        return f"{MESES[a.month - 1]} {a.year}"
    if a == date(a.year, 1, 1) and b == date(a.year, 12, 31):
        return f"Año {a.year}"
    return f"Del {a:%d/%m/%Y} al {b:%d/%m/%Y}"


def encabezado(titulo: str, descripcion: str | None = None, boton: bool = True):
    c1, c2 = st.columns([4, 1.2], vertical_alignment="bottom")
    with c1:
        ui.periodo(etiqueta_periodo())
        st.markdown(f"# {titulo}")
    if boton:
        c2.button("Registrar venta", type="primary", icon=":material/add:", on_click=ir_a_registrar,
                  width="stretch", key=f"rv_{titulo}")
    if descripcion:
        ui.subtitulo(descripcion)
    mostrar_aviso()


def tabla(items, columnas=("Concepto", "Importe MXN")):
    df = pd.DataFrame(items, columns=list(columnas))
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={columnas[1]: st.column_config.NumberColumn(format="dollar")})


def periodo_sidebar():
    hoy = hoy_local()
    modo = st.sidebar.selectbox("Periodo", ["Mes", "Año", "Rango de fechas"], key="per_modo")
    if modo == "Mes":
        c1, c2 = st.sidebar.columns(2)
        y = c1.number_input("Año", 2000, 2100, hoy.year, key="per_anio")
        mth = c2.selectbox("Mes", range(1, 13), index=hoy.month - 1, format_func=lambda x: MESES[x - 1], key="per_mes")
        ini, fin = date(int(y), mth, 1), fin_de_mes(int(y), mth)
    elif modo == "Año":
        y = st.sidebar.number_input("Año", 2000, 2100, hoy.year, key="per_anio2")
        ini, fin = date(int(y), 1, 1), date(int(y), 12, 31)
    else:
        ini = st.sidebar.date_input("Desde", hoy.replace(day=1), key="per_desde")
        fin = st.sidebar.date_input("Hasta", hoy, key="per_hasta")
    if ini > fin:
        st.sidebar.error("La fecha inicial debe ser anterior o igual a la final.")
        st.stop()
    st.sidebar.caption(f"Del {ini:%d/%m/%Y} al {fin:%d/%m/%Y}")
    return ini.isoformat(), fin.isoformat()


# ====================================================================== barra lateral
st.sidebar.image("https://drive.google.com/thumbnail?id=1j9PfF082J_VzWP2bQURgQw8BVgeI3aK9&sz=w1000", width="stretch")
ICONOS = {"Inicio": ":material/space_dashboard:", "Ventas": ":material/point_of_sale:",
          "Costos y gastos": ":material/receipt_long:", "Finanzas": ":material/account_balance:",
          "Simulador": ":material/tune:", "Configuración y respaldos": ":material/settings:"}
pagina = st.sidebar.radio("Secciones", PAGINAS, key="pagina", label_visibility="collapsed",
                          format_func=lambda p: f"{ICONOS[p]}  {p}")
st.sidebar.divider()
inicio, fin = periodo_sidebar()
if st.sidebar.button("Actualizar datos", width="stretch", help="Trae cambios guardados desde otra sesión o por la sincronización."):
    st.rerun()
if os.environ.get("LEGADO_VERDE_MODO") == "demo":
    st.sidebar.warning("Base de demostración: estas cifras no son del negocio.")

cv_unit, cf_mes = M.costos_catalogo(datos["catalogo"], cfg["tc_usd"], cfg["vol_prod"])


# ====================================================================== INICIO
def pagina_inicio():
    encabezado("Inicio", "Cada cifra indica si es un dato registrado, preliminar o no disponible.")
    pend = reportes.pendientes(datos, inicio, fin)
    preliminar = bool(pend)
    rep = M.reporte(datos, inicio, fin)
    pe = M.calculo_pe(datos, inicio, fin)
    incompletas = reportes.ventas_incompletas(datos, inicio, fin)
    costo_pend = bool(pe.get("faltantes") or incompletas)

    st.markdown("### Ventas")
    filtro = st.selectbox("Canal", ["Todos los canales"] + canales(datos), key="ini_canal",
                          help="Filtra solo los indicadores comerciales de esta sección. Gastos, EBITDA y efectivo son siempre globales.")
    canal = None if filtro == "Todos los canales" else filtro
    c = reportes.comerciales(datos, inicio, fin, canal)
    est = "pre" if preliminar else "ok"
    ui.franja([
        {"etiqueta": "Ventas netas de producto", "valor": moneda(c["venta_neta_producto"], ""), "estado": est,
         "nota": "Preliminar: hay pendientes" if preliminar else "Registrado", "destacado": True},
        {"etiqueta": "Sobres netos vendidos", "valor": None if c["sobres_netos"] is None else f"{c['sobres_netos']:,}",
         "estado": "nd" if c["sobres_netos"] is None else est,
         "nota": f"{c['sobres']:,} vendidos; devoluciones desconocidas en {c['devueltos_desconocidos']}" if c["sobres_netos"] is None else None},
        {"etiqueta": "Ventas registradas", "valor": f"{c['ventas']:,}", "estado": est},
        {"etiqueta": "Ticket promedio", "valor": None if c["ticket"] is None else moneda(c["ticket"], ""),
         "estado": "nd" if c["ticket"] is None else est},
        {"etiqueta": "Margen de contribución", "valor": None if c["margen_contribucion"] is None else moneda(c["margen_contribucion"], ""),
         "estado": "nd" if c["margen_contribucion"] is None else est,
         "nota": f"Falta costo, comisión o logística en {c['margen_pendientes']} ventas" if c["margen_contribucion"] is None and c["ventas"] else None},
        {"etiqueta": "Por cobrar (registrado)", "valor": moneda(c["por_cobrar"], ""), "estado": est,
         "nota": f"Cobrado: {moneda(c['cobrado'], '')}"},
    ])

    g1, g2 = st.columns([1, 1.4])
    with g1:
        por = c["por_canal"]
        if por:
            fig = go.Figure(go.Bar(x=list(por.values()), y=list(por.keys()), orientation="h", marker_color=ui.BOSQUE,
                                   text=[moneda(v, "") for v in por.values()], textposition="auto",
                                   hovertemplate="%{y}: $%{x:,.2f}<extra></extra>"))
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(ui.layout_grafica(fig, 300, "Ventas netas por canal"), width="stretch")
        else:
            st.info("No hay ventas fechadas en este periodo. Usa «Registrar venta» o importa tus ventas.")
    with g2:
        anio = int(inicio[:4])
        filas = reportes.serie_mensual(datos, anio)
        fig = go.Figure(go.Bar(
            x=[f["Mes"][:3] for f in filas], y=[f["Ventas netas MXN"] for f in filas],
            marker_color=[ui.BOSQUE if f["Completo"] else ui.OLIVA for f in filas],
            marker_pattern_shape=["" if f["Completo"] else "/" for f in filas],
            customdata=[[f["Estado"], "No aplica" if f["Variación %"] is None else f"{f['Variación %']:+.1f}%"] for f in filas],
            hovertemplate="%{x}: $%{y:,.2f}<br>%{customdata[0]}<br>Variación: %{customdata[1]}<extra></extra>"))
        st.plotly_chart(ui.layout_grafica(fig, 300, f"Evolución mensual {anio}"), width="stretch")
        st.caption("Barras rayadas: meses parciales o sin cobertura confirmada. La variación solo se calcula entre dos meses completos. Sin ingresos por envío.")

    st.markdown("### Resultados globales")
    ui.franja([
        {"etiqueta": "EBITDA", "valor": None if costo_pend else moneda(rep["ebitda"], ""),
         "estado": "nd" if costo_pend else est,
         "nota": f"Falta costo, comisión o logística en {len(incompletas)} ventas" if costo_pend else None},
        {"etiqueta": "Utilidad neta", "valor": None if costo_pend else moneda(rep["utilidad"], ""),
         "estado": "nd" if costo_pend else est},
        {"etiqueta": "Efectivo registrado al corte", "valor": moneda(rep["efectivo_final"], ""),
         "estado": "pre" if not datos.get("apertura_confirmada") else est,
         "nota": "Sin balance de apertura confirmado" if not datos.get("apertura_confirmada") else None},
        {"etiqueta": "Costos fijos presupuestados / mes", "valor": moneda(cf_mes, ""), "estado": "pre",
         "nota": "Presupuesto del catálogo, no gasto real"},
    ])

    st.markdown("### Punto de equilibrio del periodo")
    if pe["meta"] is None or incompletas:
        st.info("No se puede calcular todavía: faltan costos, comisiones o logística confirmados, no hay ventas o el margen es cero o negativo.")
    elif pe["fijos"] <= 0:
        st.info("No hay gastos fijos registrados en el periodo. Regístralos en «Costos y gastos» para interpretar la meta.")
    else:
        meta = pe["meta"]
        fig = go.Figure(go.Bar(x=[pe["ventas"]], y=["Ventas"], orientation="h", marker_color=ui.BOSQUE,
                               hovertemplate="$%{x:,.2f}<extra></extra>"))
        fig.add_vline(x=meta, line_color=ui.ROJO, line_width=3, annotation_text=f"Meta {moneda(meta, '')}")
        fig.update_layout(xaxis=dict(range=[0, max(meta, pe["ventas"]) * 1.15]))
        st.plotly_chart(ui.layout_grafica(fig, 170), width="stretch")
        st.caption(f"Avance {pe['avance']:.1f}% · faltan {moneda(max(meta - pe['ventas'], 0))} · margen conjunto {pe['margen'] * 100:.1f}%."
                   + (" Meta preliminar." if preliminar else ""))
    with st.expander("Curva teórica del presupuesto (catálogo)"):
        contrib = cfg["precio_venta"] - cv_unit
        if contrib <= 0:
            st.info("Con el precio y costo variable del catálogo no hay margen positivo.")
        else:
            pe_u = math.ceil(cf_mes / contrib)
            import numpy as np
            u = np.linspace(0, max(pe_u * 2, 1500), 60)
            f = go.Figure()
            f.add_trace(go.Scatter(x=u, y=u * cfg["precio_venta"], name="Ventas presupuestadas", line=dict(color=ui.BOSQUE)))
            f.add_trace(go.Scatter(x=u, y=cf_mes + u * cv_unit, name="Costos presupuestados", line=dict(color=ui.ROJO)))
            f.add_trace(go.Scatter(x=[pe_u], y=[pe_u * cfg["precio_venta"]], mode="markers", name="Equilibrio teórico",
                                   marker=dict(size=12, color=ui.OLIVA)))
            st.plotly_chart(ui.layout_grafica(f, 300), width="stretch")
            st.caption(f"Equilibrio teórico: {pe_u:,} sobres al mes. Supuestos del catálogo; no son costos reales del periodo.")

    hist = reportes.historico_reportado(datos)
    if hist:
        st.markdown("### Histórico reportado (antes del sistema)")
        dfh = pd.DataFrame(hist)
        orden = list(dict.fromkeys(dfh["Periodo reportado"]))
        fig = go.Figure()
        for i, (canal_h, grupo) in enumerate(dfh.groupby("Canal", sort=False)):
            fig.add_trace(go.Bar(name=canal_h, x=grupo["Periodo reportado"], y=grupo["Ventas reportadas"],
                                 marker_color=ui.SERIE[i % len(ui.SERIE)],
                                 customdata=grupo[["Sobres"]].values,
                                 hovertemplate="%{x}<br>$%{y:,.2f} · %{customdata[0]} sobres<extra>" + str(canal_h) + "</extra>"))
        fig.update_layout(barmode="group", xaxis=dict(categoryorder="array", categoryarray=orden))
        st.plotly_chart(ui.layout_grafica(fig, 300), width="stretch")
        st.caption(f"Cifras reportadas sin fecha exacta ni verificación: {int(dfh['Sobres'].sum()):,} sobres y "
                   f"{moneda(dfh['Ventas reportadas'].sum())}. No entran a estados financieros ni a los indicadores del periodo "
                   "hasta que se fechen o se importen desglosadas desde la plataforma.")

    st.markdown(f"### Pendientes de información ({len(pend)})")
    if pend:
        st.dataframe(pd.DataFrame(pend), hide_index=True, width="stretch")
    else:
        st.success("Sin pendientes para este periodo.")


# ====================================================================== VENTAS
def tabla_ventas():
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 2])
    canal = c1.selectbox("Canal", ["Todos"] + canales(datos), key="tv_canal")
    origen = c2.selectbox("Origen", ["Todos", "Captura manual", "Voz (Claude)", "Importación (Claude/archivo)", ORIGEN_ML, ORIGEN_AMZ,
                                     "Heredado sin verificar"], key="tv_origen")
    estado = c3.selectbox("Estado", ["Activas", "Con pendientes", "Anuladas", "Todas"], key="tv_estado")
    buscar = c4.text_input("Buscar", placeholder="Folio, cliente, ID, pedido…", key="tv_buscar")
    solo_periodo = st.toggle("Solo el periodo seleccionado", value=False, key="tv_periodo")
    filas = []
    for r in datos["operaciones"]:
        if canal != "Todos" and r.get("Canal") != canal:
            continue
        if origen != "Todos" and r.get("Origen") != origen:
            continue
        if estado == "Activas" and r.get("Anulada"):
            continue
        if estado == "Anuladas" and not r.get("Anulada"):
            continue
        p = pendientes_de_venta(r)
        if estado == "Con pendientes" and (r.get("Anulada") or not p):
            continue
        if solo_periodo and not M.en_periodo(r, inicio, fin):
            continue
        texto = " ".join(str(r.get(k) or "") for k in ("ID", "Referencia", "Cliente", "Origen pedido", "Notas")).casefold()
        if buscar and buscar.casefold() not in texto:
            continue
        i = importes(r)
        filas.append({"Fecha": r.get("Fecha") or f"Sin fecha ({r.get('Mes')})", "Canal": r.get("Canal"),
                      "Folio": r.get("Referencia"), "Presentación": r.get("Presentación"),
                      "Unidades": r.get("Presentaciones"), "Sobres": r.get("Cantidad"),
                      "Venta neta": i["venta_neta_producto"], "Margen contrib.": i["margen_contribucion"],
                      "Entrega": r.get("Estado"), "Cobro": r.get("Estado cobro"), "Origen": r.get("Origen"),
                      "Pendientes": ", ".join(p) or "—", "Anulada": "Sí" if r.get("Anulada") else "No", "ID": r["ID"]})
    df = pd.DataFrame(filas)
    st.caption(f"{len(filas)} ventas. «Margen contrib.» vacío = falta costo, comisión o logística.")
    if not df.empty:
        st.dataframe(df, hide_index=True, width="stretch", height=min(560, 38 + 35 * len(df)),
                     column_config={"Venta neta": st.column_config.NumberColumn(format="dollar"),
                                    "Margen contrib.": st.column_config.NumberColumn(format="dollar")})
    st.download_button("Exportar CSV", pd.DataFrame([r for r in datos["operaciones"] if r["ID"] in set(df["ID"])] if not df.empty else []).to_csv(index=False).encode("utf-8-sig"),
                       "ventas_legado_verde.csv", "text/csv")
    with st.expander("Cómo tratar los registros heredados"):
        st.write("Los registros heredados conservan su Mes y Remanente originales, pero no tienen fecha exacta, costo ni cobros "
                 "verificados, así que no entran a los reportes. Un resumen de varios meses (p. ej. AMZ-001) debe "
                 "desglosarse en ventas individuales —o importarse desde la plataforma— y después anularse para no duplicarlo.")


def _num(v, defecto=0.0):
    return float(v) if v is not None else defecto


def formulario_venta():
    ids = [r["ID"] for r in datos["operaciones"]]
    etiquetas = {r["ID"]: f"{r.get('Fecha') or 'Sin fecha'} · {r.get('Canal')} · {r.get('Referencia') or r['ID'][:8]}"
                 for r in datos["operaciones"]}
    ss.setdefault("venta_sel", "Nueva venta")
    if ss["venta_sel"] not in ["Nueva venta"] + ids:
        ss["venta_sel"] = "Nueva venta"
    sel = st.selectbox("Venta", ["Nueva venta"] + ids[::-1], key="venta_sel",
                       format_func=lambda x: x if x == "Nueva venta" else etiquetas.get(x, x))
    anterior = op.por_id(datos, sel)
    nueva = anterior is None

    # Tras guardar se muestra la confirmación en lugar del formulario: un segundo clic no puede volver a enviar.
    if nueva and ss.get("venta_guardada"):
        vid = ss["venta_guardada"]
        r = op.por_id(datos, vid)
        if r:
            st.success(f"Venta guardada y verificada en la base. ID {vid}")
            i = importes(r)
            ui.vista_previa([("Fecha", r["Fecha"]), ("Canal", r["Canal"]), ("Sobres", f"{r['Cantidad']:,}")],
                            ("Venta neta de producto", moneda(i["venta_neta_producto"])))
        if st.button("Registrar otra venta", type="primary"):
            ss.pop("venta_guardada")
            ss["clave_form"] = str(uuid4())
            ss["form_v"] = ss.get("form_v", 0) + 1
            st.rerun()
        return
    ss.setdefault("clave_form", str(uuid4()))
    ss.setdefault("form_v", 0)
    k = f"{sel}_{ss['form_v']}"
    r = anterior or {}
    if anterior and anterior.get("Anulada"):
        st.warning(f"Venta anulada ({anterior.get('Motivo anulación') or 'sin motivo'}). Queda bloqueada; si hace falta, registra una nueva.")
    if anterior and anterior.get("Origen") in (ORIGEN_ML, ORIGEN_AMZ):
        st.info("Esta venta viene de la sincronización. Puedes confirmar costo, comisiones y notas; "
                "si editas cantidades o precios, la próxima actualización de la plataforma quedará en revisión en lugar de sobrescribirte.")

    pres = presentaciones(datos)
    st.markdown("#### Captura rápida")
    a, b, c = st.columns(3)
    fecha = a.date_input("Fecha de la venta", date.fromisoformat(r["Fecha"]) if r.get("Fecha") else hoy_local(),
                         max_value=hoy_local(), key=f"f_fecha_{k}")
    lista_canales = canales(datos)
    canal = b.selectbox("Canal", lista_canales, index=lista_canales.index(r["Canal"]) if r.get("Canal") in lista_canales else
                        (lista_canales.index("Venta directa") if "Venta directa" in lista_canales else 0), key=f"f_canal_{k}")
    nombres_p = list(pres)
    presentacion = c.selectbox("Presentación", nombres_p, index=nombres_p.index(r["Presentación"]) if r.get("Presentación") in nombres_p else 0,
                               key=f"f_pres_{k}", format_func=lambda n: f"{n} ({pres[n]} sobre{'s' if pres[n] > 1 else ''})")
    a, b, c = st.columns(3)
    unidades = a.number_input("Cantidad de presentaciones", min_value=1, step=1,
                              value=int(r.get("Presentaciones") or r.get("Cantidad") or 1), key=f"f_uni_{k}")
    precio_def = r.get("Precio presentación") or (r.get("Precio") if r else cfg["precio_venta"] * pres[presentacion])
    precio = b.number_input("Precio por presentación (MXN)", min_value=0.0, step=1.0, format="%.2f",
                            value=float(precio_def or 0), key=f"f_precio_{k}")
    folio = c.text_input("Folio o referencia", r.get("Referencia") or "", key=f"f_folio_{k}",
                         help="Si lo dejas vacío se genera un folio interno (INT-…). Debe ser único por canal, incluso entre ventas anuladas.")
    st.caption(f"Equivale a {unidades * pres[presentacion]:,} sobres.")

    with st.expander("Detalles avanzados: devoluciones, comisiones, envío, costo y entrega", expanded=not nueva):
        a, b, c = st.columns(3)
        descuento = a.number_input("Descuento total", min_value=0.0, value=_num(r.get("Descuento")), key=f"f_desc_{k}")
        devolucion = b.number_input("Devolución (dinero)", min_value=0.0, value=_num(r.get("Devolución")), key=f"f_dev_{k}",
                                    help="Importe devuelto al cliente. Reduce la venta neta.")
        dev_conocida = r.get("Sobres devueltos") is not None or nueva
        sdev_desconocido = c.checkbox("No sé cuántos sobres regresaron", value=not dev_conocida, key=f"f_sdevnd_{k}")
        sobres_dev = None if sdev_desconocido else c.number_input(
            "Sobres devueltos (unidades)", min_value=0, value=int(r.get("Sobres devueltos") or 0), key=f"f_sdev_{k}",
            help="Unidades que regresaron. Afecta sobres netos; registra el costo de ventas ya neto de lo que volvió a inventario.")
        a, b, c = st.columns(3)
        envio = a.number_input("Ingreso por envío cobrado", min_value=0.0, value=_num(r.get("Ingresos Envío")), key=f"f_env_{k}")
        com_nd = b.checkbox("Comisión aún no confirmada", value=not r.get("Comisiones confirmadas", True) if r else False, key=f"f_comnd_{k}")
        comision = b.number_input("Comisiones", min_value=0.0, value=_num(r.get("Comisiones")), key=f"f_com_{k}", disabled=com_nd)
        log_nd = c.checkbox("Logística aún no confirmada", value=not r.get("Logística confirmada", True) if r else False, key=f"f_lognd_{k}")
        logistica = c.number_input("Costos logísticos", min_value=0.0, value=_num(r.get("Costos Logísticos")), key=f"f_log_{k}", disabled=log_nd)
        a, b, c = st.columns(3)
        costo_ok = a.checkbox("Costo de ventas confirmado", value=bool(r.get("Costo confirmado")), key=f"f_cok_{k}",
                              help="Márcalo también si el costo real es cero.")
        costo = a.number_input("Costo de ventas total (neto)", min_value=0.0, value=_num(r.get("Costo de ventas")),
                               key=f"f_costo_{k}", disabled=not costo_ok)
        entrega = b.selectbox("Estado de entrega", ESTADOS_ENTREGA, index=ESTADOS_ENTREGA.index(r["Estado"]) if r.get("Estado") in ESTADOS_ENTREGA else 0, key=f"f_ent_{k}")
        cliente = c.text_input("Cliente (opcional)", r.get("Cliente") or "", key=f"f_cli_{k}")
        notas = st.text_area("Notas", r.get("Notas") or "", key=f"f_notas_{k}", height=70)

    entrada = {"fecha": fecha.isoformat(), "canal": canal, "referencia": folio, "presentacion": presentacion,
               "presentaciones": int(unidades), "precio_presentacion": precio, "descuento": descuento,
               "devolucion": devolucion, "sobres_devueltos": sobres_dev, "envio": envio,
               "comisiones": None if com_nd else comision, "logistica": None if log_nd else logistica,
               "costo": costo if costo_ok else None, "costo_confirmado": costo_ok, "estado": entrega,
               "cliente": cliente or None, "notas": notas or None}
    cobro = None
    if nueva:
        st.markdown("#### Cobro")
        modo = st.radio("¿Ya cobraste esta venta?", ["Todavía no", "Sí, registrar el cobro ahora"], horizontal=True, key=f"f_cmodo_{k}",
                        help="El cobro crea el movimiento de efectivo. Cambiar una etiqueta a «Cobrado» no lo hace.")
        if modo.startswith("Sí"):
            a, b, c, d = st.columns(4)
            cf = a.date_input("Fecha del cobro", fecha, min_value=fecha, max_value=hoy_local(), key=f"f_cf_{k}")
            try:
                total_prev = importes(construir_venta(datos, entrada))["ventas_netas_totales"]
            except ValueError:
                total_prev = 0.0
            ci = b.number_input("Importe cobrado", min_value=0.0, value=round(total_prev, 2), key=f"f_ci_{k}")
            cm = c.selectbox("Medio", ["Transferencia", "Efectivo", "Tarjeta", "Depósito de plataforma", "Otro"], key=f"f_cm_{k}")
            cr = d.text_input("Referencia bancaria (opcional)", key=f"f_cr_{k}", help="Si no la tienes, queda como pendiente.")
            cobro = {"fecha": cf.isoformat(), "importe": ci, "medio": cm, "referencia": cr or None}

    st.markdown("#### Vista previa")
    try:
        prev = construir_venta(datos, entrada, anterior=anterior)
        i = importes(prev)
        filas = [("Venta bruta", moneda(i["venta_bruta"])), ("Descuentos", moneda(-i["descuento"])),
                 ("Devoluciones", moneda(-i["devolucion"])), ("Venta neta de producto", moneda(i["venta_neta_producto"])),
                 ("Ingreso por envío", moneda(i["ingreso_envio"])),
                 ("Comisiones", moneda(-(i["comisiones"] or 0)) if i["comisiones"] is not None else "Pendiente"),
                 ("Logística", moneda(-(i["logistica"] or 0)) if i["logistica"] is not None else "Pendiente"),
                 ("Costo de ventas", moneda(-i["costo_ventas"]) if i["costo_ventas"] is not None else "Pendiente")]
        if op.es_marketplace(datos, prev):
            filas.append(("Depósito estimado de la plataforma",
                          moneda(i["deposito_estimado"]) if i["deposito_estimado"] is not None else "Pendiente"))
        if cobro:
            filas.append(("Cobro que se registrará", moneda(cobro["importe"]) + f" el {cobro['fecha']}"))
        ui.vista_previa(filas, ("Margen de contribución",
                                moneda(i["margen_contribucion"]) if i["margen_contribucion"] is not None else "No disponible"),
                        nota=f"{prev['Cantidad']:,} sobres. Margen de contribución = ventas netas − costo − comisiones − logística; "
                             "no es utilidad (faltan gastos fijos) ni efectivo. El depósito estimado no es un cobro.")
        valido = True
    except ValueError as e:
        st.error(str(e))
        valido = False

    if anterior and anterior.get("Anulada"):
        return
    if nueva:
        if st.button("Guardar venta", type="primary", disabled=not valido, key=f"f_guardar_{k}"):
            entrada["clave"] = ss["clave_form"]
            res = ejecutar(lambda d: op.registrar_venta(d, entrada, cobro), rerun=False)
            if res:
                vid = res[0]["ID"] if isinstance(res, tuple) else res.get("ID")
                if op.por_id(repo.leer()[1], vid):  # verificación de escritura
                    ss["venta_guardada"] = vid
                    avisar("Venta registrada" + (" con su cobro." if cobro else "."))
                st.rerun()
    else:
        h = op.huella_registro(anterior)
        if st.button("Guardar cambios", type="primary", disabled=not valido, key=f"f_guardarc_{k}"):
            ejecutar(lambda d: op.editar_venta(d, sel, entrada, h), "Cambios guardados.")
        with st.expander("Anular venta"):
            st.write("Usa la anulación solo para registros cargados por error. Si la venta ocurrió y se devolvió, registra la devolución y el reembolso.")
            motivo = st.text_input("Motivo", key=f"f_motivo_{k}")
            conf = st.checkbox(f"Confirmo anular {sel}", key=f"f_anconf_{k}")
            if st.button("Anular venta", key=f"f_anular_{k}", disabled=not conf):
                ejecutar(lambda d: op.anular_venta(d, sel, h, motivo), "Venta anulada.")


def vista_cobros():
    elegibles = [r for r in datos["operaciones"] if M.activo(r) and r.get("Fecha")]
    if not elegibles:
        st.info("Primero registra una venta con fecha.")
        return
    def etiqueta(vid):
        r = op.por_id(datos, vid)
        saldo = importes(r)["ventas_netas_totales"] - op.cobrado_neto(datos, vid)
        return f"{r['Fecha']} · {r['Canal']} · {r.get('Referencia') or vid[:8]} · saldo {moneda(saldo, '')}"
    solo_saldo = st.toggle("Solo ventas con saldo por cobrar", value=True)
    lista = [r["ID"] for r in elegibles[::-1]
             if not solo_saldo or importes(r)["ventas_netas_totales"] - op.cobrado_neto(datos, r["ID"]) > 0.005]
    if not lista:
        st.success("No hay saldos por cobrar.")
        return
    vid = st.selectbox("Venta", lista, format_func=etiqueta)
    venta = op.por_id(datos, vid)
    total = importes(venta)["ventas_netas_totales"]
    cobrado = op.cobrado_neto(datos, vid)
    ui.franja([{"etiqueta": "Venta neta total", "valor": moneda(total, "")},
               {"etiqueta": "Cobrado", "valor": moneda(cobrado, "")},
               {"etiqueta": "Saldo", "valor": moneda(total - cobrado, "")}])
    with st.form(f"cobro_{vid}", clear_on_submit=True):
        a, b, c = st.columns(3)
        tipo = a.selectbox("Movimiento", ["Cobro de venta", "Reembolso de venta"])
        fecha = b.date_input("Fecha real del movimiento", hoy_local(), max_value=hoy_local())
        importe = c.number_input("Importe", min_value=0.01, value=max(round(total - cobrado, 2), 0.01))
        a, b = st.columns(2)
        medio = a.selectbox("Medio", ["Transferencia", "Efectivo", "Tarjeta", "Depósito de plataforma", "Otro"])
        ref = b.text_input("Referencia bancaria o recibo (opcional)")
        ok = st.form_submit_button("Registrar movimiento", type="primary")
    if ok:
        clave = f"cobro-{vid}-{fecha.isoformat()}-{importe:.2f}-{(ref or '').strip().casefold()}-{tipo}"
        ejecutar(lambda d: op.registrar_cobro(d, vid, fecha.isoformat(), importe, medio, ref, clave, tipo), f"{tipo} registrado.")
    vinc = [a for a in datos["asientos"] if a.get("Venta ID") == vid]
    if vinc:
        st.dataframe(pd.DataFrame([{"Fecha": a["Fecha"], "Tipo": a.get("Tipo"), "Referencia": a.get("Referencia"),
                                    "Referencia bancaria": a.get("Referencia bancaria") or "Pendiente",
                                    "Anulado": "Sí" if a.get("Anulada") else "No"} for a in vinc]), hide_index=True, width="stretch")


INSTRUCCION_CLAUDE = """Convierte mis ventas a JSON con el formato «legado-verde-ventas» versión 1 del sistema de Legado Verde.
Reglas: fecha en AAAA-MM-DD (resuelve «hoy» con la hora de Ciudad de México); null para lo que no dije
(cliente, referencia bancaria, comisiones, logística, costo); una clave única por venta; cobro solo si dije
que ya se cobró, con fecha e importe explícitos. Muéstrame primero los datos interpretados y los pendientes."""


def vista_importar():
    st.write("Importa ventas desde un archivo JSON o CSV —por ejemplo, el que Claude genera a partir de tus mensajes—. "
             "Nada se guarda hasta que revises la vista previa y confirmes.")
    with st.expander("Cómo pedirle las ventas a Claude"):
        st.code(INSTRUCCION_CLAUDE, language=None)
        st.download_button("Descargar plantilla CSV", importacion.plantilla_csv().encode("utf-8-sig"), "plantilla_ventas.csv", "text/csv")
    archivo = st.file_uploader("Archivo de ventas", type=["json", "csv"], key=f"imp_{ss.get('imp_v', 0)}")
    if not archivo:
        return
    try:
        ventas = importacion.leer(archivo.getvalue(), archivo.name)
    except (ValueError, json.JSONDecodeError) as e:
        st.error(f"No se pudo leer el archivo: {e}")
        return
    filas = importacion.previsualizar(datos, ventas)
    resumen = pd.DataFrame([{
        "Fila": f["Fila"], "Estado": f["Estado"], "Fecha": (f["venta"] or {}).get("Fecha"),
        "Canal": (f["venta"] or {}).get("Canal"), "Sobres": (f["venta"] or {}).get("Cantidad"),
        "Venta neta": importes(f["venta"])["venta_neta_producto"] if f["venta"] else None,
        "Cobro": f"{moneda(f['cobro']['importe'], '')} el {f['cobro']['fecha']}" if f["cobro"] else "Sin cobro",
        "Pendientes": "; ".join(f["Pendientes"]) or "—", "Mensajes": " ".join(f["Mensajes"]) or "—"} for f in filas])
    st.dataframe(resumen, hide_index=True, width="stretch",
                 column_config={"Venta neta": st.column_config.NumberColumn(format="dollar")})
    errores = [f for f in filas if f["Estado"] == "Error"]
    if errores:
        st.error("Corrige las filas con error y vuelve a cargar el archivo. No se importará nada mientras haya errores.")
        return
    aceptar = set()
    for f in filas:
        if f["Estado"] == "Posible duplicado" and st.checkbox(f"Importar la fila {f['Fila']} aunque se parece a otra venta", key=f"imp_dup_{f['Fila']}"):
            aceptar.add(f["Fila"])
    nuevas = sum(1 for f in filas if f["Estado"] == "Nueva") + len(aceptar)
    if not nuevas:
        st.info("No hay ventas nuevas que importar: todas ya estaban registradas o requieren confirmación.")
        return
    if any("Costo" in p for f in filas for p in f["Pendientes"]):
        st.warning("Algunas ventas entran con costo pendiente: margen, EBITDA y utilidad del periodo se mostrarán como «No disponible» hasta confirmarlo.")
    conf = st.checkbox(f"Revisé la vista previa y quiero registrar {nuevas} venta(s)")
    if st.button("Importar ventas", type="primary", disabled=not conf):
        res = ejecutar(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas), aceptar, ventas), rerun=False)
        if res:
            _, verif = repo.leer()
            for s in res:
                s["Verificada en la base"] = "Sí" if s["ID"] and op.por_id(verif, s["ID"]) else ("—" if not s["ID"] else "No")
            ss["imp_resultado"] = res
            ss["imp_v"] = ss.get("imp_v", 0) + 1
            st.rerun()


def vista_historial():
    eventos = datos.get("historial", [])
    st.caption(f"{len(eventos)} eventos registrados (más recientes primero).")
    filas = []
    for e in eventos[::-1][:500]:
        if isinstance(e, dict):
            desp = e.get("Después") or e.get("despues") or {}
            filas.append({"Tipo": e.get("Tipo") or e.get("tipo"), "Fecha": e.get("Fecha") or e.get("fecha"),
                          "Registro": (desp or {}).get("ID") if isinstance(desp, dict) else None,
                          "Detalle": json.dumps(e, ensure_ascii=False, default=str)[:300]})
    if filas:
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")


def pagina_ventas():
    encabezado("Ventas", "Registra, corrige y consulta ventas por canal. Los cobros se registran con su fecha e importe reales.")
    vista = st.radio("Vista", VISTAS_VENTAS, horizontal=True, key="ventas_vista", label_visibility="collapsed")
    if ss.get("imp_resultado") and vista == "Importar":
        st.success("Importación terminada.")
        st.dataframe(pd.DataFrame(ss.pop("imp_resultado")), hide_index=True, width="stretch")
    {"Registro de ventas": tabla_ventas, "Registrar o editar": formulario_venta, "Cobros": vista_cobros,
     "Importar": vista_importar, "Historial": vista_historial}[vista]()


# ====================================================================== COSTOS Y GASTOS
PARES = {
    "Gasto fijo": ("Gasto operativo fijo", "Efectivo", "Operación"),
    "Gasto variable": ("Gasto operativo variable", "Efectivo", "Operación"),
    "Compra de inventario": ("Inventarios", "Efectivo", "Operación"),
    "Compra de equipo": ("Equipo", "Efectivo", "Inversión"),
    "Depreciación": ("Depreciación", "Depreciación acumulada", "Operación"),
    "Amortización": ("Amortización", "Amortización acumulada", "Operación"),
    "Impuesto devengado": ("Impuestos", "Impuestos por pagar", "Operación"),
    "Pago de impuestos": ("Impuestos por pagar", "Efectivo", "Operación"),
    "Préstamo recibido": ("Efectivo", "Deuda largo plazo", "Financiamiento"),
    "Pago de préstamo": ("Deuda largo plazo", "Efectivo", "Financiamiento"),
    "Aportación de capital": ("Efectivo", "Capital", "Financiamiento"),
    "Apertura": ("Efectivo", "Capital", "Sin clasificar"),
    "Otro asiento": ("Efectivo", "Capital", "Sin clasificar"),
}
FLUJOS = ["Operación", "Inversión", "Financiamiento", "Sin clasificar"]


def capturar_asiento():
    st.info("Aquí registras gastos y movimientos reales. Las ventas ya generan sus asientos de venta, costo y gastos de canal: no los repitas. "
            "El catálogo es presupuesto y no genera gastos reales.")
    tipo = st.selectbox("Tipo de movimiento", list(PARES), key="as_tipo")
    deb, hab, flujo = PARES[tipo]
    st.caption("Para un gasto pendiente de pago abona Proveedores; al pagarlo carga Proveedores y abona Efectivo. La apertura admite varios activos, pasivos y capital.")
    with st.form(f"asiento_{tipo}", clear_on_submit=True):
        a, b, c = st.columns(3)
        fecha = a.date_input("Fecha de devengo o movimiento", hoy_local())
        referencia = b.text_input("Referencia única")
        descripcion = c.text_input("Concepto o soporte")
        flujo_sel = st.selectbox("Clasificación del efectivo", FLUJOS, index=FLUJOS.index(flujo))
        editor = st.data_editor(pd.DataFrame([M.cargo(deb, 0), M.abono(hab, 0)]), num_rows="dynamic", hide_index=True, width="stretch",
                                column_config={"Cuenta": st.column_config.SelectboxColumn("Cuenta", options=list(M.CUENTAS), required=True),
                                               "Debe": st.column_config.NumberColumn("Debe", min_value=0.0, required=True),
                                               "Haber": st.column_config.NumberColumn("Haber", min_value=0.0, required=True)})
        cert = st.checkbox("Confirmo que esta apertura contiene todos los saldos al cierre anterior al inicio de los reportes") if tipo == "Apertura" else False
        enviar = st.form_submit_button("Guardar asiento", type="primary")
    if enviar:
        lineas = editor.to_dict("records")

        def fn(d):
            if not referencia.strip() or not descripcion.strip():
                raise ValueError("Referencia y concepto son obligatorios.")
            if any((x.get("Referencia") or "").casefold() == referencia.strip().casefold() for x in d["asientos"]):
                raise ValueError("Referencia de asiento duplicada, incluso si está anulado.")
            if tipo == "Apertura":
                if any(x.get("Tipo") == "Apertura" and not x.get("Anulada") for x in d["asientos"]):
                    raise ValueError("Ya existe una apertura activa. Anúlala antes de reemplazarla.")
                if any(M.CUENTAS[l["Cuenta"]][0] not in ["Activo circulante", "Activo no circulante", "Pasivo corto plazo", "Pasivo largo plazo", "Capital"] for l in lineas):
                    raise ValueError("La apertura solo admite cuentas patrimoniales; usa Resultados anteriores para utilidades acumuladas.")
                if any(x["Fecha"] <= fecha.isoformat() for x in M.asientos(d)):
                    raise ValueError("La apertura debe ser anterior a todas las operaciones y asientos existentes.")
            x = M.fila_asiento(fecha.isoformat(), lineas, Tipo=tipo, Flujo=flujo_sel, Referencia=referencia.strip(), Concepto=descripcion)
            d["asientos"].append(x)
            if tipo == "Apertura":
                d["apertura_confirmada"] = cert
                d["fecha_apertura"] = fecha.isoformat()
            M.evento(d, "Asiento", None, x)
        ejecutar(fn, "Asiento guardado.")


def lista_asientos():
    filas = [{"Fecha": a["Fecha"], "Tipo": a.get("Tipo"), "Referencia": a.get("Referencia"), "Concepto": a.get("Concepto"),
              "Importe": sum(float(l.get("Debe") or 0) for l in a.get("Líneas", [])), "Anulado": "Sí" if a.get("Anulada") else "No",
              "ID": a["ID"]} for a in datos["asientos"][::-1]]
    if not filas:
        st.info("Aún no hay asientos manuales.")
        return
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch", column_config={"Importe": st.column_config.NumberColumn(format="dollar")})
    with st.expander("Ver detalle con líneas contables"):
        st.json(datos["asientos"])
    activos = [a for a in datos["asientos"] if not a.get("Anulada")]
    if activos:
        with st.form("anular_asiento"):
            aid = st.selectbox("Asiento a anular", [a["ID"] for a in activos], format_func=lambda x: next(a.get("Referencia", x) for a in activos if a["ID"] == x))
            confirma = st.checkbox("Confirmo que este asiento se cargó por error")
            enviar = st.form_submit_button("Anular asiento")
        if enviar:
            if not confirma:
                st.error("Marca la confirmación para anular.")
            else:
                def fn(d):
                    a = next(a for a in d["asientos"] if a["ID"] == aid)
                    if a.get("Anulada"):
                        raise ValueError("El asiento ya estaba anulado.")
                    previo = copy.deepcopy(a)
                    a["Anulada"] = True
                    if a.get("Tipo") == "Apertura":
                        d["apertura_confirmada"] = False
                        d["fecha_apertura"] = None
                    venta = op.por_id(d, a.get("Venta ID") or "")
                    if venta:
                        op._actualizar_estado_cobro(d, venta)
                    M.evento(d, "Anulación de asiento", previo, a)
                ejecutar(fn, "Asiento anulado.")


def catalogo():
    st.write("Presupuesto de costos usado por el punto de equilibrio teórico y el simulador. No genera gastos reales.")
    with st.form(f"catalogo_{revision}"):
        df = st.data_editor(pd.DataFrame(datos["catalogo"]), num_rows="dynamic", width="stretch", hide_index=True,
                            column_config={"Importe Base": st.column_config.NumberColumn("Importe base", format="$%.2f", min_value=0.0),
                                           "Moneda": st.column_config.SelectboxColumn("Moneda", options=["MXN", "USD"]),
                                           "Clasificación": st.column_config.SelectboxColumn("Clasificación", options=["Fijo", "Variable"]),
                                           "Frecuencia": st.column_config.SelectboxColumn("Frecuencia", options=["Mensual", "Por sobre", "Anual"]),
                                           "Estado": st.column_config.SelectboxColumn("Estado", options=["Confirmado", "Estimado", "Pendiente"])})
        guardar = st.form_submit_button("Guardar catálogo", type="primary")
    a, b = st.columns(2)
    a.metric("Costo variable unitario presupuestado", moneda(cv_unit))
    b.metric("Costos fijos mensuales presupuestados", moneda(cf_mes))
    st.download_button("Exportar catálogo CSV", pd.DataFrame(datos["catalogo"]).to_csv(index=False).encode("utf-8-sig"),
                       "catalogo_costos_legado_verde.csv", "text/csv")
    if guardar:
        filas = df.to_dict("records")

        def fn(d):
            if df.isna().any().any():
                raise ValueError("Completa todas las celdas del catálogo antes de guardarlo.")
            for row in filas:
                v = float(row["Importe Base"])
                if not math.isfinite(v) or v < 0:
                    raise ValueError("Los importes deben ser finitos y no negativos.")
            M.costos_catalogo(filas, d["config"]["tc_usd"], d["config"]["vol_prod"])
            if d["catalogo"] != filas:
                M.evento(d, "Catálogo", d["catalogo"], filas)
                d["catalogo"] = filas
        ejecutar(fn, "Catálogo guardado.")


def pagina_costos():
    encabezado("Costos y gastos", "Presupuesto de costos y registro de gastos y movimientos reales.")
    t1, t2, t3 = st.tabs(["Registrar gasto o movimiento", "Asientos registrados", "Presupuesto (catálogo)"])
    with t1:
        capturar_asiento()
    with t2:
        lista_asientos()
    with t3:
        catalogo()


# ====================================================================== FINANZAS
def pagina_finanzas():
    encabezado("Finanzas", f"Estados financieros del {inicio} al {fin}. Importes en MXN sin IVA; los ceros significan que no hay movimientos registrados.")
    pend = reportes.pendientes(datos, inicio, fin)
    rep = M.reporte(datos, inicio, fin)
    faltan = bool(reportes.ventas_incompletas(datos, inicio, fin))
    est = "pre" if pend else "ok"
    ui.franja([
        {"etiqueta": "Ventas netas (incluye envío)", "valor": moneda(rep["ventas"], ""), "estado": est},
        {"etiqueta": "EBITDA", "valor": None if faltan else moneda(rep["ebitda"], ""), "estado": "nd" if faltan else est,
         "nota": "Falta costo, comisión o logística" if faltan else None},
        {"etiqueta": "Margen EBITDA", "valor": None if faltan or rep["ventas"] <= 0 else f"{rep['ebitda'] / rep['ventas'] * 100:.1f}%",
         "estado": "nd" if faltan or rep["ventas"] <= 0 else est},
        {"etiqueta": "Efectivo registrado al corte", "valor": moneda(rep["efectivo_final"], ""), "estado": est},
    ])
    if pend:
        with st.expander(f"Por qué los reportes son preliminares ({len(pend)})"):
            st.dataframe(pd.DataFrame(pend), hide_index=True, width="stretch")
    t1, t2, t3, t4 = st.tabs(["Estado de resultados", "Flujo de efectivo", "Situación financiera", "Cobertura y libro contable"])
    with t1:
        nd = None
        tabla([("Ventas netas", rep["ventas"]), ("Costo de ventas", nd if faltan else rep["costo"]),
               ("Utilidad bruta", nd if faltan else rep["ventas"] - rep["costo"]),
               ("Gastos operativos sin depreciación ni amortización", rep["gasto"]),
               ("EBITDA", nd if faltan else rep["ebitda"]), ("Depreciación y amortización", rep["da"]),
               ("Utilidad operativa", nd if faltan else rep["operativa"]), ("Resultado financiero", rep["financiero"]),
               ("Utilidad antes de impuestos", nd if faltan else rep["operativa"] + rep["financiero"]),
               ("Impuestos devengados", rep["impuestos"]), ("Utilidad neta", nd if faltan else rep["utilidad"])])
        st.caption("Ventas incluye producto neto e ingresos por envío; costos y gastos devengados. EBITDA = utilidad operativa + depreciación + amortización. "
                   "Celda vacía = no disponible (falta costo, comisión o logística confirmados en alguna venta del periodo).")
    with t2:
        tabla([("Saldo inicial registrado", rep["efectivo_inicial"])] + [(f"Flujos de {k.lower()}", v) for k, v in rep["flujos"].items()]
              + [("Variación neta registrada", sum(rep["flujos"].values())), ("Saldo final registrado", rep["efectivo_final"])])
        dif = rep["efectivo_inicial"] + sum(rep["flujos"].values()) - rep["efectivo_final"]
        st.write("Diferencia de conciliación de efectivo: " + moneda(dif))
        st.caption("Método directo: solo movimientos de Efectivo por fecha de cobro o pago. Un pedido pagado en una plataforma no es efectivo hasta su liquidación.")
        if abs(rep["flujos"].get("Sin clasificar", 0)) > .005:
            st.warning("Clasifica los movimientos sin clasificar. Una apertura dentro del periodo no debe leerse como flujo operativo.")
    with t3:
        g = rep["grupos"]
        tabla(list(g.items()) + [("Activo total", g["Activo circulante"] + g["Activo no circulante"]),
                                 ("Pasivo total", g["Pasivo corto plazo"] + g["Pasivo largo plazo"]),
                                 ("Pasivo + Capital", g["Pasivo corto plazo"] + g["Pasivo largo plazo"] + g["Capital"]),
                                 ("Diferencia Activo − Pasivo − Capital", rep["descuadre"])])
        if abs(rep["descuadre"]) < .01:
            st.success("La ecuación contable de los movimientos registrados cuadra. Esto no certifica que estén completos.")
        else:
            st.error("La ecuación contable no cuadra; revisa los asientos.")
        with st.expander("Detalle por cuenta"):
            tabla([(k, (v if M.CUENTAS[k][0].startswith("Activo") else v * M.CUENTAS[k][1])) for k, v in rep["saldos"].items()])
            if rep["saldos"].get("Inventarios", 0) < -.005:
                st.warning("Inventario negativo: registra apertura y compras, o revisa los costos de ventas.")
    with t4:
        st.write("Confirma la cobertura solo después de verificar ventas y devoluciones, costos, inventarios, gastos, impuestos, depreciación, cobros y pagos del periodo.")
        conf = st.checkbox(f"Verifiqué que la información del {inicio} al {fin} está completa", key="cob_conf")
        if st.button("Confirmar cobertura del periodo", disabled=not conf):
            def fn(d):
                if any(M.activo(r) and not r.get("Fecha") for r in d["operaciones"]):
                    raise ValueError("Primero fecha o desglosa los registros activos sin fecha, o anula los cargados por error.")
                if any(M.en_periodo(r, inicio, fin) and not r.get("Costo confirmado") for r in d["operaciones"]):
                    raise ValueError("Primero confirma el costo de todas las ventas del periodo.")
                if fin > hoy_local().isoformat():
                    raise ValueError("No se puede confirmar un periodo futuro; usa un rango hasta hoy.")
                c = {"Inicio": inicio, "Fin": fin}
                if c not in d["cobertura"]:
                    d["cobertura"].append(c)
                    M.evento(d, "Cobertura", None, c)
            ejecutar(fn, "Cobertura confirmada.")
        st.write("Periodos confirmados:", ", ".join(f"{c['Inicio']} a {c['Fin']}" for c in datos["cobertura"]) or "ninguno")
        if datos["cobertura"] and st.button("Revocar confirmaciones de cobertura"):
            def fn(d):
                M.evento(d, "Cobertura", d["cobertura"], [])
                d["cobertura"] = []
            ejecutar(fn, "Confirmaciones revocadas.")
        export = [{"ID": a["ID"], "Fecha": a["Fecha"], "Tipo": a.get("Tipo"), **l} for a in rep["ledger"] for l in a["Líneas"]]
        st.download_button("Exportar libro contable CSV", pd.DataFrame(export).to_csv(index=False).encode("utf-8-sig"), "libro_contable.csv", "text/csv")


# ====================================================================== SIMULADOR
def pagina_simulador():
    encabezado("Simulador", "Explora precio, volumen, costos y mezcla de canales. Nada de lo que cambies aquí modifica los registros ni el catálogo.", boton=False)
    hist = reportes.promedios_por_canal(datos)
    escenario = st.radio("Escenario de volumen", ["Base", "Conservador (−15%)", "Optimista (+20%)"], horizontal=True, key="sim_esc")
    mult = {"Base": 1.0, "Conservador (−15%)": 0.85, "Optimista (+20%)": 1.20}[escenario]
    a, b, c = st.columns(3)
    vol = a.number_input("Volumen base mensual (sobres)", min_value=1, value=int(cfg["vol_prod"]), step=50, key="sim_vol")
    cvu = b.number_input("Costo variable por sobre", min_value=0.0, value=round(float(cv_unit), 2), key="sim_cv",
                         help="Inicia con el presupuesto del catálogo.")
    fijos = c.number_input("Costos fijos mensuales", min_value=0.0, value=round(float(cf_mes), 2), key="sim_cf")
    st.markdown("#### Mezcla de canales")
    st.caption("Los valores iniciales salen de tus ventas registradas cuando existen (comisión solo de ventas con comisión confirmada); "
               "si no, del precio promedio configurado y 0%. Son supuestos: ajústalos.")
    if "sim_mezcla" not in ss:
        filas = []
        activos = canales(datos)
        for canal in activos:
            h = hist.get(canal, {})
            filas.append({"Canal": canal, "% volumen": round(100 / len(activos), 1),
                          "Precio por sobre": round(h.get("precio") or cfg["precio_venta"], 2),
                          "Comisión %": round(h["comision_pct"], 1) if h.get("comision_pct") is not None else 0.0,
                          "Logística por sobre": round(h["logistica_sobre"], 2) if h.get("logistica_sobre") is not None else 0.0,
                          "Fuente": "Histórico registrado" if h else "Supuesto"})
        ss["sim_mezcla"] = filas
    mezcla = st.data_editor(pd.DataFrame(ss["sim_mezcla"]), hide_index=True, width="stretch", key="sim_editor",
                            disabled=["Canal", "Fuente"],
                            column_config={"% volumen": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, format="%.1f"),
                                           "Precio por sobre": st.column_config.NumberColumn(min_value=0.0, format="$%.2f"),
                                           "Comisión %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, format="%.1f"),
                                           "Logística por sobre": st.column_config.NumberColumn(min_value=0.0, format="$%.2f")})
    if st.button("Restablecer supuestos"):
        ss.pop("sim_mezcla", None)
        st.rerun()
    try:
        r = reportes.simular(vol * mult, cvu, fijos, mezcla.fillna(0).to_dict("records"))
    except ValueError as e:
        st.error(str(e))
        return
    total_pct = mezcla["% volumen"].fillna(0).sum()
    if abs(total_pct - 100) > 0.5:
        st.caption(f"Los porcentajes suman {total_pct:.1f}%; se normalizan a 100%.")
    ui.franja([
        {"etiqueta": "Sobres proyectados", "valor": f"{vol * mult:,.0f}", "estado": "pre", "nota": "Proyección"},
        {"etiqueta": "Ventas proyectadas", "valor": moneda(r["ventas"], ""), "estado": "pre", "nota": "Proyección"},
        {"etiqueta": "Margen de contribución", "valor": moneda(r["contribucion"], ""), "estado": "pre",
         "nota": f"{r['margen'] * 100:.1f}% de las ventas" if r["margen"] is not None else "Proyección"},
        {"etiqueta": "Resultado operativo proyectado", "valor": moneda(r["resultado"], ""), "estado": "pre", "nota": "Antes de impuestos"},
        {"etiqueta": "Punto de equilibrio", "valor": None if r["pe_sobres"] is None else f"{math.ceil(r['pe_sobres']):,} sobres",
         "estado": "nd" if r["pe_sobres"] is None else "pre",
         "nota": "Sin margen positivo" if r["pe_sobres"] is None else moneda(r["pe_ventas"], "")},
    ])
    df = pd.DataFrame(r["filas"])
    if not df.empty:
        fig = go.Figure(go.Bar(x=df["Canal"], y=df["Contribución"], marker_color=[ui.BOSQUE if v >= 0 else ui.ROJO for v in df["Contribución"]],
                               hovertemplate="%{x}: $%{y:,.2f}<extra></extra>"))
        st.plotly_chart(ui.layout_grafica(fig, 300, "Contribución mensual por canal"), width="stretch")
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={k: st.column_config.NumberColumn(format="dollar") for k in ["Ventas", "Costo variable", "Comisiones", "Logística", "Contribución"]}
                     | {"Sobres": st.column_config.NumberColumn(format="localized")})


# ====================================================================== CONFIGURACIÓN
def config_parametros():
    with st.form("parametros"):
        a, b, c = st.columns(3)
        precio = a.number_input("Precio de venta promedio por sobre", min_value=1.0, value=float(cfg["precio_venta"]), step=1.0)
        vol = b.number_input("Volumen de producción mensual (sobres)", min_value=1, value=int(cfg["vol_prod"]), step=50)
        tc = c.number_input("Tipo de cambio USD/MXN", min_value=10.0, value=float(cfg["tc_usd"]), step=0.5)
        a, b = st.columns(2)
        costo_def = cfg.get("costo_sobre")
        sin_costo = a.checkbox("Aún no tengo un costo de producción por sobre confirmado", value=costo_def is None)
        costo_sobre = b.number_input("Costo de producción por sobre (MXN)", min_value=0.0, value=float(costo_def or 0.0),
                                     step=1.0, disabled=sin_costo,
                                     help="Se usa como costo confirmado en ventas registradas por voz. Un paquete de 10 costará 10 veces este valor.")
        prioridad = st.radio("Si una venta sincronizada se editó a mano y la plataforma informa cambios",
                             ["Conservar mi edición y pedirme revisión", "La plataforma prevalece"],
                             index=0 if cfg.get("conciliacion", {}).get("prioridad", "manual") == "manual" else 1)
        ok = st.form_submit_button("Guardar parámetros", type="primary")
    if ok:
        def fn(d):
            nuevo = {**d["config"], "precio_venta": precio, "vol_prod": int(vol), "tc_usd": tc,
                     "costo_sobre": None if sin_costo else float(costo_sobre),
                     "conciliacion": {"prioridad": "manual" if prioridad.startswith("Conservar") else "plataforma"}}
            M.costos_catalogo(d["catalogo"], tc, int(vol))
            if nuevo != d["config"]:
                M.evento(d, "Configuración", d["config"], nuevo)
                d["config"] = nuevo
        ejecutar(fn, "Parámetros guardados.")


def config_canales_presentaciones():
    st.markdown("#### Canales")
    st.caption("Desactivar un canal lo oculta en capturas nuevas; sus ventas se conservan. Shopify está listo para usarse cuando tengas ventas ahí.")
    with st.form("canales"):
        dfc = st.data_editor(pd.DataFrame(cfg["canales"]), num_rows="dynamic", hide_index=True, width="stretch",
                             column_config={"Tipo": st.column_config.SelectboxColumn(options=["Marketplace", "Tienda en línea", "Directo"]),
                                            "Activo": st.column_config.CheckboxColumn()})
        ok_c = st.form_submit_button("Guardar canales")
    if ok_c:
        def fn(d):
            nuevos = [x for x in dfc.to_dict("records") if str(x.get("Nombre") or "").strip()]
            usados = {r["Canal"] for r in d["operaciones"]}
            faltan = usados - {x["Nombre"] for x in nuevos}
            if faltan:
                raise ValueError("No puedes borrar canales con ventas: " + ", ".join(sorted(faltan)) + ". Desactívalos en su lugar.")
            nuevos = [{"Nombre": x["Nombre"].strip(), "Activo": bool(x.get("Activo")), "Tipo": x.get("Tipo") or "Directo"} for x in nuevos]
            d["config"]["canales"] = nuevos
        ejecutar(fn, "Canales guardados.")
    st.markdown("#### Presentaciones")
    st.caption("Define cuántos sobres contiene cada presentación. Así se distinguen paquetes vendidos de sobres vendidos.")
    with st.form("presentaciones"):
        dfp = st.data_editor(pd.DataFrame(cfg["presentaciones"]), num_rows="dynamic", hide_index=True, width="stretch",
                             column_config={"Sobres": st.column_config.NumberColumn(min_value=1, step=1)})
        ok_p = st.form_submit_button("Guardar presentaciones")
    if ok_p:
        def fn(d):
            lista = validar_presentaciones(dfp.to_dict("records"))
            usadas = {r.get("Presentación") for r in d["operaciones"] if r.get("Presentación")}
            previas = {p["Nombre"]: p["Sobres"] for p in d["config"]["presentaciones"]}
            nuevas = {p["Nombre"]: p["Sobres"] for p in lista}
            for n in usadas:
                if n in previas and (n not in nuevas or nuevas[n] != previas[n]):
                    raise ValueError(f"«{n}» ya tiene ventas: no la borres ni cambies sus sobres; crea una presentación nueva.")
            d["config"]["presentaciones"] = lista
        ejecutar(fn, "Presentaciones guardadas.")
    st.markdown("#### SKU de plataformas")
    st.caption("Relaciona cada SKU de Mercado Libre o Amazon con una presentación. Un SKU sin relación queda en revisión y no se cuenta.")
    skus = [{"SKU": k, "Presentación": v} for k, v in cfg["skus"].items()] or [{"SKU": "", "Presentación": "Sobre individual"}]
    with st.form("skus"):
        dfs = st.data_editor(pd.DataFrame(skus), num_rows="dynamic", hide_index=True, width="stretch",
                             column_config={"Presentación": st.column_config.SelectboxColumn(options=list(presentaciones(datos)), required=True)})
        ok_s = st.form_submit_button("Guardar SKU")
    if ok_s:
        def fn(d):
            m = {}
            for x in dfs.to_dict("records"):
                s = str(x.get("SKU") or "").strip()
                if s:
                    if s in m:
                        raise ValueError(f"SKU repetido: {s}")
                    m[s] = x["Presentación"]
            d["config"]["skus"] = m
        ejecutar(fn, "SKU guardados. Los pedidos que esperaban relación se incorporarán en la próxima sincronización.")


def config_integraciones():
    from lv.integraciones import amazon, mercadolibre
    from lv.integraciones.estado import ESTADOS_LOCALES as E
    from lv.integraciones.estado import Estado
    from lv.integraciones.sincronizador import construir
    st.write("Conexión oficial con tus cuentas de vendedor. Las credenciales viven en variables de entorno o secretos del servidor, nunca en el código ni en los respaldos.")
    estado = Estado()
    cuentas = {c["plataforma"]: c for c in estado.cuentas()}
    for nombre, mod in (("Mercado Libre", mercadolibre), ("Amazon", amazon)):
        cta = cuentas.get(nombre)
        if not mod.configurada():
            situacion, nota = "Preparada, sin credenciales", "Integración lista en el código; falta configurar credenciales."
        elif cta and cta.get("comprobada") and cta.get("estado") != "Error":
            situacion, nota = "Sincronización comprobada", f"Última correcta: {cta.get('ultimo_ok')}"
        elif cta and cta.get("estado") == "Error":
            situacion, nota = "Con error", (cta.get("ultimo_error") or "")[:140]
        else:
            situacion, nota = "Credenciales configuradas", "Aún sin una sincronización correcta."
        ui.franja([{"etiqueta": nombre, "valor": situacion, "estado": "ok" if situacion == "Sincronización comprobada" else ("err" if situacion == "Con error" else "nd"), "nota": nota},
                   {"etiqueta": "Última sincronización correcta", "valor": (cta or {}).get("ultimo_ok"), "estado": "ok" if (cta or {}).get("ultimo_ok") else "nd"},
                   {"etiqueta": "Cursor incremental", "valor": (cta or {}).get("cursor"), "estado": "ok" if (cta or {}).get("cursor") else "nd",
                    "nota": "Hasta dónde se leyó" if (cta or {}).get("cursor") else "Falta la sincronización inicial"}])
    sinc = construir(repo, estado)
    if sinc.clientes:
        a, b = st.columns(2)
        with a:
            st.markdown("#### Sincronizar ahora")
            if st.button("Sincronizar ahora", type="primary"):
                with st.spinner("Consultando plataformas… Amazon limita el ritmo de consultas, puede tardar."):
                    for plat in sinc.clientes:
                        r = sinc.sincronizar(plat)
                        (st.success if r["estado"] == "Correcta" else st.warning)(f"{plat}: {r}")
                    sinc.procesar_cola()
        with b:
            st.markdown("#### Carga inicial del historial")
            d1 = st.date_input("Desde", date(hoy_local().year, 1, 1), key="int_desde",
                               help="Mercado Libre conserva órdenes de hasta 12 meses.")
            if st.button("Cargar historial"):
                with st.spinner("Cargando historial…"):
                    for plat in sinc.clientes:
                        r = sinc.sincronizar(plat, datetime(d1.year, d1.month, d1.day, tzinfo=ZONA), tipo="inicial")
                        (st.success if r["estado"] == "Correcta" else st.warning)(f"{plat}: {r}")
                heredados = [r["ID"] for r in repo.leer()[1]["operaciones"] if r.get("Canal") in sinc.clientes and not r.get("Fecha") and not r.get("Anulada")]
                if heredados:
                    st.warning("Revisa estos resúmenes heredados: cubren meses que ahora vienen de la plataforma. "
                               "Anúlalos después de verificar para no contarlos dos veces: " + ", ".join(heredados))
    resumen = estado.resumen()
    if resumen:
        st.markdown("#### Pedidos recibidos")
        st.dataframe(pd.DataFrame([{"Estado": k, "Partidas": v} for k, v in resumen.items()]), hide_index=True, width="stretch")
    revision_ = estado.pedidos([E["REV_DUP"], E["REV_CONFLICTO"], E["REV_OTRO"], E["REV_SKU"], E["REV_MONEDA"]])
    if revision_:
        st.markdown(f"#### Requieren tu decisión ({len(revision_)})")
        for p in revision_[:30]:
            n = p["normalizado"]
            with st.expander(f"{p['plataforma']} pedido {p['pedido']} · {n.get('fecha_pedido')} · {n.get('cantidad')} × {moneda(n.get('precio_unitario'), '')} · {p['estado_local']}"):
                st.write(p.get("mensaje") or "")
                a, b, c = st.columns(3)
                if a.button("Incorporar como venta nueva", key=f"inc_{p['clave']}"):
                    estado.decidir(p["clave"], "incorporar")
                    sinc.incorporar()
                    st.rerun()
                cand = [r["ID"] for r in datos["operaciones"] if r.get("Canal") == p["plataforma"] and not r.get("Anulada") and not r.get("Clave")]
                if cand:
                    v = b.selectbox("Vincular con", cand, key=f"vsel_{p['clave']}")
                    if b.button("Vincular (no duplica)", key=f"vin_{p['clave']}"):
                        estado.decidir(p["clave"], "vincular", v)
                        sinc.incorporar()
                        st.rerun()
                if c.button("Ignorar", key=f"ign_{p['clave']}"):
                    estado.decidir(p["clave"], "ignorar")
                    sinc.incorporar()
                    st.rerun()
    with st.expander("Bitácora de sincronización"):
        st.dataframe(pd.DataFrame(estado.corridas(30)), hide_index=True, width="stretch")
    with st.expander("Qué falta configurar"):
        st.markdown(
            "- **Mercado Libre**: crea una aplicación en el portal de developers, define `ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ML_SELLER_ID` y `ML_REDIRECT_URI`, "
            "autoriza la cuenta y ejecuta `python sync_worker.py --autorizar-ml CODIGO`. Para tiempo real, publica `webhook_ml.py` con HTTPS y suscribe el tópico *orders_v2*.\n"
            "- **Amazon**: registra una aplicación privada en Seller Central (rol de pedidos y finanzas), autorízala y define `AMZ_LWA_CLIENT_ID`, `AMZ_LWA_CLIENT_SECRET`, `AMZ_REFRESH_TOKEN` y `AMZ_SELLER_ID`.\n"
            "- **Proceso permanente**: `python sync_worker.py --continuo --minutos 15` en el mismo servidor que la base.")


def config_respaldos():
    st.download_button("Descargar respaldo completo (JSON)", respaldos.serializar(datos), f"respaldo_legado_verde_{hoy_local()}.json",
                       "application/json", type="primary", help="Incluye ventas, asientos, catálogo, configuración e historial. No incluye credenciales.")
    st.markdown("#### Restaurar un respaldo")
    archivo = st.file_uploader("Respaldo generado por este sistema", type=["json"], key=f"rest_{ss.get('rest_v', 0)}")
    if not archivo:
        return
    try:
        restaurado = json.loads(archivo.getvalue().decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        st.error(f"El archivo no es un JSON válido: {e}")
        return
    errores, resumen = respaldos.validar(restaurado, datos)
    st.dataframe(pd.DataFrame([{"Concepto": k, "Valor": v} for k, v in resumen.items()]), hide_index=True, width="stretch")
    if errores:
        st.error("El respaldo no pasó la validación; no se puede restaurar:\n\n- " + "\n- ".join(errores[:20]))
        return
    st.warning("Restaurar reemplaza todos los datos actuales del servidor. Antes se guardará una copia automática de la base actual.")
    conf = st.checkbox("Confirmo reemplazar los datos del servidor por este respaldo")
    if st.button("Restaurar respaldo", disabled=not conf):
        ruta = repo.respaldo_local(repo.leer()[1], "antes-de-restaurar")

        def fn(d):
            nuevo = copy.deepcopy(restaurado)
            M.evento(nuevo, "Restauración", None, {"Fecha": hoy_local().isoformat(), "Copia previa": str(ruta) if ruta else None})
            d.clear()
            d.update(nuevo)
        ss["rest_v"] = ss.get("rest_v", 0) + 1
        ejecutar(fn, f"Respaldo restaurado. Copia previa guardada en {ruta}.")


def config_almacenamiento():
    from lv.almacen_sql import descripcion_segura, url_base
    if url_base():
        st.success(f"Base de datos externa: {descripcion_segura(url_base())}. Los datos persisten aunque Streamlit se reinicie, "
                   "y el conector de voz de Claude escribe en esta misma base.")
        st.caption("La dirección completa de conexión es un secreto y no se muestra.")
        return
    ruta = ruta_base()
    st.write(f"Base de datos: `{ruta}`")
    temporal = any(s in ruta for s in ("/tmp", "/mount/src")) or bool(os.environ.get("STREAMLIT_SHARING_MODE")) \
        or os.environ.get("HOSTNAME", "").startswith("streamlit")
    if temporal:
        st.error("La base parece estar en un disco temporal (por ejemplo, Streamlit Community Cloud). "
                 "Los datos pueden perderse al reiniciar o redesplegar. Configura DATABASE_URL (PostgreSQL externo) en los secretos de la app.")
    else:
        st.info("Los datos persisten mientras esta ruta esté en un disco persistente del servidor. Descarga respaldos con regularidad.")
    st.caption("Las ventas se guardan con control de versión: si dos sesiones guardan a la vez, ninguna sobrescribe a la otra en silencio.")


def pagina_configuracion():
    encabezado("Configuración y respaldos", "Parámetros, canales, presentaciones, integraciones y respaldos.", boton=False)
    t1, t2, t3, t4, t5 = st.tabs(["Parámetros", "Canales y presentaciones", "Integraciones", "Respaldos", "Almacenamiento"])
    with t1:
        config_parametros()
    with t2:
        config_canales_presentaciones()
    with t3:
        config_integraciones()
    with t4:
        config_respaldos()
    with t5:
        config_almacenamiento()


{"Inicio": pagina_inicio, "Ventas": pagina_ventas, "Costos y gastos": pagina_costos, "Finanzas": pagina_finanzas,
 "Simulador": pagina_simulador, "Configuración y respaldos": pagina_configuracion}[pagina]()
