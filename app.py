import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import json
import os
import copy
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

def hoy_local():
    return datetime.now(ZoneInfo("America/Mexico_City")).date()
from motor import *
# ==========================================
# CONFIGURACIÓN DE PÁGINA Y BRANDING CSS
# ==========================================
st.set_page_config(
    page_title="Legado Verde - Sistema Financiero",
    page_icon="🥑",
    layout="wide",
    initial_sidebar_state="expanded",
)
# Estilos CSS basados en la paleta oficial del logo
st.markdown(
    """
    <style>
    /* Fondo principal Beige Institucional */
    .stApp {
        background-color: #F4F0EA;
    }
    /* Encabezados y títulos en Verde Bosque */
    h1, h2, h3, .stSubheader {
        color: #0B5127 !important;
        font-family: 'Georgia', serif;
        font-weight: 700;
    }
    /* Tarjetas de métricas estilizadas */
    [data-testid="stMetricValue"] {
        color: #0B5127 !important;
        font-size: 1.8rem !important;
        font-weight: bold;
    }
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        padding: 15px 20px;
        border-radius: 12px;
        box-shadow: 0 4px 10px rgba(11, 81, 39, 0.08);
        border-left: 6px solid #8EB712;
    }
    /* Botones con estilo institucional */
    .stButton>button {
        background-color: #0B5127 !important;
        color: #FFFFFF !important;
        border-radius: 8px !important;
        border: none !important;
        padding: 10px 20px !important;
        font-weight: bold !important;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #8EB712 !important;
        color: #FFFFFF !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }
    /* Modificación de la barra lateral */
    section[data-testid="stSidebar"] {
        background-color: #EFE9E0;
        border-right: 1px solid #DCD5C9;
    }
    @media (max-width: 640px) {
        [data-testid="stHorizontalBlock"] {flex-wrap: wrap;}
        [data-testid="stColumn"] {min-width: 240px; flex: 1 1 100%;}
    }
    </style>
""",
    unsafe_allow_html=True,
)
# ==========================================
# LOGO Y ENCABEZADO
# ==========================================
st.sidebar.image(
    "https://drive.google.com/thumbnail?id=1j9PfF082J_VzWP2bQURgQw8BVgeI3aK9&sz=w1000",
    width="stretch",
)
st.sidebar.markdown("---")
st.title("🌱 Legado Verde: Sistema Financiero Inteligente")
st.markdown(
    "*Tablero gerencial integrado para el control de costos, ventas por canal,"
    " punto de equilibrio y simulación de escenarios.*"
)
st.markdown("---")
# Almacenamiento compartido del servidor con control de versiones.
DB_PATH = os.environ.get("LEGADO_VERDE_DB", str(Path(__file__).with_name("datos") / "legado_verde.sqlite3"))
almacen = Almacen(DB_PATH)
revision, guardado = almacen.leer()
if guardado is not None:
    st.session_state.catalogo_df = pd.DataFrame(guardado["catalogo"])
    st.session_state.operaciones_df = pd.DataFrame(guardado["operaciones"])
    for k, v in guardado["config"].items():
        st.session_state[k] = v

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

# Nuevas tablas conservan íntegros los campos y registros heredados.
if guardado is None:
    datos = {'config': {k: st.session_state[k] for k in ['tc_usd','vol_prod','precio_venta']},
             'catalogo': st.session_state.catalogo_df.to_dict('records'),
             'operaciones': migrar(st.session_state.operaciones_df.to_dict('records')),
             'asientos': [], 'historial': [], 'cobertura': [], 'apertura_confirmada': False,
             'fecha_apertura': None}
    try:
        revision = almacen.guardar(datos, revision)
    except Conflicto:
        st.rerun()
else:
    datos = guardado
antes_ejecucion = copy.deepcopy(datos)
st.session_state.operaciones_df = pd.DataFrame(datos['operaciones'])

def guardar_y_actualizar():
    try:
        almacen.guardar(datos, revision)
        st.rerun()
    except Conflicto as e:
        st.error(str(e))
        st.stop()

def moneda(v):
    return f'${v:,.2f} MXN' if v is not None else 'No disponible'

def periodo():
    modo = st.sidebar.selectbox('Periodo', ['Mes','Año','Rango de fechas'])
    hoy = hoy_local()
    if modo == 'Mes':
        y = st.sidebar.number_input('Año',2000,2100,hoy.year)
        m = st.sidebar.selectbox('Mes',range(1,13),index=hoy.month-1,format_func=lambda x:MESES[x-1])
        ini,fin=date(y,m,1),date(y,m,calendar.monthrange(y,m)[1])
    elif modo == 'Año':
        y=st.sidebar.number_input('Año',2000,2100,hoy.year)
        ini,fin=date(y,1,1),date(y,12,31)
    else:
        ini=st.sidebar.date_input('Desde',hoy.replace(day=1))
        fin=st.sidebar.date_input('Hasta',hoy)
    if ini>fin:
        st.error('La fecha inicial debe ser anterior o igual a la final.')
        st.stop()
    st.sidebar.caption(f'{ini:%d/%m/%Y} — {fin:%d/%m/%Y}')
    return ini.isoformat(),fin.isoformat()

def completa(inicio,fin):
    return any(c['Inicio']<=inicio and c['Fin']>=fin for c in datos['cobertura'])

def advertencias(inicio,fin):
    problemas=[]
    if not completa(inicio,fin):
        problemas.append('No se ha confirmado que ventas, costos, gastos y movimientos estén completos para este periodo.')
    pendientes=[r['ID'] for r in datos['operaciones'] if activo(r) and not r.get('Fecha')]
    if pendientes:
        problemas.append('Ventas sin fecha exacta excluidas: '+', '.join(pendientes)+'. Los resúmenes deben desglosarse sin duplicarlos.')
    faltantes=[r['ID'] for r in datos['operaciones'] if en_periodo(r,inicio,fin) and not r.get('Costo confirmado')]
    if faltantes:
        problemas.append('Falta costo de ventas confirmado en: '+', '.join(faltantes)+'.')
    if not datos.get('apertura_confirmada'):
        problemas.append('Falta registrar y confirmar el balance de apertura; saldos patrimoniales y de efectivo incompletos.')
    elif datos.get('fecha_apertura') and datos['fecha_apertura']>=inicio:
        problemas.append('El periodo comienza antes o en la apertura. Consulta desde el día siguiente a la apertura para conciliar flujos.')
    ajustes=[r['ID'] for r in datos['operaciones'] if en_periodo(r,inicio,fin) and r.get('Ajustes',0)]
    if ajustes:
        problemas.append('Ajustes heredados pendientes de clasificación contable: '+', '.join(ajustes)+'.')
    if problemas:
        st.warning('Reportes PRELIMINARES. '+ ' '.join(problemas))
    return problemas

def tabla(items):
    st.dataframe(pd.DataFrame(items,columns=['Concepto','Importe MXN']),width="stretch",hide_index=True)

def crecimiento():
    st.subheader('📈 Ventas netas por mes')
    y=st.number_input('Año de la gráfica',2000,2100,hoy_local().year,key='crec_anio')
    rows=[]
    anterior=None
    for m in range(1,13):
        ini=f'{y}-{m:02d}-01'
        fin=f'{y}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}'
        # Gráfica comercial: venta de producto neta; envío se informa aparte.
        v=sum(neta(r) for r in datos['operaciones'] if en_periodo(r,ini,fin))
        comp=completa(ini,fin) and date.fromisoformat(fin)<hoy_local()
        tiene=any(en_periodo(r,ini,fin) for r in datos['operaciones'])
        mostrado=v if tiene or comp else None
        variacion='No aplicable'
        if anterior and anterior['Completo'] and comp and anterior['Ventas netas MXN']:
            variacion=f"{(v/anterior['Ventas netas MXN']-1)*100:+.1f}%"
        estado='Completo' if comp else 'Parcial / sin confirmar'
        row={'Mes':MESES[m-1],'Ventas netas MXN':mostrado,'Variación':variacion,'Estado':estado,'Completo':comp}
        rows.append(row)
        anterior=row
    fig=go.Figure(go.Bar(x=[x['Mes'] for x in rows],y=[x['Ventas netas MXN'] for x in rows],
                        marker_color=['#0B5127' if x['Completo'] else '#8EB712' for x in rows],
                        customdata=[[x['Variación'],x['Estado']] for x in rows],
                        hovertemplate='%{x}: $%{y:,.2f}<br>Variación: %{customdata[0]}<br>%{customdata[1]}<extra></extra>'))
    fig.update_layout(yaxis_title='Ventas netas de producto (MXN)',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig,width="stretch")
    st.dataframe(pd.DataFrame(rows).drop(columns='Completo'),hide_index=True,width="stretch")
    st.caption('Un espacio vacío significa información desconocida. Las comparaciones porcentuales requieren dos meses completos; el mes actual siempre es parcial. No incluye ingresos por envío.')

CANALES=['Mercado Libre','Amazon','Cafeterías','Venta directa','Otros canales']
menu=st.sidebar.radio('Seleccione módulo:',[
    '📊 Resumen Ejecutivo','🌐 Ventas por Canal','📋 Catálogo de Costos & Configuración',
    '🔮 Simulador de Escenarios','📑 Estados financieros'],label_visibility='collapsed')
inicio,fin=periodo()
if st.sidebar.button('🔄 Actualizar datos del servidor'):
    st.rerun()
st.sidebar.caption('Se recalcula al guardar, editar o anular. Las sesiones comparten la base del servidor; Actualizar obtiene cambios de otra sesión.')
cv_unitario_total,cf_mensual_total=costos_catalogo(datos['catalogo'],st.session_state.tc_usd,st.session_state.vol_prod)
contribucion_unitaria=st.session_state.precio_venta-cv_unitario_total
margen_contribucion_pct=contribucion_unitaria/st.session_state.precio_venta
pe_unidades=int(np.ceil(cf_mensual_total/contribucion_unitaria)) if contribucion_unitaria>0 else None
pe_pesos=cf_mensual_total/margen_contribucion_pct if margen_contribucion_pct>0 else None

if menu == '📊 Resumen Ejecutivo':
    st.subheader('📊 Resumen Ejecutivo & Indicadores Clave')
    problemas=advertencias(inicio,fin)
    rep=reporte(datos,inicio,fin)
    pe=calculo_pe(datos,inicio,fin)
    filtro=st.selectbox('Canal comercial',['Todos los canales']+CANALES)
    ops=[r for r in datos['operaciones'] if en_periodo(r,inicio,fin) and (filtro=='Todos los canales' or r['Canal']==filtro)]
    c1,c2,c3=st.columns(3)
    c1.metric('Ventas netas de producto',moneda(sum(neta(r) for r in ops)))
    c2.metric('Remanente reportado (no es utilidad)',moneda(sum(r['Remanente'] for r in ops)))
    c3.metric('Sobres vendidos',f"{sum(r['Cantidad'] for r in ops):,}")
    c1,c2,c3=st.columns(3)
    c1.metric('Costo variable unitario presupuestado',moneda(cv_unitario_total))
    c2.metric('Costos fijos mensuales presupuestados',moneda(cf_mensual_total))
    costo_pendiente=bool(pe['faltantes'])
    c3.metric('EBITDA registrado · preliminar' if problemas else 'EBITDA',moneda(None if costo_pendiente else rep['ebitda']))
    st.caption('Margen EBITDA: '+('No disponible' if costo_pendiente or rep['ventas']<=0 else f"{rep['ebitda']/rep['ventas']*100:.1f}%")+'. EBITDA no representa efectivo.')
    grouped={c:sum(neta(r) for r in ops if r['Canal']==c) for c in CANALES}
    fig=go.Figure(go.Bar(x=list(grouped),y=list(grouped.values()),marker_color='#0B5127'))
    fig.update_layout(title='Ventas netas por canal',yaxis_title='MXN')
    st.plotly_chart(fig,width="stretch")
    st.subheader('🎯 Punto de equilibrio del periodo · todos los canales')
    st.caption('Base: margen conjunto de ventas registradas (incluye envío), costo de ventas confirmado y comisiones/logística. Fijos: gastos fijos, depreciación y amortización devengados en el mismo periodo. El filtro comercial de canal no asigna gastos fijos.')
    st.write(f"Ventas: {moneda(pe['ventas'])} · Costos variables: {moneda(pe['variables'])} · Fijos registrados: {moneda(pe['fijos'])}")
    if pe['meta'] is None:
        st.info('No se puede calcular: faltan costos confirmados, no hay ventas o el margen de contribución es cero o negativo.')
    elif pe['fijos']<=0:
        st.info('No hay costos fijos registrados. Confirma y registra los gastos del periodo antes de interpretar la meta.')
    else:
        meta=pe['meta']
        faltante=max(meta-pe['ventas'],0)
        superado=max(pe['ventas']-meta,0)
        a,b,c,d=st.columns(4)
        a.metric('Meta registrada',moneda(meta))
        b.metric('Avance',f"{pe['avance']:.1f}%")
        c.metric('Falta',moneda(faltante),f'{faltante/meta*100:.1f}% de la meta')
        d.metric('Superado',moneda(superado))
        fig=go.Figure(go.Bar(x=[pe['ventas']],y=['Ventas reales'],orientation='h',marker_color='#0B5127',hovertemplate='$%{x:,.2f}<extra></extra>'))
        fig.add_vline(x=meta,line_color='#d90429',line_width=3,annotation_text=f'Meta ${meta:,.2f}')
        fig.update_layout(xaxis=dict(title='MXN',range=[0,max(meta,pe['ventas'])*1.2]),height=250)
        st.plotly_chart(fig,width="stretch")
        st.caption('Margen conjunto: '+f"{pe['margen']*100:.2f}%"+('. La meta es preliminar porque hay información pendiente.' if problemas else '.'))
    with st.expander('Curva teórica mensual del catálogo (presupuesto)'):
        if pe_pesos is None:
            st.info('El presupuesto no tiene margen positivo; no hay punto de equilibrio finito.')
        else:
            unidades=np.linspace(0,max(pe_unidades*2,1500),100)
            teorica=go.Figure()
            teorica.add_trace(go.Scatter(x=unidades,y=unidades*st.session_state.precio_venta,name='Ventas presupuestadas',line=dict(color='#0B5127')))
            teorica.add_trace(go.Scatter(x=unidades,y=cf_mensual_total+unidades*cv_unitario_total,name='Costos presupuestados',line=dict(color='#d90429')))
            teorica.add_trace(go.Scatter(x=[pe_unidades],y=[pe_pesos],name='Equilibrio teórico',mode='markers',marker=dict(size=12,color='#8EB712')))
            teorica.update_layout(xaxis_title='Sobres / mes',yaxis_title='MXN',height=330)
            st.plotly_chart(teorica,width='stretch')
            st.caption('Supuestos del catálogo, precio promedio y producción mensual. Esta curva no representa los costos reales del periodo seleccionado.')
    crecimiento()

elif menu == '🌐 Ventas por Canal':
    st.subheader('🌐 Gestión y Detalle de Ventas por Canal')
    canal=st.selectbox('Filtrar vista por canal',['Todos']+CANALES)
    vista=[r for r in datos['operaciones'] if canal=='Todos' or r['Canal']==canal]
    st.dataframe(pd.DataFrame(vista),width="stretch",hide_index=True)
    st.download_button('📥 Exportar ventas CSV',pd.DataFrame(vista).to_csv(index=False).encode('utf-8-sig'),'ventas_legado_verde.csv','text/csv')
    st.info('Los registros heredados conservan Mes y Remanente. Fecha, costo y cobros se confirman por separado. Un resumen de varios meses debe desglosarse en ventas individuales y después anularse para evitar duplicarlo.')
    ids=[r['ID'] for r in datos['operaciones']]
    elegido=st.selectbox('Crear o editar venta',['Nueva venta']+ids)
    anterior=next((r for r in datos['operaciones'] if r['ID']==elegido),None)
    r=anterior or {'Canal':'Venta directa','Referencia':'','Producto':'Guacamole Liofilizado 40g','Cantidad':1,'Precio':st.session_state.precio_venta,'Fecha':None,'Ventas Producto':st.session_state.precio_venta,'Descuento':0.0,'Devolución':0.0,'Costo de ventas':None,'Costo confirmado':False,'Remanente':0.0,'Ingresos Envío':0.0,'Comisiones':0.0,'Costos Logísticos':0.0,'Ajustes':0.0,'Estado':'Entregado','Estado cobro':'Por confirmar'}
    with st.form('venta_'+elegido):
        a,b=st.columns(2)
        with a:
            fecha=st.date_input('Fecha exacta de la venta (confirmar)',date.fromisoformat(r['Fecha']) if r.get('Fecha') else hoy_local())
            confirmar_fecha=st.checkbox('Confirmo que esta es la fecha real',value=bool(r.get('Fecha confirmada')))
            canales=list(dict.fromkeys(CANALES+[r['Canal']]))
            new_canal=st.selectbox('Canal',canales,index=canales.index(r['Canal']))
            referencia=st.text_input('Referencia / Folio',r['Referencia'])
            producto=st.text_input('Producto',r['Producto'])
            cantidad=st.number_input('Cantidad (sobres)',min_value=1,value=int(r['Cantidad']))
            precio=st.number_input('Precio por sobre antes de descuentos',min_value=0.0,value=float(r.get('Precio') or 0),format='%.6f',step=0.01)
            descuento=st.number_input('Descuento total',min_value=0.0,value=float(r.get('Descuento',0)))
            devolucion=st.number_input('Devoluciones de venta (importe)',min_value=0.0,value=float(r.get('Devolución',0)))
            st.caption('Costo de ventas: costo neto de las unidades efectivamente vendidas; descontar el costo del producto devuelto que regresa a inventario.')
            costo=st.number_input('Costo de ventas total neto',min_value=0.0,value=float(r.get('Costo de ventas') or 0))
            costo_confirmado=st.checkbox('Costo confirmado (incluye cero real)',value=bool(r.get('Costo confirmado')))
        with b:
            envio=st.number_input('Ingresos por envío',min_value=0.0,value=float(r['Ingresos Envío']))
            comision=st.number_input('Comisiones devengadas',min_value=0.0,value=float(r['Comisiones']))
            logistica=st.number_input('Costos logísticos devengados',min_value=0.0,value=float(r['Costos Logísticos']))
            remanente=st.number_input('Remanente reportado (dato histórico)',value=float(r['Remanente']))
            ajustes=st.number_input('Ajustes reportados pendientes de clasificar',value=float(r['Ajustes']))
            estados=list(dict.fromkeys(['Entregado','En Camino','Pendiente','Resumen Global',r['Estado']]))
            estado=st.selectbox('Estado de entrega',estados,index=estados.index(r['Estado']))
            cobros=list(dict.fromkeys(['Por confirmar','Pendiente','Parcial','Cobrado',r.get('Estado cobro','Por confirmar')]))
            cobro=st.selectbox('Estado del cobro (informativo)',cobros,index=cobros.index(r.get('Estado cobro','Por confirmar')))
            st.caption('Marcar Cobrado no mueve efectivo. Registra el cobro con su fecha y asiento en Estados financieros. Si editas una venta cobrada, revisa también el cobro registrado; no se cambia automáticamente.')
        enviar=st.form_submit_button('Guardar cambios' if anterior else 'Guardar venta')
    if enviar:
        if anterior and not activo(anterior):
            st.error('Una venta anulada queda bloqueada; crea una nueva con otro folio para corregirla.')
        elif not confirmar_fecha:
            st.error('Confirma la fecha real antes de guardar.')
        else:
            nuevo=copy.deepcopy(r)
            nuevo.update({'ID':anterior['ID'] if anterior else str(uuid4()),'Fecha':fecha.isoformat(),'Fecha confirmada':True,
                'Mes':f'{MESES[fecha.month-1]} {fecha.year}','Canal':new_canal,'Referencia':referencia.strip(),'Producto':producto.strip(),
                'Cantidad':cantidad,'Precio':precio,'Ventas Producto':round(cantidad*precio,2),'Descuento':descuento,'Devolución':devolucion,
                'Costo de ventas':costo if costo_confirmado else None,'Costo confirmado':costo_confirmado,
                'Ingresos Envío':envio,'Comisiones':comision,'Costos Logísticos':logistica,'Remanente':remanente,
                'Ajustes':ajustes,'Estado':estado,'Estado cobro':cobro,'Anulada':False})
            try:
                validar_venta(nuevo,datos['operaciones'])
                if anterior:
                    datos['operaciones'][ids.index(elegido)]=nuevo
                else:
                    datos['operaciones'].append(nuevo)
                evento(datos,'Venta',anterior,nuevo)
                guardar_y_actualizar()
            except ValueError as e:
                st.error(str(e))
    if anterior and activo(anterior):
        with st.form('anular_'+elegido):
            st.warning('Anular excluye esta venta y sus asientos de cobro vinculados de los reportes. Si la venta ocurrió y fue devuelta, registra devolución y reembolso; usa anulación solo para registros cargados por error.')
            confirmacion=st.checkbox('Confirmo la anulación de '+elegido)
            if st.form_submit_button('Anular venta'):
                if confirmacion:
                    nuevo={**anterior,'Anulada':True,'Estado':'Cancelado'}
                    datos['operaciones'][ids.index(elegido)]=nuevo
                    evento(datos,'Anulación de venta',anterior,nuevo)
                    guardar_y_actualizar()
                else:
                    st.error('Marca la confirmación para anular.')
    with st.expander('Historial de ventas y cambios'):
        st.json(datos['historial'])
elif menu == "📋 Catálogo de Costos & Configuración":
  st.subheader("📋 Catálogo Interactivo de Costos y Parámetros Globales")
  st.markdown(
      "Modifica los supuestos globales y la estructura detallada de costos."
  )
  st.markdown("### ⚙️ Parámetros Globales")
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
      width="stretch",
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
  st.markdown(
      "Evalúa el comportamiento operativo bajo diferentes supuestos de volumen"
      " de ventas."
  )
  escenario = st.selectbox(
      "Selecciona un escenario:",
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
      "Resultado operativo proyectado",
      f"${utilidad_proy:,.2f}",
      f"{(utilidad_proy/ventas_proy*100) if ventas_proy>0 else 0:.1f}%",
  )
  st.markdown("---")
  st.success(
      "✨ El simulador se alimenta automáticamente de los costos configurados"
      " en tiempo real."
  )

elif menu == '📑 Estados financieros':
    st.subheader('📑 Estados financieros')
    problemas=advertencias(inicio,fin)
    rep=reporte(datos,inicio,fin)
    faltan_costos=any(en_periodo(r,inicio,fin) and not r.get('Costo confirmado') for r in datos['operaciones'])
    a,b,c=st.columns(3)
    a.metric('EBITDA · preliminar' if problemas else 'EBITDA',moneda(None if faltan_costos else rep['ebitda']))
    b.metric('Margen EBITDA','No disponible' if faltan_costos or rep['ventas']<=0 else f"{rep['ebitda']/rep['ventas']*100:.1f}%")
    c.metric('Efectivo registrado al corte',moneda(rep['efectivo_final']))
    st.caption('Importes en MXN, sin IVA. Registra IVA y otros impuestos indirectos con cuentas patrimoniales; no forman parte de las ventas ni del EBITDA. Las cifras cero significan ausencia de movimientos registrados, no confirmación de ausencia de operaciones.')
    t1,t2,t3,t4=st.tabs(['Estado de resultados','Flujos de efectivo','Situación financiera','Captura y conciliación'])
    with t1:
        st.caption(f'Periodo: {inicio} a {fin}. Ventas incluye producto neto e ingresos por envío; costos y gastos son devengados.')
        tabla([
            ('Ventas netas',rep['ventas']),('Costo de ventas',None if faltan_costos else rep['costo']),
            ('Utilidad bruta',None if faltan_costos else rep['ventas']-rep['costo']),
            ('Gastos operativos sin depreciación/amortización',rep['gasto']),
            ('EBITDA',None if faltan_costos else rep['ebitda']),('Depreciación y amortización',rep['da']),
            ('Utilidad operativa',None if faltan_costos else rep['operativa']),('Resultado financiero',rep['financiero']),
            ('Utilidad antes de impuestos',None if faltan_costos else rep['operativa']+rep['financiero']),
            ('Impuestos devengados',rep['impuestos']),('Utilidad neta',None if faltan_costos else rep['utilidad'])])
        st.caption('EBITDA = utilidad operativa + depreciación + amortización. Se reconocen una sola vez en sus cuentas específicas.')
    with t2:
        st.caption('Método directo: únicamente movimientos registrados de Efectivo, por fecha de cobro o pago. Cobrar ventas a crédito no vuelve a reconocer ingresos.')
        tabla([('Saldo inicial registrado',rep['efectivo_inicial'])]+
              [('Flujos de '+k.lower(),v) for k,v in rep['flujos'].items()]+
              [('Variación neta registrada',sum(rep['flujos'].values())),('Saldo final registrado',rep['efectivo_final'])])
        diferencia=rep['efectivo_inicial']+sum(rep['flujos'].values())-rep['efectivo_final']
        st.write('Conciliación de efectivo registrado: '+moneda(diferencia))
        if abs(rep['flujos']['Sin clasificar'])>.005:
            st.warning('Clasifica los movimientos sin clasificar. Una apertura dentro del periodo impide interpretar esa entrada como flujo operativo.')
    with t3:
        st.caption('Saldos acumulados al '+fin+'. Capital incluye el resultado acumulado registrado.')
        g=rep['grupos']
        tabla(list(g.items())+[
            ('Activo total',g['Activo circulante']+g['Activo no circulante']),
            ('Pasivo total',g['Pasivo corto plazo']+g['Pasivo largo plazo']),
            ('Pasivo + Capital',g['Pasivo corto plazo']+g['Pasivo largo plazo']+g['Capital']),
            ('Diferencia Activo − Pasivo − Capital',rep['descuadre'])])
        if abs(rep['descuadre'])<.01:
            st.success('La ecuación contable de los movimientos registrados cuadra. Esto no certifica que estén completos.')
        else:
            st.error('La ecuación contable no cuadra; revisa los asientos.')
        with st.expander('Detalle por cuenta'):
            tabla([(k,(v if CUENTAS[k][0].startswith('Activo') else v*CUENTAS[k][1])) for k,v in rep['saldos'].items()])
            if rep['saldos']['Inventarios']<-.005:
                st.warning('Inventario negativo: registra apertura, compras o revisa costos de ventas.')
    with t4:
        st.markdown('### Capturar cobros, pagos y asientos contables')
        st.info('Las ventas fechadas generan automáticamente Clientes / Ventas, costo de ventas / Inventarios y gastos de canal / Proveedores. No repitas esas partidas en asientos manuales. El catálogo es presupuesto y no genera gastos reales.')
        tipo=st.selectbox('Tipo de movimiento',['Cobro de venta','Reembolso de venta','Gasto fijo','Gasto variable','Compra de inventario','Compra de equipo','Depreciación','Amortización','Impuesto devengado','Pago de impuestos','Préstamo recibido','Pago de préstamo','Aportación de capital','Apertura','Otro asiento'])
        if tipo in ['Cobro de venta','Reembolso de venta']:
            elegibles=[r for r in datos['operaciones'] if activo(r) and r.get('Fecha')]
            if elegibles:
                seleccion=st.selectbox('Venta vinculada',[r['ID'] for r in elegibles],format_func=lambda x:next(r['Referencia']+' · '+r['Canal'] for r in elegibles if r['ID']==x))
                with st.form('cobro_'+tipo):
                    fecha=st.date_input('Fecha del movimiento efectivo',hoy_local(),key='fecha_cobro')
                    importe=st.number_input('Importe efectivamente cobrado / reembolsado',min_value=.01,value=1.0)
                    referencia=st.text_input('Referencia bancaria / recibo')
                    enviar=st.form_submit_button('Registrar movimiento')
                if enviar:
                    venta=next(r for r in elegibles if r['ID']==seleccion)
                    anteriores=[a for a in datos['asientos'] if not a.get('Anulada') and a.get('Venta ID')==seleccion]
                    cobrado=sum(l['Debe']-l['Haber'] for a in anteriores for l in a['Líneas'] if l['Cuenta']=='Efectivo')
                    total=neta(venta)+venta['Ingresos Envío']
                    delta=importe if tipo=='Cobro de venta' else -importe
                    if fecha.isoformat()<venta['Fecha']:
                        st.error('El movimiento no puede ser anterior a la venta; registra anticipos con Otro asiento.')
                    elif not referencia.strip():
                        st.error('Captura una referencia del movimiento.')
                    elif any(a.get('Referencia','').casefold()==referencia.strip().casefold() for a in datos['asientos']):
                        st.error('Ya existe esa referencia de asiento, incluso si fue anulado.')
                    elif (delta>0 and cobrado+delta>total+.005) or (delta<0 and cobrado+delta<-.005):
                        st.error('El cobro supera la venta neta o el reembolso supera el efectivo cobrado. Corrige primero la venta si corresponde.')
                    else:
                        ls=[cargo('Efectivo',importe),abono('Clientes',importe)] if delta>0 else [cargo('Clientes',importe),abono('Efectivo',importe)]
                        asiento=fila_asiento(fecha.isoformat(),ls,Tipo=tipo,Flujo='Operación',Referencia=referencia.strip(),**{'Venta ID':seleccion})
                        datos['asientos'].append(asiento)
                        evento(datos,'Asiento',None,asiento)
                        guardar_y_actualizar()
            else:
                st.info('Primero confirma una venta y su fecha.')
        else:
            pares={
                'Gasto fijo':('Gasto operativo fijo','Efectivo','Operación'),
                'Gasto variable':('Gasto operativo variable','Efectivo','Operación'),
                'Compra de inventario':('Inventarios','Efectivo','Operación'),
                'Compra de equipo':('Equipo','Efectivo','Inversión'),
                'Depreciación':('Depreciación','Depreciación acumulada','Operación'),
                'Amortización':('Amortización','Amortización acumulada','Operación'),
                'Impuesto devengado':('Impuestos','Impuestos por pagar','Operación'),
                'Pago de impuestos':('Impuestos por pagar','Efectivo','Operación'),
                'Préstamo recibido':('Efectivo','Deuda largo plazo','Financiamiento'),
                'Pago de préstamo':('Deuda largo plazo','Efectivo','Financiamiento'),
                'Aportación de capital':('Efectivo','Capital','Financiamiento'),
                'Apertura':('Efectivo','Capital','Sin clasificar'),
                'Otro asiento':('Efectivo','Capital','Sin clasificar')}
            deb,hab,flujo=pares[tipo]
            st.caption('Edita las cuentas y los importes antes de guardar. Para un gasto pendiente de pago, abona Proveedores; para pagar después, carga Proveedores y abona Efectivo. La apertura admite múltiples activos, pasivos y capital.')
            with st.form('asiento_'+tipo):
                fecha=st.date_input('Fecha de devengo / movimiento',hoy_local())
                referencia=st.text_input('Referencia única')
                descripcion=st.text_input('Concepto / soporte')
                flujo_sel=st.selectbox('Clasificación de los movimientos de efectivo',['Operación','Inversión','Financiamiento','Sin clasificar'],index=['Operación','Inversión','Financiamiento','Sin clasificar'].index(flujo))
                editor=st.data_editor(pd.DataFrame([cargo(deb,0),abono(hab,0)]),num_rows='dynamic',hide_index=True,width="stretch",
                    column_config={'Cuenta':st.column_config.SelectboxColumn('Cuenta',options=list(CUENTAS),required=True),
                                   'Debe':st.column_config.NumberColumn('Debe',min_value=0.0,required=True),
                                   'Haber':st.column_config.NumberColumn('Haber',min_value=0.0,required=True)})
                cert_apertura=st.checkbox('Confirmo que esta apertura contiene todos los saldos y corresponde al cierre anterior al inicio de los reportes') if tipo=='Apertura' else False
                enviar=st.form_submit_button('Guardar asiento')
            if enviar:
                try:
                    if not referencia.strip() or not descripcion.strip():
                        raise ValueError('Referencia y concepto son obligatorios.')
                    if any(a.get('Referencia','').casefold()==referencia.strip().casefold() for a in datos['asientos']):
                        raise ValueError('Referencia de asiento duplicada, incluso si está anulado.')
                    lineas=editor.to_dict('records')
                    if tipo=='Apertura':
                        if any(a.get('Tipo')=='Apertura' and not a.get('Anulada') for a in datos['asientos']):
                            raise ValueError('Ya existe una apertura activa. Anúlala antes de reemplazarla.')
                        if any(CUENTAS[l['Cuenta']][0] not in ['Activo circulante','Activo no circulante','Pasivo corto plazo','Pasivo largo plazo','Capital'] for l in lineas):
                            raise ValueError('La apertura solo admite cuentas patrimoniales; usa Resultados anteriores para utilidades acumuladas.')
                        if any(a['Fecha']<=fecha.isoformat() for a in asientos(datos)):
                            raise ValueError('La apertura debe ser anterior a todas las operaciones y asientos existentes.')
                    a=fila_asiento(fecha.isoformat(),lineas,Tipo=tipo,Flujo=flujo_sel,Referencia=referencia.strip(),Concepto=descripcion)
                    datos['asientos'].append(a)
                    if tipo=='Apertura':
                        datos['apertura_confirmada']=cert_apertura
                        datos['fecha_apertura']=fecha.isoformat()
                    evento(datos,'Asiento',None,a)
                    guardar_y_actualizar()
                except (ValueError,KeyError,TypeError) as e:
                    st.error('No se guardó el asiento: '+str(e))
        st.markdown('### Asientos registrados y anulación')
        st.json(datos['asientos'])
        activos=[a for a in datos['asientos'] if not a.get('Anulada')]
        if activos:
            with st.form('anular_asiento'):
                aid=st.selectbox('Asiento a anular',[a['ID'] for a in activos],format_func=lambda x:next(a.get('Referencia',x) for a in activos if a['ID']==x))
                confirma=st.checkbox('Confirmo que este asiento se cargó por error')
                if st.form_submit_button('Anular asiento'):
                    if confirma:
                        a=next(a for a in datos['asientos'] if a['ID']==aid)
                        previo=copy.deepcopy(a)
                        a['Anulada']=True
                        if a['Tipo']=='Apertura':
                            datos['apertura_confirmada']=False
                            datos['fecha_apertura']=None
                        evento(datos,'Anulación de asiento',previo,a)
                        guardar_y_actualizar()
                    else:
                        st.error('Confirma la anulación.')
        st.markdown('### Confirmar información completa')
        st.caption('Solo confirma después de verificar ventas y devoluciones, costos, inventarios, gastos devengados, impuestos, depreciación, cobros y pagos. Esto confirma cobertura; no sustituye captura ni revisión contable.')
        with st.form('cobertura'):
            conf=st.checkbox(f'Verifiqué que la información de {inicio} a {fin} está completa')
            if st.form_submit_button('Confirmar cobertura del periodo'):
                if conf:
                    if any(activo(r) and not r.get('Fecha') for r in datos['operaciones']):
                        st.error('Primero fecha o desglosa los registros activos pendientes, o anula los que se cargaron por error.')
                    elif faltan_costos:
                        st.error('Primero confirma el costo de todas las ventas del periodo.')
                    elif fin>hoy_local().isoformat():
                        st.error('No se puede confirmar un periodo futuro; usa un rango hasta hoy.')
                    else:
                        c={'Inicio':inicio,'Fin':fin}
                        if c not in datos['cobertura']:
                            datos['cobertura'].append(c)
                            evento(datos,'Cobertura',None,c)
                        guardar_y_actualizar()
                else:
                    st.error('Confirma que verificaste la información.')
        st.write('Periodos confirmados:',datos['cobertura'])
        if st.button('Revocar confirmaciones de cobertura'):
            evento(datos,'Cobertura',datos['cobertura'],[])
            datos['cobertura']=[]
            guardar_y_actualizar()
        export=[]
        for a in rep['ledger']:
            for l in a['Líneas']:
                export.append({'ID':a['ID'],'Fecha':a['Fecha'],'Tipo':a['Tipo'],**l})
        st.download_button('📥 Exportar libro contable CSV',pd.DataFrame(export).to_csv(index=False).encode('utf-8-sig'),'libro_contable.csv','text/csv')

# Persistir también edición del catálogo y parámetros sin perder el resto.
if menu=='📋 Catálogo de Costos & Configuración':
    candidato=st.session_state.catalogo_df
    try:
        if candidato.isna().any().any():
            raise ValueError('Completa todas las celdas del catálogo antes de guardarlo.')
        filas=candidato.to_dict('records')
        for row in filas:
            if not math.isfinite(float(row['Importe Base'])) or float(row['Importe Base'])<0:
                raise ValueError('Los importes deben ser finitos y no negativos.')
        costos_catalogo(filas,st.session_state.tc_usd,st.session_state.vol_prod)
        datos['catalogo']=filas
        datos['config']={k:st.session_state[k] for k in ['tc_usd','vol_prod','precio_venta']}
        if datos != antes_ejecucion:
            evento(datos,'Configuración y catálogo',{'config':antes_ejecucion['config'],'catalogo':antes_ejecucion['catalogo']},
                   {'config':datos['config'],'catalogo':datos['catalogo']})
            guardar_y_actualizar()
    except (ValueError,TypeError,KeyError) as e:
        st.error('El catálogo no se guardó: '+str(e))

st.sidebar.markdown('---')
st.sidebar.download_button('📦 Respaldo completo JSON',json.dumps(datos,ensure_ascii=False,indent=2).encode('utf-8'),
                           'respaldo_legado_verde.json','application/json')
with st.sidebar.expander('Restaurar respaldo completo'):
    archivo=st.file_uploader('Respaldo generado por este sistema',type=['json'])
    confirma=st.checkbox('Confirmo reemplazar los datos del servidor por este respaldo')
    if st.button('Restaurar respaldo'):
        if archivo and confirma:
            try:
                restaurado=json.load(archivo)
                for k in ['operaciones','catalogo','config','asientos','historial','cobertura','apertura_confirmada']:
                    if k not in restaurado:
                        raise ValueError('El respaldo no contiene '+k)
                if len({r['ID'] for r in restaurado['operaciones']})!=len(restaurado['operaciones']):
                    raise ValueError('El respaldo contiene IDs duplicados.')
                costos_catalogo(restaurado['catalogo'],restaurado['config']['tc_usd'],restaurado['config']['vol_prod'])
                if restaurado['config']['vol_prod']<=0 or restaurado['config']['precio_venta']<=0:
                    raise ValueError('Configuración inválida.')
                for r in restaurado['operaciones']:
                    if r.get('Fecha'):
                        validar_venta(r,restaurado['operaciones'])
                for a in restaurado['asientos']:
                    fila_asiento(a['Fecha'],a['Líneas'])
                json.dumps(restaurado,allow_nan=False)
                evento(restaurado,'Restauración',None,{'Fecha':hoy_local().isoformat()})
                datos=restaurado
                guardar_y_actualizar()
            except (ValueError,KeyError,TypeError,ZeroDivisionError) as e:
                st.error('Respaldo inválido: '+str(e))
        else:
            st.error('Selecciona un respaldo y confirma su restauración.')
