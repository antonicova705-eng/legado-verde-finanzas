import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ==========================================
# CONFIGURACIÓN DE PÁGINA Y ESTILO VISUAL
# ==========================================
st.set_page_config(
    page_title="Legado Verde - Tablero Financiero Unificado",
    page_icon="🌱",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main { background-color: #F9F9F6; }
    .stMetric { background-color: #FFFFFF; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    </style>
""",
    unsafe_allow_html=True,
)

st.title("🌱 Legado Verde: Sistema Financiero Inteligente")
st.markdown(
    "*Plataforma unificada: Histórico de operaciones, catálogo de costos dinámico"
    " y análisis de rentabilidad.*"
)
st.markdown("---")

# ==========================================
# INICIALIZACIÓN DE ESTADO (PERSISTENCIA)
# ==========================================
if "tc_usd" not in st.session_state:
  st.session_state.tc_usd = 20.00

if "vol_prod" not in st.session_state:
  st.session_state.vol_prod = 1000

if "precio_venta" not in st.session_state:
  st.session_state.precio_venta = 60.00

# Catálogo Editable de Costos (Nueva App)
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
          "Concepto": "Cajas de empaque ($11/caja, 50 sobres)",
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
          "Concepto": "Shopify ($200 USD/año prorrateado)",
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

# Datos Históricos (App Anterior)
if "historico_df" not in st.session_state:
  data_hist = [
      {
          "Mes": "Julio 2026",
          "Canal": "Mercado Libre",
          "Ventas Producto": 1341.0,
          "Remanente Reportado": 450.90,
          "Estado": "Validado",
      },
      {
          "Mes": "Agosto 2026",
          "Canal": "Mercado Libre",
          "Ventas Producto": 1044.0,
          "Remanente Reportado": 538.88,
          "Estado": "Validado",
      },
      {
          "Mes": "Septiembre 2026",
          "Canal": "Mercado Libre",
          "Ventas Producto": 1342.0,
          "Remanente Reportado": 873.92,
          "Estado": "Validado",
      },
      {
          "Mes": "Octubre 2026 (Parcial)",
          "Canal": "Mercado Libre",
          "Ventas Producto": 895.0,
          "Remanente Reportado": 638.40,
          "Estado": "Parcial / En Camino",
      },
      {
          "Mes": "Julio - Sept 2026",
          "Canal": "Amazon",
          "Ventas Producto": 420.0,
          "Remanente Reportado": -75.67,
          "Estado": "Resumen Global",
      },
      {
          "Mes": "Pendiente de Fechar",
          "Canal": "Cafeterías",
          "Ventas Producto": 15000.0,
          "Remanente Reportado": 15000.0,
          "Estado": "Pendiente Fechas",
      },
  ]
  st.session_state.historico_df = pd.DataFrame(data_hist)

# ==========================================
# BARRA LATERAL: NAVEGACIÓN Y PARÁMETROS
# ==========================================
st.sidebar.header("🎛️ Panel de Control")
menu = st.sidebar.radio(
    "Selecciona una sección:",
    [
        "📊 Resumen Ejecutivo",
        "📋 Catálogo de Costos",
        "📈 Histórico y Canales",
        "🔮 Simulador de Escenarios",
    ],
)

st.sidebar.markdown("---")
st.sidebar.subheader("Parámetros Globales")
st.session_state.precio_venta = st.sidebar.number_input(
    "Precio Venta Promedio ($)",
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
st.session_state.tc_usd = st.sidebar.number_input(
    "Tipo de Cambio USD/MXN",
    min_value=10.0,
    value=float(st.session_state.tc_usd),
    step=0.5,
)

# ==========================================
# CÁLCULOS AUTOMÁTICOS DESDE EL CATÁLOGO
# ==========================================
cv_unitario_total = 0.0
cf_mensual_total = 0.0

df_cat = st.session_state.catalogo_df
for _, row in df_cat.iterrows():
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

# Ventas totales registradas históricamente (excluyendo pendientes o sumando según criterio)
ventas_historicas_totales = st.session_state.historico_df[
    st.session_state.historico_df["Estado"] != "Pendiente Fechas"
]["Ventas Producto"].sum()

# ==========================================
# VISTA 1: RESUMEN EJECUTIVO
# ==========================================
if menu == "📊 Resumen Ejecutivo":
  st.subheader("📊 Resumen Ejecutivo & Estado Operativo")

  col1, col2, col3, col4, col5 = st.columns(5)
  col1.metric("Ventas Históricas", f"${ventas_historicas_totales:,.2f}")
  col2.metric("Costo Variable Unit.", f"${cv_unitario_total:,.2f}")
  col3.metric("Gastos Fijos Mensuales", f"${cf_mensual_total:,.2f}")
  col4.metric(
      "Punto de Equilibrio",
      f"{pe_unidades:,} sobres",
      f"${pe_pesos:,.2f} MXN",
  )
  col5.metric(
      "Margen Contribución",
      f"{margen_contribucion_pct*100:.1f}%",
      f"${contribucion_unitaria:,.2f} u.",
  )

  st.markdown("---")

  col_g1, col_g2 = st.columns(2)
  with col_g1:
    st.subheader("⚖️ Estructura de Costos y Margen")
    fig_est = go.Figure(
        data=[
            go.Pie(
                labels=[
                    "Costos Fijos Asignados",
                    "Costos Variables Totales",
                    "Margen de Contribución",
                ],
                values=[
                    cf_mensual_total,
                    cv_unitario_total * st.session_state.vol_prod,
                    max(0, contribucion_unitaria * st.session_state.vol_prod),
                ],
                hole=0.4,
                marker_colors=["#1b4332", "#2d6a4f", "#95d5b2"],
            )
        ]
    )
    fig_est.update_layout(height=320, margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig_est, use_container_width=True)

  with col_g2:
    st.subheader("📈 Gráfica de Punto de Equilibrio Dinámica")
    rango_u = np.linspace(0, max(pe_unidades * 2, 1500), 100)
    v_linea = rango_u * st.session_state.precio_venta
    c_linea = cf_mensual_total + (rango_u * cv_unitario_total)

    fig_pe = go.Figure()
    fig_pe.add_trace(
        go.Scatter(
            x=rango_u,
            y=v_linea,
            name="Ventas Totales",
            line=dict(color="#2d6a4f", width=3),
        )
    )
    fig_pe.add_trace(
        go.Scatter(
            x=rango_u,
            y=c_linea,
            name="Costos Totales",
            line=dict(color="#d90429", width=3),
        )
    )
    fig_pe.add_trace(
        go.Scatter(
            x=[pe_unidades],
            y=[pe_pesos],
            name="Equilibrio",
            marker=dict(size=12, color="#ffb703"),
        )
    )
    fig_pe.update_layout(
        height=320,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Sobres",
        yaxis_title="MXN",
    )
    st.plotly_chart(fig_pe, use_container_width=True)

# ==========================================
# VISTA 2: CATÁLOGO DE COSTOS
# ==========================================
elif menu == "📋 Catálogo de Costos":
  st.subheader("📋 Catálogo Interactivo de Costos y Formación de Precios")
  st.markdown(
      "Modifica los valores directamente en la tabla. Los cambios actualizarán"
      " instantáneamente los cálculos financieros."
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

  st.markdown("---")
  csv_bytes = df_editado.to_csv(index=False).encode("utf-8")
  st.download_button(
      "📥 Exportar Catálogo de Costos (CSV)",
      data=csv_bytes,
      file_name="catalogo_costos_legado_verde.csv",
      mime="text/csv",
  )

# ==========================================
# VISTA 3: HISTÓRICO Y CANALES
# ==========================================
elif menu == "📈 Histórico y Canales":
  st.subheader("📈 Registro Histórico Consolidado (Julio - Octubre 2026)")
  st.markdown(
      "Información de transacciones por plataforma, excluyendo cancelaciones y"
      " segregando pedidos en camino."
  )

  st.dataframe(st.session_state.historico_df, use_container_width=True)

  st.markdown("---")
  st.subheader("🌐 Ventas Acumuladas por Canal")

  df_canales = (
      st.session_state.historico_df.groupby("Canal")["Ventas Producto"]
      .sum()
      .reset_index()
  )
  fig_c = go.Figure(
      data=[
          go.Bar(
              x=df_canales["Canal"],
              y=df_canales["Ventas Producto"],
              marker_color=["#2d6a4f", "#40916c", "#52b788"],
          )
      ]
  )
  fig_c.update_layout(
      height=350, margin=dict(t=20, b=20, l=20, r=20), yaxis_title="MXN"
  )
  st.plotly_chart(fig_c, use_container_width=True)

# ==========================================
# VISTA 4: SIMULADOR DE ESCENARIOS
# ==========================================
elif menu == "🔮 Simulador de Escenarios":
  st.subheader("🔮 Simulador Financiero Proforma")

  escenario = st.selectbox(
      "Selecciona un escenario de proyección:",
      [
          "Base (Volumen actual)",
          "Conservador (Ventas -15%)",
          "Optimista (Ventas +20%)",
      ],
  )

  mult = 1.0
  if "Conservador" in escenario:
    mult = 0.85
  elif "Optimista" in escenario:
    mult = 1.20

  vol_proy = int(st.session_state.vol_prod * mult)
  ventas_proy = vol_proy * st.session_state.precio_venta
  costos_var_proy = vol_proy * cv_unitario_total
  costos_tot_proy = cf_mensual_total + costos_var_proy
  utilidad_proy = ventas_proy - costos_tot_proy

  sc1, sc2, sc3, sc4 = st.columns(4)
  sc1.metric("Volumen Proyectado", f"{vol_proy:,} sobres")
  sc2.metric("Ventas Proyectadas", f"${ventas_proy:,.2f}")
  sc3.metric("Costos Totales", f"${costos_tot_proy:,.2f}")
  sc4.metric(
      "Utilidad Neta Operativa",
      f"${utilidad_proy:,.2f}",
      f"{(utilidad_proy/ventas_proy*100) if ventas_proy>0 else 0:.1f}%",
  )

  st.markdown("---")
  st.success(
      "✨ El simulador utiliza en tiempo real los costos definidos en el"
      " catálogo interactivo."
  )
