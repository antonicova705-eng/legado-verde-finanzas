from datetime import date
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
    "*Plataforma unificada: Histórico de operaciones, ventas por canal,"
    " catálogo de costos y análisis de rentabilidad.*"
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

# Catálogo Editable de Costos
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

# Base de Operaciones / Ventas por Canal detalladas
if "operaciones_df" not in st.session_state:
  ops_iniciales = [
      {
          "ID": "ML-001",
          "Mes": "Julio 2026",
          "Canal": "Mercado Libre",
          "Referencia": "ML-JUL-01",
          "Producto": "Guacamole Liofilizado 40g",
          "Cantidad": 22,
          "Ventas Producto": 1341.0,
          "Remanente": 450.90,
          "Ingresos Envío": 0.0,
          "Comisiones": 150.0,
          "Costos Logísticos": 0.0,
          "Ajustes": 0.0,
          "Estado": "Entregado",
      },
      {
          "ID": "ML-002",
          "Mes": "Agosto 2026",
          "Canal": "Mercado Libre",
          "Referencia": "ML-AGO-01",
          "Producto": "Guacamole Liofilizado 40g",
          "Cantidad": 17,
          "Ventas Producto": 1044.0,
          "Remanente": 538.88,
          "Ingresos Envío": 0.0,
          "Comisiones": 120.0,
          "Costos Logísticos": 0.0,
          "Ajustes": 0.0,
          "Estado": "Entregado",
      },
      {
          "ID": "ML-003",
          "Mes": "Septiembre 2026",
          "Canal": "Mercado Libre",
          "Referencia": "ML-SEP-01",
          "Producto": "Guacamole Liofilizado 40g",
          "Cantidad": 22,
          "Ventas Producto": 1342.0,
          "Remanente": 873.92,
          "Ingresos Envío": 0.0,
          "Comisiones": 150.0,
          "Costos Logísticos": 0.0,
          "Ajustes": 0.0,
          "Estado": "Entregado",
      },
      {
          "ID": "ML-004",
          "Mes": "Octubre 2026 (Parcial)",
          "Canal": "Mercado Libre",
          "Referencia": "ML-OCT-01",
          "Producto": "Guacamole Liofilizado 40g",
          "Cantidad": 15,
          "Ventas Producto": 895.0,
          "Remanente": 638.40,
          "Ingresos Envío": 0.0,
          "Comisiones": 95.0,
          "Costos Logísticos": 0.0,
          "Ajustes": 0.0,
          "Estado": "En Camino",
      },
      {
          "ID": "AMZ-001",
          "Mes": "Julio - Sept 2026",
          "Canal": "Amazon",
          "Referencia": "AMZ-RESUMEN",
          "Producto": "Guacamole Liofilizado 40g",
          "Cantidad": 7,
          "Ventas Producto": 420.0,
          "Remanente": -75.67,
          "Ingresos Envío": 264.18,
          "Comisiones": 382.93,
          "Costos Logísticos": 30.15,
          "Ajustes": -11.40,
          "Estado": "Resumen Global",
      },
      {
          "ID": "CAF-001",
          "Mes": "Pendiente de Fechar",
          "Canal": "Cafeterías",
          "Referencia": "CAF-LOTE-1",
          "Producto": "Guacamole Liofilizado 40g",
          "Cantidad": 250,
          "Ventas Producto": 15000.0,
          "Remanente": 15000.0,
          "Ingresos Envío": 0.0,
          "Comisiones": 0.0,
          "Costos Logísticos": 0.0,
          "Ajustes": 0.0,
          "Estado": "Entregado",
      },
  ]
  st.session_state.operaciones_df = pd.DataFrame(ops_iniciales)

# ==========================================
# BARRA LATERAL: NAVEGACIÓN Y CONFIGURACIÓN
# ==========================================
st.sidebar.header("🎛️ Panel de Control")
menu = st.sidebar.radio(
    "Selecciona una sección:",
    [
        "📊 Resumen Ejecutivo",
        "🌐 Ventas por Canal",
        "📋 Catálogo de Costos & Configuración",
        "🔮 Simulador de Escenarios",
    ],
)

# CÁLCULOS AUTOMÁTICOS DESDE EL CATÁLOGO
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

# ==========================================
# VISTA 1: RESUMEN EJECUTIVO (CON FILTROS INTERACTIVOS)
# ==========================================
if menu == "📊 Resumen Ejecutivo":
  st.subheader("📊 Resumen Ejecutivo & Indicadores Clave")

  # Controles de filtros en forma de botón / selectores desplegables superiores
  col_f1, col_f2, col_f3 = st.columns([2, 2, 1])

  meses_disponibles = sorted(
      st.session_state.operaciones_df["Mes"].unique().tolist()
  )
  canales_disponibles = [
      "Todos los canales",
      "Mercado Libre",
      "Amazon",
      "Cafeterías",
      "Venta directa",
      "Otros canales",
  ]

  with col_f1:
    meses_seleccionados = st.multiselect(
        "📅 Elegir meses", options=meses_disponibles, default=meses_disponibles
    )

  with col_f2:
    canal_seleccionado = st.selectbox(
        "🌐 Elegir canal", options=canales_disponibles, index=0
    )

  with col_f3:
    st.write("")
    st.write("")
    if st.button("🔄 Restablecer filtros"):
      st.rerun()

  # Etiqueta de selección activa
  txt_meses = (
      ", ".join(meses_seleccionados)
      if meses_seleccionados
      else "Ningún mes seleccionado"
  )
  st.info(f"🔍 **Selección activa:** {txt_meses} · **{canal_seleccionado}**")

  # Filtrado de operaciones (excluyendo canceladas y pendientes de fecha si no se seleccionan explícitamente)
  df_ops = st.session_state.operaciones_df[
      st.session_state.operaciones_df["Estado"] != "Cancelado"
  ]

  if meses_seleccionados:
    df_ops = df_ops[df_ops["Mes"].isin(meses_seleccionados)]

  if canal_seleccionado != "Todos los canales":
    df_ops = df_ops[df_ops["Canal"] == canal_seleccionado]

  # Validar si existen registros
  if df_ops.empty:
    st.warning(
        "⚠️ No existen registros para la combinación de filtros seleccionada."
    )
  else:
    ventas_filtradas = df_ops["Ventas Producto"].sum()
    remanente_filtrado = df_ops["Remanente"].sum()
    cantidad_filtrada = df_ops["Cantidad"].sum()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Ventas Filtradas", f"${ventas_filtradas:,.2f}")
    col2.metric("Remanente Reportado", f"${remanente_filtrado:,.2f}")
    col3.metric("Costo Variable Unit.", f"${cv_unitario_total:,.2f}")
    col4.metric("Gastos Fijos Mensuales", f"${cf_mensual_total:,.2f}")
    col5.metric(
        "Punto de Equilibrio",
        f"{pe_unidades:,} sobres",
        f"${pe_pesos:,.2f} MXN",
    )

    st.markdown("---")

    col_g1, col_g2 = st.columns(2)
    with col_g1:
      st.subheader("🌐 Ventas por Canal (Filtrado)")
      df_c_res = df_ops.groupby("Canal")["Ventas Producto"].sum().reset_index()
      fig_c = go.Figure(
          data=[
              go.Bar(
                  x=df_c_res["Canal"],
                  y=df_c_res["Ventas Producto"],
                  marker_color="#2d6a4f",
              )
          ]
      )
      fig_c.update_layout(
          height=320, margin=dict(t=20, b=20, l=20, r=20), yaxis_title="MXN"
      )
      st.plotly_chart(fig_c, use_container_width=True)

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
# VISTA 2: VENTAS POR CANAL
# ==========================================
elif menu == "🌐 Ventas por Canal":
  st.subheader("🌐 Gestión y Detalle de Ventas por Canal")
  st.markdown(
      "Visualiza operaciones por canal, distingue ventas de producto frente a"
      " remanentes y administra registros manuales."
  )

  canal_sel = st.selectbox(
      "Filtrar vista por canal:",
      [
          "Todos",
          "Mercado Libre",
          "Amazon",
          "Cafeterías",
          "Venta directa",
          "Otros canales",
      ],
  )

  df_view = st.session_state.operaciones_df
  if canal_sel != "Todos":
    df_view = df_view[df_view["Canal"] == canal_sel]

  st.dataframe(df_view, use_container_width=True)

  # Bloque de elementos pendientes de fecha
  df_pendientes = st.session_state.operaciones_df[
      st.session_state.operaciones_df["Mes"] == "Pendiente de Fechar"
  ]
  if not df_pendientes.empty:
    st.warning(
        "⚠️ **Atención:** Existen importes sin fecha asignada (ej. Cafeterías)."
        " Estos se muestran en un bloque separado para evitar distorsiones"
        " mensuales:"
    )
    st.dataframe(df_pendientes, use_container_width=True)

  st.markdown("---")
  st.subheader("➕ Agregar / Registrar Nueva Venta (Cafeterías / Directa / Otros)")

  with st.form("form_nueva_venta"):
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
      new_canal = st.selectbox(
          "Canal", ["Cafeterías", "Venta directa", "Otros canales"]
      )
      new_ref = st.text_input("Referencia / Folio", "VENTA-001")
    with f_col2:
      new_mes = st.text_input("Mes y Año (ej. Octubre 2026)", "Octubre 2026")
      new_prod = st.text_input("Producto", "Guacamole Liofilizado 40g")
    with f_col3:
      new_cant = st.number_input("Cantidad (Sobres)", min_value=1, value=50)
      new_monto = st.number_input(
          "Importe Venta Producto ($ MXN)", min_value=0.0, value=3000.0
      )

    submitted = st.form_submit_button("Guardar Registro de Venta")
    if submitted:
      nuevo_id = f"REG-{len(st.session_state.operaciones_df)+1}"
      nueva_fila = {
          "ID": nuevo_id,
          "Mes": new_mes,
          "Canal": new_canal,
          "Referencia": new_ref,
          "Producto": new_prod,
          "Cantidad": new_cant,
          "Ventas Producto": new_monto,
          "Remanente": new_monto,
          "Ingresos Envío": 0.0,
          "Comisiones": 0.0,
          "Costos Logísticos": 0.0,
          "Ajustes": 0.0,
          "Estado": "Entregado",
      }
      st.session_state.operaciones_df = pd.concat(
          [st.session_state.operaciones_df, pd.DataFrame([nueva_fila])],
          ignore_index=True,
      )
      st.success(f"¡Venta registrada con éxito bajo el ID {nuevo_id}!")
      st.rerun()

  st.markdown("---")
  st.subheader("⚙️ Cancelar o Ajustar Registro")
  id_a_cancelar = st.selectbox(
      "Selecciona el ID de la operación a cancelar:",
      st.session_state.operaciones_df["ID"].tolist(),
  )
  if st.button("Marcar Registro como Cancelado"):
    st.session_state.operaciones_df.loc[
        st.session_state.operaciones_df["ID"] == id_a_cancelar, "Estado"
    ] = "Cancelado"
    st.success(
        f"La operación {id_a_cancelar} ha sido marcada como cancelada"
        " (conservando trazabilidad)."
    )
    st.rerun()

  # Exportación de datos filtrados
  st.markdown("---")
  csv_ops = df_view.to_csv(index=False).encode("utf-8")
  st.download_button(
      "📥 Exportar Ventas Filtradas (CSV)",
      data=csv_ops,
      file_name="ventas_legado_verde.csv",
      mime="text/csv",
  )

# ==========================================
# VISTA 3: CATÁLOGO DE COSTOS & CONFIGURACIÓN
# ==========================================
elif menu == "📋 Catálogo de Costos & Configuración":
  st.subheader("📋 Catálogo Interactivo de Costos y Configuración Global")
  st.markdown(
      "Administra los parámetros globales (precio de venta, volumen de"
      " producción, tipo de cambio) y edita la estructura de costos y gastos."
  )

  # Parámetros globales reubicados desde el resumen ejecutivo
  st.markdown("### ⚙️ Parámetros Globales del Negocio")
  cg1, cg2, cg3 = st.columns(3)
  with cg1:
    st.session_state.precio_venta = st.number_input(
        "Precio Venta Promedio ($)",
        min_value=1.0,
        value=float(st.session_state.precio_venta),
        step=1.0,
    )
  with cg2:
    st.session_state.vol_prod = st.number_input(
        "Volumen Producción Mensual (Sobres)",
        min_value=1,
        value=int(st.session_state.vol_prod),
        step=50,
    )
  with cg3:
    st.session_state.tc_usd = st.number_input(
        "Tipo de Cambio USD/MXN",
        min_value=10.0,
        value=float(st.session_state.tc_usd),
        step=0.5,
    )

  st.markdown("---")
  st.markdown("### 📋 Tabla Editable de Costos")
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
