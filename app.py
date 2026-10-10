import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Configuración de página
st.set_page_config(
    page_title="Legado Verde - Tablero Financiero",
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

st.title(
    "🌱 Legado Verde: Tablero Financiero & Inteligencia Operativa (MBA CUCEA)"
)
st.markdown(
    "*Módulo central para la automatización de rentabilidad, punto de"
    " equilibrio y análisis de escenarios.*"
)
st.markdown("---")

# ==========================================
# 1. BARRA LATERAL: PARÁMETROS Y SUPUESTOS
# ==========================================
st.sidebar.header("🎛️ Parámetros y Supuestos Operativos")

st.sidebar.subheader("Precios y Costos Unitarios")
precio_unitario = st.sidebar.number_input(
    "Precio promedio por unidad ($)",
    min_value=1.0,
    value=60.0,
    step=1.0,
    help="Precio por presentación de 40g.",
)
costo_variable_unitario = st.sidebar.number_input(
    "Costo variable unitario ($)",
    min_value=0.0,
    value=45.0,
    step=1.0,
    help="Incluye insumos, empaque y mermas directas.",
)

st.sidebar.subheader("Gastos Fijos Mensuales")
gastos_fijos = st.sidebar.number_input(
    "Gastos Fijos Totales ($)",
    min_value=0.0,
    value=35000.0,
    step=1000.0,
    help=(
        "Incluye sueldos, renta, software, etc. (Pendiente validar"
        " devengados)."
    ),
)

st.sidebar.subheader("Ventas por Canal (Mes Actual)")
ventas_ml = st.sidebar.number_input(
    "Ventas Mercado Libre ($)", min_value=0.0, value=3727.0, step=100.0
)
ventas_amz = st.sidebar.number_input(
    "Ventas Amazon ($)", min_value=0.0, value=684.18, step=100.0
)
ventas_cafeterias = st.sidebar.number_input(
    "Ventas Cafeterías ($)",
    min_value=0.0,
    value=15000.0,
    step=100.0,
    help="Pendiente fechar y documentar unidades exactas.",
)
ventas_directa = st.sidebar.number_input(
    "Venta Directa ($)", min_value=0.0, value=0.0, step=100.0
)

# ==========================================
# 2. MODELO DE CÁLCULOS FINANCIEROS
# ==========================================
# Contribución unitaria y márgenes
contribucion_unitaria = precio_unitario - costo_variable_unitario
margen_contribucion_pct = (
    (contribucion_unitaria / precio_unitario) if precio_unitario > 0 else 0
)

# Ventas totales efectivas
ventas_totales = (
    ventas_ml + ventas_amz + ventas_cafeterias + ventas_directa
)

# Unidades estimadas equivalentes basadas en ventas totales y precio promedio
unidades_estimadas = (
    int(ventas_totales / precio_unitario) if precio_unitario > 0 else 0
)
costos_variables_totales = unidades_estimadas * costo_variable_unitario

costos_totales = gastos_fijos + costos_variables_totales
utilidad_neta = ventas_totales - costos_totales
margen_utilidad = (
    (utilidad_neta / ventas_totales * 100) if ventas_totales > 0 else 0
)

# Punto de equilibrio
punto_equilibrio_ventas = (
    gastos_fijos / margen_contribucion_pct
    if margen_contribucion_pct > 0
    else 0
)
punto_equilibrio_unidades = (
    int(round(gastos_fijos / contribucion_unitaria, 0))
    if contribucion_unitaria > 0
    else 0
)

# Brecha respecto a la meta de equilibrio
brecha_ventas = max(0.0, punto_equilibrio_ventas - ventas_totales)
brecha_pct = (
    (brecha_ventas / punto_equilibrio_ventas * 100)
    if punto_equilibrio_ventas > 0
    else 0
)
brecha_unidades = max(0, punto_equilibrio_unidades - unidades_estimadas)

# ==========================================
# 3. VISTA: RESUMEN EJECUTIVO (KPIs)
# ==========================================
st.header("📊 Resumen Ejecutivo & Estado de Integridad")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Ventas Totales", f"${ventas_totales:,.2f}")
col2.metric("Contribución Unit.", f"${contribucion_unitaria:,.2f}")
col3.metric("Margen de Cont.", f"{margen_contribucion_pct*100:.1f}%")
col4.metric(
    "Punto de Equilibrio",
    f"${punto_equilibrio_ventas:,.2f}",
    f"{punto_equilibrio_unidades} un.",
)
col5.metric(
    "Brecha Actual",
    f"${brecha_ventas:,.2f}",
    f"-{brecha_unidades} un.",
    delta_color="inverse",
)

st.markdown("---")

# ==========================================
# 4. VISUALIZACIÓN Y ANÁLISIS DE CANALES
# ==========================================
col_g1, col_g2 = st.columns(2)

with col_g1:
  st.subheader("🌐 Aporte de Ventas por Canal")
  df_canales = pd.DataFrame({
      "Canal": [
          "Mercado Libre",
          "Amazon",
          "Cafeterías (Pendiente)",
          "Venta Directa",
      ],
      "Ventas": [
          ventas_ml,
          ventas_amz,
          ventas_cafeterias,
          ventas_directa,
      ],
  })
  fig_canales = go.Figure(
      data=[
          go.Bar(
              x=df_canales["Canal"],
              y=df_canales["Ventas"],
              marker_color=["#2d6a4f", "#40916c", "#52b788", "#74c69d"],
          )
      ]
  )
  fig_canales.update_layout(
      margin=dict(t=20, b=20, l=20, r=20),
      height=320,
      paper_bgcolor="rgba(0,0,0,0)",
      plot_bgcolor="rgba(0,0,0,0)",
  )
  st.plotly_chart(fig_canales, use_container_width=True)

with col_g2:
  st.subheader("⚖️ Estructura de Costos y Resultado")
  fig_estructura = go.Figure(
      data=[
          go.Pie(
              labels=["Costos Fijos", "Costos Variables", "Utilidad / Pérdida"],
              values=[
                  gastos_fijos,
                  costos_variables_totales,
                  max(0, utilidad_neta),
              ],
              hole=0.4,
              marker_colors=["#1b4332", "#2d6a4f", "#95d5b2"],
          )
      ]
  )
  fig_estructura.update_layout(
      margin=dict(t=20, b=20, l=20, r=20),
      height=320,
      paper_bgcolor="rgba(0,0,0,0)",
      plot_bgcolor="rgba(0,0,0,0)",
  )
  st.plotly_chart(fig_estructura, use_container_width=True)

st.markdown("---")

# ==========================================
# 5. MÓDULO DE ESCENARIOS (Proforma)
# ==========================================
st.header("🔮 Simulador de Escenarios Estratégicos")
st.markdown(
    "Modifica los factores clave para evaluar el impacto en la utilidad y el"
    " punto de equilibrio."
)

escenario_op = st.selectbox(
    "Selecciona un escenario preconfigurado o personaliza en la barra"
    " lateral:",
    [
        "Personalizado (Barra lateral)",
        "Conservador (Ventas -15%)",
        "Base (Sin cambios)",
        "Optimista (Ventas +20%)",
    ],
)

multiplicador = 1.0
if "Conservador" in escenario_op:
  multiplicador = 0.85
elif "Optimista" in escenario_op:
  multiplicador = 1.20

ventas_escenario = ventas_totales * multiplicador
costos_var_escenario = ventas_escenario * (
    costos_variables_totales / ventas_totales
    if ventas_totales > 0
    else (costo_variable_unitario / precio_unitario)
)
utilidad_escenario = ventas_escenario - (gastos_fijos + costos_var_escenario)

ec1, ec2, ec3 = st.columns(3)
ec1.metric("Ventas Proyectadas", f"${ventas_escenario:,.2f}")
ec2.metric(
    "Utilidad Proyectada",
    f"${utilidad_escenario:,.2f}",
    f"{ (utilidad_escenario/ventas_escenario*100) if ventas_escenario>0 else 0:.1f}%",
)
ec3.metric(
    "Unidades Reales Equiv.", f"{int(ventas_escenario/precio_unitario)}"
)

st.markdown("---")

# ==========================================
# 6. FUENTES, DATOS FALTANTES Y AUDITORÍA
# ==========================================
st.subheader("🔍 Auditoría de Datos y Elementos Pendientes de Validación")
st.markdown("""
- **Mercado Libre:** Conciliado de julio a octubre (excluyendo pedidos en camino y cancelaciones). Pedido en camino de $895 segregado correctamente.
- **Amazon:** Resumen julio-septiembre incorporado ($684.18 ingresos reportados, comisiones y retenciones identificadas por separado).
- **Cafeterías:** Importe reportado de **$15,000** mantenido en bloque estanco pendiente de distribución temporal por falta de fechas exactas y unidades.
- **Gastos Fijos:** $35,000 sujetos a validación de devengado real frente a presupuesto inicial.
""")

st.success(
    "✨ Tablero sincronizado en tiempo real. Cualquier cambio en los controles"
    " laterales recalcula de forma exacta los indicadores financieros."
)
