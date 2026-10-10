import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Legado Verde - Catálogo de Costos & Finanzas",
    page_icon="🌱",
    layout="wide",
)

# Estilo visual corporativo (Verde profundo, oliva, beige)
st.markdown(
    """
    <style>
    .main { background-color: #F9F9F6; }
    .stMetric { background-color: #FFFFFF; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    </style>
""",
    unsafe_allow_html=True,
)

st.title("🌱 Legado Verde: Catálogo de Costos y Formación de Precios")
st.markdown(
    "*Módulo dinámico para la gestión de costos de producción, gastos fijos,"
    " márgenes y punto de equilibrio.*"
)
st.markdown("---")

# ==========================================
# INICIALIZACIÓN DE ESTADO (PERSISTENCIA SESIÓN)
# ==========================================
if "tc_usd" not in st.session_state:
  st.session_state.tc_usd = 20.00

if "vol_prod" not in st.session_state:
  st.session_state.vol_prod = 1000

if "sobres_caja" not in st.session_state:
  st.session_state.sobres_caja = 50

if "precio_venta" not in st.session_state:
  st.session_state.precio_venta = 60.00

if "catalogo_df" not in st.session_state:
  datos_iniciales = [
      {
          "Concepto": "Aguacates",
          "Área": "Producción",
          "Clasificación": "Variable",
          "Importe Base": 15000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Lote / Mes",
          "Estado": "Estimado",
      },
      {
          "Concepto": "Limón, sal, cebolla, cilantro, pimienta",
          "Área": "Producción",
          "Clasificación": "Variable",
          "Importe Base": 2000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Lote / Mes",
          "Estado": "Estimado",
      },
      {
          "Concepto": "Empaque del producto",
          "Área": "Producción",
          "Clasificación": "Variable",
          "Importe Base": 6.0,
          "Moneda": "MXN",
          "Frecuencia": "Por sobre",
          "Base Asignación": "Sobre",
          "Estado": "Confirmado",
      },
      {
          "Concepto": "Bolsitas antioxidantes",
          "Área": "Producción",
          "Clasificación": "Variable",
          "Importe Base": 0.75,
          "Moneda": "MXN",
          "Frecuencia": "Por sobre",
          "Base Asignación": "Sobre",
          "Estado": "Confirmado",
      },
      {
          "Concepto": "Cajas de empaque ($11/caja)",
          "Área": "Logística",
          "Clasificación": "Variable",
          "Importe Base": 0.22,
          "Moneda": "MXN",
          "Frecuencia": "Por sobre",
          "Base Asignación": "Sobre",
          "Estado": "Confirmado",
      },
      {
          "Concepto": "Tinta e impresión por envío",
          "Área": "Ventas",
          "Clasificación": "Variable",
          "Importe Base": 0.10,
          "Moneda": "MXN",
          "Frecuencia": "Por sobre",
          "Base Asignación": "Sobre",
          "Estado": "Confirmado",
      },
      {
          "Concepto": "Renta",
          "Área": "Administración",
          "Clasificación": "Fijo",
          "Importe Base": 9000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Mes",
          "Estado": "Confirmado",
      },
      {
          "Concepto": "Sueldos",
          "Área": "Administración",
          "Clasificación": "Fijo",
          "Importe Base": 8000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Mes",
          "Estado": "Estimado",
      },
      {
          "Concepto": "Electricidad",
          "Área": "Producción",
          "Clasificación": "Fijo",
          "Importe Base": 7000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Mes",
          "Estado": "Estimado",
      },
      {
          "Concepto": "Agua",
          "Área": "Producción",
          "Clasificación": "Fijo",
          "Importe Base": 250.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Mes",
          "Estado": "Confirmado",
      },
      {
          "Concepto": "Insumos y utensilios de limpieza",
          "Área": "Producción",
          "Clasificación": "Fijo",
          "Importe Base": 2000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Mes",
          "Estado": "Estimado",
      },
      {
          "Concepto": "Aceite Liofilizadora",
          "Área": "Producción",
          "Clasificación": "Fijo",
          "Importe Base": 2000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Mes",
          "Estado": "Estimado",
      },
      {
          "Concepto": "Filtro de aceite",
          "Área": "Producción",
          "Clasificación": "Fijo",
          "Importe Base": 800.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Mes",
          "Estado": "Estimado",
      },
      {
          "Concepto": "Shopify ($200 USD/año)",
          "Área": "Ventas",
          "Clasificación": "Fijo",
          "Importe Base": 333.33,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
          "Base Asignación": "Mes",
          "Estado": "Confirmado",
      },
  ]
  st.session_state.catalogo_df = pd.DataFrame(datos_iniciales)

# ==========================================
# BARRA LATERAL: PARÁMETROS OPERATIVOS
# ==========================================
st.sidebar.header("🎛️ Configuración General")
st.session_state.precio_venta = st.sidebar.number_input(
    "Precio de Venta Promedio ($)",
    min_value=1.0,
    value=float(st.session_state.precio_venta),
    step=1.0,
)
st.session_state.vol_prod = st.sidebar.number_input(
    "Volumen Producción Mensual (Sobres)",
    min_value=1,
    value=int(st.session_state.vol_prod),
    step=50,
)
st.session_state.sobres_caja = st.sidebar.number_input(
    "Sobres por Caja de Empaque",
    min_value=1,
    value=int(st.session_state.sobres_caja),
    step=5,
)
st.session_state.tc_usd = st.sidebar.number_input(
    "Tipo de Cambio (USD a MXN)",
    min_value=10.0,
    value=float(st.session_state.tc_usd),
    step=0.5,
)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Restablecer Catálogo Original"):
  st.session_state.pop("catalogo_df")
  st.rerun()

# ==========================================
# CATÁLOGO EDITABLE DE COSTOS
# ==========================================
st.subheader("📋 Catálogo Interactivo de Costos y Gastos")
st.markdown(
    "Edita directamente las celdas de la tabla para actualizar la estructura"
    " financiera en tiempo real:"
)

df_editado = st.data_editor(
    st.session_state.catalogo_df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Importe Base": st.column_config.NumberColumn(
            "Importe Base", format="$%.2f"
        ),
        "Moneda": st.column_config.SelectboxColumn("Moneda", options=["MXN", "USD"]),
        "Clasificación": st.column_config.SelectboxColumn(
            "Clasificación", options=["Fijo", "Variable"]
        ),
        "Frecuencia": st.column_config.SelectboxColumn(
            "Frecuencia", options=["Mensual", "Por sobre", "Anual"]
        ),
        "Estado": st.column_config.SelectboxColumn(
            "Estado", options=["Confirmado", "Estimado", "Pendiente"]
        ),
    },
)
st.session_state.catalogo_df = df_editado

# ==========================================
# CÁLCULOS DINÁMICOS
# ==========================================
cv_unitario_total = 0.0
cf_mensual_total = 0.0

for _, row in df_editado.iterrows():
  importe = float(row["Importe Base"])
  if row["Moneda"] == "USD":
    importe *= st.session_state.tc_usd

  if row["Clasificación"] == "Variable":
    if row["Frecuencia"] == "Mensual":
      cv_unitario_total += importe / st.session_state.vol_prod
    elif row["Frecuencia"] == "Por sobre":
      cv_unitario_total += importe
  elif row["Clasificación"] == "Fijo":
    if row["Frecuencia"] == "Mensual":
      cf_mensual_total += importe
    elif row["Frecuencia"] == "Anual":
      cf_mensual_total += importe / 12.0

# Métricas Principales
contribucion_unitaria = st.session_state.precio_venta - cv_unitario_total
margen_contribucion_pct = (
    (contribucion_unitaria / st.session_state.precio_venta)
    if st.session_state.precio_venta > 0
    else 0
)

pe_unidades = (
    int(np.ceil(cf_mensual_total / contribucion_unitaria))
    if contribucion_unitaria > 0
    else 0
)
pe_pesos = (
    cf_mensual_total / margen_contribucion_pct
    if margen_contribucion_pct > 0
    else 0
)

# ==========================================
# VISTA DE RESULTADOS Y KPIS
# ==========================================
st.markdown("---")
st.subheader("📊 Indicadores Financieros Calculados")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Costo Variable Unitario", f"${cv_unitario_total:,.2f}")
c2.metric("Costos Fijos Mensuales", f"${cf_mensual_total:,.2f}")
c3.metric(
    "Contribución Unitaria",
    f"${contribucion_unitaria:,.2f}",
    f"{margen_contribucion_pct*100:.1f}% Margen",
)
c4.metric(
    "Punto de Equilibrio", f"{pe_unidades:,} sobres", f"${pe_pesos:,.2f} MXN"
)

# Gráfica de Punto de Equilibrio
st.markdown("---")
st.subheader("📈 Gráfica de Punto de Equilibrio")

rango_unidades = np.linspace(0, max(pe_unidades * 2, 2000), 100)
ventas_linea = rango_unidades * st.session_state.precio_venta
costos_totales_linea = cf_mensual_total + (rango_unidades * cv_unitario_total)

fig_pe = go.Figure()
fig_pe.add_trace(
    go.Scatter(
        x=rango_unidades,
        y=ventas_linea,
        mode="lines",
        name="Ventas Totales",
        line=dict(color="#2d6a4f", width=3),
    )
)
fig_pe.add_trace(
    go.Scatter(
        x=rango_unidades,
        y=costos_totales_linea,
        mode="lines",
        name="Costos Totales",
        line=dict(color="#d90429", width=3),
    )
)
fig_pe.add_trace(
    go.Scatter(
        x=[pe_unidades],
        y=[pe_pesos],
        mode="markers+text",
        name="Punto de Equilibrio",
        text=[f"Equilibrio: {pe_unidades} un."],
        textposition="top left",
        marker=dict(size=12, color="#ffb703"),
    )
)

fig_pe.update_layout(
    xaxis_title="Sobres Vendidos",
    yaxis_title="Pesos ($ MXN)",
    height=400,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(fig_pe, use_container_width=True)

# Exportación y Resguardo
st.markdown("---")
csv_data = df_editado.to_csv(index=False).encode("utf-8")
st.download_button(
    "📥 Exportar Catálogo de Costos (CSV)",
    data=csv_data,
    file_name="catalogo_costos_legado_verde.csv",
    mime="text/csv",
)
