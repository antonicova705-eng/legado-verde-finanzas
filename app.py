import streamlit as st

import pandas as pd

import plotly.graph_objects as go

import plotly.express as px

import sqlite3

from datetime import datetime



# ---------------------------------------------------------

# CONFIGURACIÓN DE PÁGINA & ESTILOS (Legado Verde Theme)

# ---------------------------------------------------------

st.set_page_config(

    page_title="Legado Verde - Tablero Financiero & IA",

    page_icon="🥑",

    layout="wide"

)



# Estilo personalizado Verde Esmeralda

st.markdown("""

    <style>

    .main { background-color: #f8faf8; }

    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }

    .css-1r6slb0 { border-radius: 10px; }

    div[data-testid="stMetricValue"] { color: #1b4d3e; font-weight: 700; }

    </style>

""", unsafe_allow_html=True)



# ---------------------------------------------------------

# BASE DE DATOS LOCAL (SQLite para Persistencia de Datos)

# ---------------------------------------------------------

def init_db():

    conn = sqlite3.connect('legado_verde_finanzas.db')

    c = conn.cursor()

    # Tabla de Ventas y Movimientos

    c.execute('''CREATE TABLE IF NOT EXISTS movimientos (

                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    fecha TEXT,

                    canal TEXT,

                    concepto TEXT,

                    unidades INTEGER,

                    ingreso_bruto REAL,

                    cargos_plataforma REAL,

                    costo_envio REAL,

                    costo_producto_unitario REAL,

                    estatus TEXT,

                    es_parcial INTEGER DEFAULT 0

                )''')

    

    # Insertar datos históricos iniciales de Mercado Libre y Amazon si la tabla está vacía

    c.execute("SELECT COUNT(*) FROM movimientos")

    if c.fetchone()[0] == 0:

        datos_iniciales = [

            ('2026-07-15', 'Mercado Libre', 'Ventas Julio Meli', 9, 1341.00, 890.10, 0.0, 45.0, 'DELIVERED', 0),

            ('2026-08-15', 'Mercado Libre', 'Ventas Agosto Meli', 7, 1044.00, 505.12, 0.0, 45.0, 'DELIVERED', 0),

            ('2026-09-15', 'Mercado Libre', 'Ventas Septiembre Meli', 9, 1342.00, 468.08, 0.0, 45.0, 'DELIVERED', 0),

            ('2026-10-05', 'Mercado Libre', 'Ventas Octubre Meli (Curso)', 6, 895.00, 256.60, 0.0, 45.0, 'IN_TRANSIT', 1),

            ('2026-09-26', 'Amazon', 'Resumen Q3 Amazon', 7, 420.00, 413.08, 0.0, 45.0, 'DELIVERED', 0),

            ('2026-09-30', 'Cafeterías', 'Ventas Acumuladas Cafeterías', 250, 15000.00, 0.0, 0.0, 45.0, 'UNALLOCATED_HISTORIC', 0)

        ]

        c.executemany('''INSERT INTO movimientos 

                         (fecha, canal, concepto, unidades, ingreso_bruto, cargos_plataforma, costo_envio, costo_producto_unitario, estatus, es_parcial) 

                         VALUES (?,?,?,?,?,?,?,?,?,?)''', datos_iniciales)

        conn.commit()

    conn.close()



init_db()



# ---------------------------------------------------------

# FUNCIONES DE CÁLCULO FINANCIERO

# ---------------------------------------------------------

def cargar_datos():

    conn = sqlite3.connect('legado_verde_finanzas.db')

    df = pd.read_sql_query("SELECT * FROM movimientos", conn)

    conn.close()

    return df



# Header Principal

st.title("🥑 Legado Verde — Control Financiero & IA")

st.caption("Sistema de Gestión de Rentabilidad, Punto de Equilibrio y Proyecciones Omnicanal")



df = cargar_datos()



# ---------------------------------------------------------

# PANEL LATERAL: PARÁMETROS Y SUPUESTOS EDITABLES

# ---------------------------------------------------------

st.sidebar.header("⚙️ Supuestos Financieros")

gastos_fijos_base = st.sidebar.number_input("Gastos Fijos Mensuales ($ MXN):", value=35000.0, step=1000.0)

costo_var_unitario_default = st.sidebar.number_input("Costo Variable Prod. Unitario ($):", value=45.0, step=1.0)

precio_promedio_default = st.sidebar.number_input("Precio Promedio Unitario ($):", value=60.0, step=5.0)



st.sidebar.markdown("---")

st.sidebar.header("🎯 Meta de Negocio")

meta_ventas = st.sidebar.number_input("Meta de Ventas Mensual ($ MXN):", value=140000.0, step=5000.0)



# ---------------------------------------------------------

# PESTAÑAS PRINCIPALES DEL TABLERO

# ---------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs([

    "📊 Resumen & Punto de Equilibrio", 

    "📈 Proyecciones & Escenarios", 

    "📝 Registro de Movimientos", 

    "🤖 Asistente Virtual (Jarvis)"

])



# ---------------------------------------------------------

# TAB 1: RESUMEN Y PUNTO DE EQUILIBRIO

# ---------------------------------------------------------

with tab1:

    st.subheader("Resumen Ejecutivo de Operaciones")

    

    # Filtro de Estatus para excluir cancelados

    df_valid = df[df['estatus'] != 'CANCELLED'].copy()

    

    # Métricas Globales

    total_ingresos = df_valid['ingreso_bruto'].sum()

    total_cargos_plat = df_valid['cargos_plataforma'].sum()

    total_cogs = (df_valid['unidades'] * df_valid['costo_producto_unitario']).sum()

    margen_contribucion_total = total_ingresos - total_cargos_plat - total_cogs

    

    # Cálculos Teóricos unitarios

    margen_unitario = precio_promedio_default - costo_var_unitario_default

    margen_contrib_pct = (margen_unitario / precio_promedio_default) if precio_promedio_default > 0 else 0

    pe_dinero = gastos_fijos_base / margen_contrib_pct if margen_contrib_pct > 0 else 0

    pe_unidades = gastos_fijos_base / margen_unitario if margen_unitario > 0 else 0

    

    # Faltante para Meta

    faltante_meta = meta_ventas - total_ingresos

    pct_meta = (total_ingresos / meta_ventas) * 100 if meta_ventas > 0 else 0



    # KPIs superiores

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Ventas Totales Registradas", f"${total_ingresos:,.2f} MXN")

    c2.metric("Punto de Equilibrio (Mensual)", f"${pe_dinero:,.2f} MXN", f"{pe_unidades:,.0f} unds")

    c3.metric("Margen Contribución Unitario", f"${margen_unitario:,.2f}", f"{margen_contrib_pct*100:.1f}%")

    c4.metric("Avance Hacia la Meta", f"{pct_meta:.1f}%", f"Faltan ${max(0.0, faltante_meta):,.2f}")



    st.markdown("---")

    

    col_left, col_right = st.columns([6, 4])

    

    with col_left:

        st.write("### Gráfico de Punto de Equilibrio y Costos")

        unidades_range = list(range(0, int(pe_unidades * 2) + 500, 100))

        df_pe = pd.DataFrame({'Unidades': unidades_range})

        df_pe['Ingresos'] = df_pe['Unidades'] * precio_promedio_default

        df_pe['Costos Fijos'] = gastos_fijos_base

        df_pe['Costos Totales'] = gastos_fijos_base + (df_pe['Unidades'] * costo_var_unitario_default)

        

        fig_pe = go.Figure()

        fig_pe.add_trace(go.Scatter(x=df_pe['Unidades'], y=df_pe['Ingresos'], name='Ingresos Totales', line=dict(color='#2E7D32', width=3)))

        fig_pe.add_trace(go.Scatter(x=df_pe['Unidades'], y=df_pe['Costos Totales'], name='Costos Totales', line=dict(color='#D32F2F', width=2, dash='dash')))

        fig_pe.add_trace(go.Scatter(x=df_pe['Unidades'], y=df_pe['Costos Fijos'], name='Costos Fijos', line=dict(color='#757575', width=1, dash='dot')))

        

        # Marca Punto de Equilibrio

        fig_pe.add_vline(x=pe_unidades, line_width=1, line_dash="dash", line_color="black")

        fig_pe.add_annotation(x=pe_unidades, y=pe_dinero, text=f"Punto Equilibrio<br>${pe_dinero:,.0f}", showarrow=True, arrowhead=1)

        

        fig_pe.update_layout(title="Análisis de Breakeven", xaxis_title="Unidades Vendidas", yaxis_title="Monto ($ MXN)", template="plotly_white")

        st.plotly_chart(fig_pe, use_container_width=True)



    with col_right:

        st.write("### Desglose de Ventas por Canal")

        df_canal = df_valid.groupby('canal')['ingreso_bruto'].sum().reset_index()

        fig_pie = px.pie(df_canal, values='ingreso_bruto', names='canal', color_discrete_sequence=px.colors.sequential.Emrld)

        st.plotly_chart(fig_pie, use_container_width=True)



# ---------------------------------------------------------

# TAB 2: PROYECCIONES Y ESCENARIOS DE SENSIBILIDAD

# ---------------------------------------------------------

with tab2:

    st.subheader("Simulación de Escenarios Financieros")

    st.write("Ajusta las variables proyectadas para evaluar el comportamiento de la utilidad neta.")

    

    volumen_base = st.slider("Volumen de Ventas Proyectado (Unidades):", min_value=100, max_value=5000, value=1500, step=100)

    

    # Matriz de escenarios

    escenarios = {

        'Conservador (-15%)': int(volumen_base * 0.85),

        'Base': volumen_base,

        'Optimista (+20%)': int(volumen_base * 1.20)

    }

    

    res_escenarios = []

    for nombre, vol in escenarios.items():

        ing = vol * precio_promedio_default

        cv = vol * costo_var_unitario_default

        mb = ing - cv

        un = mb - gastos_fijos_base

        res_escenarios.append({

            'Escenario': nombre,

            'Unidades': vol,

            'Ingresos Proyectados': ing,

            'Costos Variables': cv,

            'Margen Bruto': mb,

            'Gastos Fijos': gastos_fijos_base,

            'Utilidad Neta Est.': un

        })

    

    df_esc = pd.DataFrame(res_escenarios)

    st.table(df_esc.style.format({

        'Ingresos Proyectados': '${:,.2f}',

        'Costos Variables': '${:,.2f}',

        'Margen Bruto': '${:,.2f}',

        'Gastos Fijos': '${:,.2f}',

        'Utilidad Neta Est.': '${:,.2f}'

    }))



# ---------------------------------------------------------

# TAB 3: REGISTRO DE MOVIMIENTOS Y EXPORTACIÓN

# ---------------------------------------------------------

with tab3:

    st.subheader("Histórico de Movimientos y Nuevo Registro")

    

    with st.expander("➕ Registrar Nuevo Movimiento / Venta"):

        with st.form("form_nuevo_mov"):

            f1, f2, f3 = st.columns(3)

            fecha_n = f1.date_input("Fecha", datetime.now())

            canal_n = f2.selectbox("Canal", ["Mercado Libre", "Amazon", "Cafeterías", "Venta Directa"])

            concepto_n = f3.text_input("Concepto / Folio", "Venta Lote")

            

            f4, f5, f6 = st.columns(3)

            unidades_n = f4.number_input("Unidades", value=1, min_value=1)

            ingreso_n = f5.number_input("Ingreso Bruto ($)", value=0.0)

            cargos_n = f6.number_input("Cargos / Comisiones ($)", value=0.0)

            

            estatus_n = st.selectbox("Estatus", ["DELIVERED", "IN_TRANSIT", "CANCELLED", "UNALLOCATED_HISTORIC"])

            

            submit = st.form_submit_button("Guardar Registro")

            if submit:

                conn = sqlite3.connect('legado_verde_finanzas.db')

                c = conn.cursor()

                c.execute('''INSERT INTO movimientos 

                             (fecha, canal, concepto, unidades, ingreso_bruto, cargos_plataforma, costo_envio, costo_producto_unitario, estatus) 

                             VALUES (?,?,?,?,?,?,?,?,?)''',

                          (str(fecha_n), canal_n, concepto_n, unidades_n, ingreso_n, cargos_n, 0.0, costo_var_unitario_default, estatus_n))

                conn.commit()

                conn.close()

                st.success("¡Registro guardado exitosamente!")

                st.rerun()



    st.write("### Tabla General de Registros")

    st.dataframe(df, use_container_width=True)

    

    # Exportación

    csv = df.to_csv(index=False).encode('utf-8')

    st.download_button("📥 Exportar Histórico a CSV", data=csv, file_name="legado_verde_historico.csv", mime="text/csv")



# ---------------------------------------------------------

# TAB 4: ASISTENTE VIRTUAL DE CONSULTAS (JARVIS SIMULADO)

# ---------------------------------------------------------

with tab4:

    st.subheader("🤖 Jarvis — Asistente Financiero de Legado Verde")

    st.caption("Consulta tus métricas operativas en lenguaje natural.")

    

    prompt = st.text_input("Haz una pregunta sobre las finanzas de Legado Verde:")

    if prompt:

        p_lower = prompt.lower()

        if "vendimos" in p_lower or "ventas" in p_lower:

            st.info(f"💡 **Respuesta de Jarvis:** Las ventas totales registradas acumuladas son de **${total_ingresos:,.2f} MXN**, distribuidas en {len(df_valid)} operaciones documentadas.")

        elif "equilibrio" in p_lower or "breakeven" in p_lower:

            st.info(f"💡 **Respuesta de Jarvis:** Tu punto de equilibrio teórico mensual requiere facturar **${pe_dinero:,.2f} MXN** (aproximadamente {pe_unidades:,.0f} unidades a $60 MXN).")

        elif "canal" in p_lower or "margen" in p_lower:

            st.info(f"💡 **Respuesta de Jarvis:** El canal con mayor volumen documentado es **Cafeterías** ($15,000 MXN), seguido de Mercado Libre. Recuerda regularizar las fechas de cafeterías para el reporte mensual exacto.")

        else:

            st.warning("🤖 **Jarvis:** Consulta recibida. Para análisis complejos de escenarios, utiliza la pestaña 'Proyecciones & Escenarios'.") 
