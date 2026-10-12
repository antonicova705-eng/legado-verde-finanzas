import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ==========================================
# CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="Legado Verde - Sistema Financiero",
    page_icon="🥑",
    layout="wide",
)

# Estilos visuales institucionales
st.markdown(
    """
    <style>
    .stApp { background-color: #F4F0EA; }
    h1, h2, h3, .stSubheader { color: #0B5127 !important; font-family: 'Georgia', serif; }
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #8EB712;
    }
    .stButton>button {
        background-color: #0B5127 !important;
        color: white !important;
        border-radius: 6px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# Logo y Título
st.sidebar.image(
    "https://drive.google.com/thumbnail?id=1j9PfF082J_VzWP2bQURgQw8BVgeI3aK9&sz=w1000",
    use_container_width=True,
)
st.sidebar.markdown("---")
modulo = st.sidebar.radio(
    "Navegación",
    [
        "📊 Resumen Ejecutivo",
        "🌐 Ventas por Canal",
        "📋 Catálogo de Costos",
        "🔮 Simulador",
    ],
)

st.title("🌱 Legado Verde: Sistema Financiero Inteligente")
st.markdown(
    "*Tablero gerencial para control de costos, ventas y punto de equilibrio.*"
)
st.markdown("---")

# ==========================================
# ESTADO INICIAL
# ==========================================
if "precio_venta" not in st.session_state:
  st.session_state.precio_venta = 60.0
if "vol_prod" not in st.session_state:
  st.session_state.vol_prod = 1000
if "tc_usd" not in st.session_state:
  st.session_state.tc_usd = 20.0

if "catalogo" not in st.session_state:
  st.session_state.catalogo = pd.DataFrame([
      {
          "Concepto": "Aguacates",
          "Clasificación": "Variable",
          "Importe": 15000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Insumos (Limón, sal, etc.)",
          "Clasificación": "Variable",
          "Importe": 2000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Empaque por sobre",
          "Clasificación": "Variable",
          "Importe": 6.0,
          "Moneda": "MXN",
          "Frecuencia": "Por sobre",
      },
      {
          "Concepto": "Bolsita antioxidante",
          "Clasificación": "Variable",
          "Importe": 0.75,
          "Moneda": "MXN",
          "Frecuencia": "Por sobre",
      },
      {
          "Concepto": "Renta",
          "Clasificación": "Fijo",
          "Importe": 9000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Sueldos",
          "Clasificación": "Fijo",
          "Importe": 8000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Electricidad",
          "Clasificación": "Fijo",
          "Importe": 7000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Agua",
          "Clasificación": "Fijo",
          "Importe": 250.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Limpieza y Varios",
          "Clasificación": "Fijo",
          "Importe": 2000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Mantenimiento Aceite",
          "Clasificación": "Fijo",
          "Importe": 2000.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Filtro de aceite",
          "Clasificación": "Fijo",
          "Importe": 800.0,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
      {
          "Concepto": "Shopify (Prorr. anual)",
          "Clasificación": "Fijo",
          "Importe": 333.33,
          "Moneda": "MXN",
          "Frecuencia": "Mensual",
      },
  ])

if "ventas" not in st.session_state:
  st.session_state.ventas = pd.DataFrame([
      {
          "Mes": "Julio 2026",
          "Canal": "Mercado Libre",
          "Cantidad": 22,
          "Ventas": 1341.0,
          "Estado": "Activo",
      },
      {
          "Mes": "Agosto 2026",
          "Canal": "Mercado Libre",
          "Cantidad": 17,
          "Ventas": 1044.0,
          "Estado": "Activo",
      },
      {
          "Mes": "Septiembre 2026",
          "Canal": "Mercado Libre",
          "Cantidad": 22,
          "Ventas": 1342.0,
          "Estado": "Activo",
      },
      {
          "Mes": "Octubre 2026",
          "Canal": "Mercado Libre",
          "Cantidad": 15,
          "Ventas": 895.0,
          "Estado": "Activo",
      },
      {
          "Mes": "Julio - Sept 2026",
          "Canal": "Amazon",
          "Cantidad": 7,
          "Ventas": 420.0,
          "Estado": "Activo",
      },
      {
          "Mes": "Pendiente",
          "Canal": "Cafeterías",
          "Cantidad": 250,
          "Ventas": 15000.0,
          "Estado": "Activo",
      },
  ])

# ==========================================
# CÁLCULOS FINANCIEROS
# ==========================================
cv_tot = 0.0
cf_tot = 0.0

for _, r in st.session_state.catalogo.iterrows():
  imp = float(r["Importe"])
  if r["Moneda"] == "USD":
    imp *= st.session_state.tc_usd

  if r["Clasificación"] == "Variable":
    if r["Frecuencia"] == "Mensual":
      cv_tot += imp / st.session_state.vol_prod
    else:
      cv_tot += imp
  else:
    if r["Frecuencia"] == "Mensual":
      cf_tot += imp
    elif r["Frecuencia"] == "Anual":
      cf_tot += imp / 12.0

contribucion = st.session_state.precio_venta - cv_tot
margen_pct = (
    (contribucion / st.session_state.precio_venta)
    if st.session_state.precio_venta > 0
    else 0
)
pe_unidades = (
    int(np.ceil(cf_tot / contribucion)) if contribucion > 0 else 0
)
pe_pesos = cf_tot / margen_pct if margen_pct > 0 else 0

# ==========================================
# MÓDULOS
# ==========================================
if modulo == "📊 Resumen Ejecutivo":
  st.subheader("📊 Resumen Ejecutivo")

  c1, c2, c3, c4 = st.columns(4)
  c1.metric("Costo Variable Unit.", f"${cv_tot:,.2f}")
  c2.metric("Gastos Fijos Mes", f"${cf_tot:,.2f}")
  c3.metric("Margen Contribución", f"{margen_pct*100:.1f}%")
  c4.metric(
      "Punto de Equilibrio", f"{pe_unidades:,} sobres", f"${pe_pesos:,.2f}"
  )

  st.markdown("---")

  # Ventas totales actuales filtradas
  df_v = st.session_state.ventas[
      st.session_state.ventas["Estado"] == "Activo"
  ]
  total_ventas = df_v["Ventas"].sum()
  total_unidades = int(df_v["Cantidad"].sum())

  col_g1, col_g2 = st.columns(2)
  with col_g1:
    st.subheader("🌐 Ventas por Canal")
    df_c = df_v.groupby("Canal")["Ventas"].sum().reset_index()
    fig_c = go.Figure(
        data=[
            go.Bar(
                x=df_c["Canal"], y=df_c["Ventas"], marker_color="#0B5127"
            )
        ]
    )
    fig_c.update_layout(height=300, margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig_c, use_container_width=True)

  with col_g2:
    st.subheader("📈 Punto de Equilibrio & Avance Actual")
    rango_u = np.linspace(
        0, max(pe_unidades * 2, total_unidades * 1.5, 1200), 100
    )
    v_linea = rango_u * st.session_state.precio_venta
    c_linea = cf_tot + (rango_u * cv_tot)

    fig_pe = go.Figure()
    fig_pe.add_trace(
        go.Scatter(
            x=rango_u,
            y=v_linea,
            name="Ventas Totales",
            line=dict(color="#0B5127", width=3),
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
            marker=dict(size=12, color="#8EB712"),
        )
    )
    fig_pe.add_trace(
        go.Scatter(
            x=[total_unidades],
            y=[total_ventas],
            mode="markers+text",
            name="Avance Actual",
            text=[f"Avance: {total_unidades} un."],
            textposition="top right",
            marker=dict(size=14, color="#1b4332", symbol="diamond"),
        )
    )
    fig_pe.update_layout(height=300, margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig_pe, use_container_width=True)

elif modulo == "🌐 Ventas por Canal":
  st.subheader("🌐 Registro de Ventas")
  st.dataframe(st.session_state.ventas, use_container_width=True)

  with st.form("nueva_v"):
    nc = st.selectbox(
        "Canal", ["Mercado Libre", "Amazon", "Cafeterías", "Venta directa"]
    )
    nm = st.text_input("Mes", "Octubre 2026")
    ncan = st.number_input("Cantidad de sobres", min_value=1, value=50)
    nimp = st.number_input("Importe Ventas ($)", min_value=0.0, value=3000.0)
    if st.form_submit_button("Guardar Venta"):
      nueva = pd.DataFrame([{
          "Mes": nm,
          "Canal": nc,
          "Cantidad": ncan,
          "Ventas": nimp,
          "Estado": "Activo",
      }])
      st.session_state.ventas = pd.concat(
          [st.session_state.ventas, nueva], ignore_index=True
      )
      st.success("¡Venta agregada con éxito!")
      st.rerun()

elif modulo == "📋 Catálogo de Costos":
  st.subheader("📋 Catálogo y Parámetros")
  c1, c2, c3 = st.columns(3)
  with c1:
    st.session_state.precio_venta = st.number_input(
        "Precio Venta Promedio", value=float(st.session_state.precio_venta)
    )
  with c2:
    st.session_state.vol_prod = st.number_input(
        "Volumen Producción Mensual", value=int(st.session_state.vol_prod)
    )
  with c3:
    st.session_state.tc_usd = st.number_input(
        "Tipo de Cambio USD", value=float(st.session_state.tc_usd)
    )

  st.markdown("---")
  st.session_state.catalogo = st.data_editor(
      st.session_state.catalogo, num_rows="dynamic", use_container_width=True
  )

elif modulo == "🔮 Simulador":
  st.subheader("🔮 Simulador de Escenarios")
  esc = st.selectbox(
      "Escenario", ["Base (100%)", "Conservador (-15%)", "Optimista (+20%)"]
  )
  mult = 0.85 if "Conservador" in esc else (1.20 if "Optimista" in esc else 1.0)

  vp = int(st.session_state.vol_prod * mult)
  vt = vp * st.session_state.precio_venta
  ct = cf_tot + (vp * cv_tot)
  ut = vt - ct

  s1, s2, s3 = st.columns(3)
  s1.metric("Ventas Proyectadas", f"${vt:,.2f}")
  s2.metric("Costos Totales", f"${ct:,.2f}")
  s3.metric("Utilidad Proyectada", f"${ut:,.2f}")
