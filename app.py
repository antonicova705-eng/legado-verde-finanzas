import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Legado Verde - Tablero Financiero", layout="wide")

st.title("🌱 Legado Verde: Tablero de Rentabilidad y Punto de Equilibrio")
st.markdown("---")

# Barra lateral para entradas de datos
st.sidebar.header("Parámetros Operativos")

ventas_ml = st.sidebar.number_input(
    "Ventas Mercado Libre ($)", min_value=0.0, value=50000.0, step=1000.0
)
ventas_amz = st.sidebar.number_input(
    "Ventas Amazon ($)", min_value=0.0, value=75000.0, step=1000.0
)

st.sidebar.markdown("---")
costos_fijos = st.sidebar.number_input(
    "Costos Fijos Totales ($)", min_value=0.0, value=30000.0, step=1000.0
)
porcentaje_cv = st.sidebar.slider(
    "Costo Variable (% de las ventas)", min_value=10, max_value=90, value=40
)

# Cálculos dinámicos basados en las entradas del usuario
ventas_totales = ventas_ml + ventas_amz
costos_variables = ventas_totales * (porcentaje_cv / 100.0)
costos_totales = costos_fijos + costos_variables
utilidad_neta = ventas_totales - costos_totales
margen_utilidad = (
    (utilidad_neta / ventas_totales * 100) if ventas_totales > 0 else 0
)

# Punto de equilibrio teórico (asumiendo margen de contribución)
margen_contribucion_pct = 1.0 - (porcentaje_cv / 100.0)
punto_equilibrio = (
    costos_fijos / margen_contribucion_pct if margen_contribucion_pct > 0 else 0
)

# Métricas principales en la parte superior
col1, col2, col3, col4 = st.columns(4)
col1.metric("Ventas Totales", f"${ventas_totales:,.2f}")
col2.metric("Costos Totales", f"${costos_totales:,.2f}")
col3.metric("Utilidad Neta", f"${utilidad_neta:,.2f}", f"{margen_utilidad:.1f}%")
col4.metric("Punto de Equilibrio", f"${punto_equilibrio:,.2f}")

st.markdown("---")

# Sección de Gráficas con Plotly
col_g1, col_g2 = st.columns(2)

with col_g1:
  st.subheader("📊 Distribución de Ventas por Canal")
  fig_ventas = go.Figure(
      data=[
          go.Bar(
              x=["Mercado Libre", "Amazon"],
              y=[ventas_ml, ventas_amz],
              marker_color=["#ffe600", "#ff9900"],
          )
      ]
  )
  fig_ventas.update_layout(
      margin=dict(t=20, b=20, l=20, r=20),
      height=300,
      paper_bgcolor="rgba(0,0,0,0)",
      plot_bgcolor="rgba(0,0,0,0)",
  )
  st.plotly_chart(fig_ventas, use_container_width=True)

with col_g2:
  st.subheader("⚖️ Estructura Financiera")
  fig_fin = go.Figure(
      data=[
          go.Pie(
              labels=["Costos Fijos", "Costos Variables", "Utilidad Neta"],
              values=[
                  costos_fijos,
                  costos_variables,
                  max(0, utilidad_neta),
              ],  # Evita negativos visuales en pastel
              hole=0.4,
          )
      ]
  )
  fig_fin.update_layout(
      margin=dict(t=20, b=20, l=20, r=20),
      height=300,
      paper_bgcolor="rgba(0,0,0,0)",
      plot_bgcolor="rgba(0,0,0,0)",
  )
  st.plotly_chart(fig_fin, use_container_width+True)

st.success(
    "💡 Tablero conectado dinámicamente. Modifica los valores en la barra"
    " lateral para ver el impacto en tiempo real."
)
