"""Vistas nuevas del ecosistema: histórico por canal, simulador por mezcla, flujo comercial y asistente IA."""
import copy
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import comercial as cm
import ia

VERDE, LIMA, ROJO = '#0B5127', '#8EB712', '#d90429'


def _m(v):
    return f'${v:,.2f}' if v is not None else '—'


# =====================================================================
# HISTÓRICO Y MARGEN REAL POR CANAL
# =====================================================================
def vista_historico(datos, cv_unitario):
    st.subheader('📈 Histórico reportado y margen por canal')
    st.info('Esta vista usa los registros tal como fueron reportados por cada plataforma, **incluidos los que aún no tienen '
            'fecha exacta**, agrupados por el campo "Mes". No sustituye a los estados financieros: sirve para analizar canales. '
            '**Costo de producto y contribución son ESTIMACIONES** con el costo variable unitario del catálogo '
            f'({_m(cv_unitario)} por sobre).')
    filas = cm.historico_por_canal(datos['operaciones'], cv_unitario)
    if not filas:
        st.warning('No hay registros activos.')
        return
    tot_v = sum(f['Ventas producto'] for f in filas)
    tot_s = sum(f['Sobres'] for f in filas)
    tot_rem = sum(f['Remanente reportado'] for f in filas)
    tot_c = sum(f['Contribución estimada'] for f in filas)
    a, b, c, d = st.columns(4)
    a.metric('Ventas de producto reportadas', _m(tot_v))
    b.metric('Sobres vendidos', f'{tot_s:,}')
    c.metric('Remanente reportado (hecho)', _m(tot_rem))
    d.metric('Contribución después de producto (est.)', _m(tot_c))

    fig = go.Figure()
    fig.add_bar(x=[f['Canal'] for f in filas], y=[f['Ventas producto'] for f in filas], name='Ventas producto', marker_color=LIMA)
    fig.add_bar(x=[f['Canal'] for f in filas], y=[f['Remanente reportado'] for f in filas], name='Remanente reportado', marker_color=VERDE)
    fig.add_bar(x=[f['Canal'] for f in filas], y=[f['Contribución estimada'] for f in filas], name='Contribución (est.)',
                marker_color=[VERDE if f['Contribución estimada'] >= 0 else ROJO for f in filas], marker_pattern_shape='/')
    fig.update_layout(barmode='group', yaxis_title='MXN', title='¿Cuánto deja cada canal?',
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, width='stretch')

    df = pd.DataFrame(filas)
    cols = ['Canal', 'Registros', 'Sobres', 'Ventas producto', 'Ingresos envío', 'Comisiones', 'Logística', 'Ajustes',
            'Deducciones no explicadas', 'Remanente reportado', 'Remanente por sobre', 'Costo producto estimado',
            'Contribución estimada', 'Contribución por sobre (est.)']
    st.dataframe(df[cols], hide_index=True, width='stretch',
                 column_config={k: st.column_config.NumberColumn(k, format='$%.2f') for k in cols[3:]})

    alertas = []
    for f in filas:
        if abs(f['Deducciones no explicadas']) > 1:
            alertas.append(f"**{f['Canal']}**: la plataforma descontó {_m(f['Deducciones no explicadas'])} que no están registrados "
                           'como comisión o logística (probablemente envíos, cargos fijos o publicidad). Mientras no se clasifiquen, '
                           'el margen por concepto está incompleto.')
        if f['Contribución estimada'] < 0:
            alertas.append(f"**{f['Canal']}**: contribución estimada negativa ({_m(f['Contribución estimada'])}); "
                           'cada sobre vendido aquí no cubre su propio costo de producto.')
    for x in alertas:
        st.warning(x)

    st.markdown('#### Ventas por mes reportado')
    meses = pd.DataFrame(cm.historico_por_mes(datos['operaciones']))
    if not meses.empty:
        piv = meses.pivot_table(index='Mes reportado', columns='Canal', values='Ventas producto', aggfunc='sum', sort=False).fillna(0)
        fig2 = go.Figure([go.Bar(x=piv.index, y=piv[c], name=c) for c in piv.columns])
        fig2.update_layout(barmode='stack', yaxis_title='MXN', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig2, width='stretch')
        st.dataframe(meses, hide_index=True, width='stretch')
        st.caption('Los resúmenes de varios meses (por ejemplo Amazon) y los registros sin fecha se muestran en su etiqueta original.')


# =====================================================================
# SIMULADOR POR MEZCLA DE CANALES
# =====================================================================
def simulador_mezcla(datos, cv_unitario, cf_mensual, precio):
    st.markdown('---')
    st.subheader('🧭 Escenarios por mezcla de canales')
    st.caption('Supuesto editable: ingreso neto que queda por sobre en cada canal después de comisiones y envíos. '
               'Los valores iniciales salen del remanente histórico reportado; los canales sin historial usan el precio promedio.')
    hist = {f['Canal']: f['Remanente por sobre'] for f in cm.historico_por_canal(datos['operaciones'], cv_unitario)}
    base = [
        {'Canal': 'Mercado Libre', 'Neto por sobre': round(hist.get('Mercado Libre') or precio, 2), 'Mezcla %': 30},
        {'Canal': 'Amazon', 'Neto por sobre': round(hist.get('Amazon') or precio, 2), 'Mezcla %': 10},
        {'Canal': 'Cafeterías', 'Neto por sobre': round(hist.get('Cafeterías') or precio, 2), 'Mezcla %': 40},
        {'Canal': 'Tienda en línea (Shopify)', 'Neto por sobre': round(hist.get('Tienda en línea (Shopify)') or precio, 2), 'Mezcla %': 20},
    ]
    tabla = st.data_editor(pd.DataFrame(base), hide_index=True, width='stretch', key='mezcla',
                           column_config={'Neto por sobre': st.column_config.NumberColumn(format='$%.2f', min_value=0.0),
                                          'Mezcla %': st.column_config.NumberColumn(min_value=0, max_value=100)})
    unidades = st.slider('Sobres vendidos al mes', 50, 3000, 500, 50)
    mezcla = {r['Canal']: float(r['Mezcla %']) for r in tabla.to_dict('records')}
    neto = {r['Canal']: float(r['Neto por sobre']) for r in tabla.to_dict('records')}
    if sum(mezcla.values()) <= 0:
        st.error('La mezcla debe sumar más de 0%.')
        return
    r = cm.escenario_mezcla(unidades, mezcla, neto, cv_unitario, cf_mensual)
    a, b, c = st.columns(3)
    a.metric('Contribución por sobre (est.)', _m(r['contribucion_unitaria']))
    b.metric('Resultado operativo mensual (est.)', _m(r['resultado_operativo']))
    c.metric('Equilibrio con esta mezcla', f"{r['pe_unidades']:,.0f} sobres/mes" if r['pe_unidades'] else 'Sin equilibrio')
    xs = list(range(0, 3001, 100))
    fig = go.Figure()
    fig.add_scatter(x=xs, y=[cm.escenario_mezcla(x, mezcla, neto, cv_unitario, cf_mensual)['resultado_operativo'] for x in xs],
                    name='Resultado operativo', line=dict(color=VERDE))
    fig.add_hline(y=0, line_color=ROJO)
    fig.add_vline(x=unidades, line_dash='dot', line_color=LIMA)
    fig.update_layout(xaxis_title='Sobres / mes', yaxis_title='MXN', height=320, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, width='stretch')
    st.caption(f'Estimación con costos fijos del catálogo ({_m(cf_mensual)}/mes) y costo variable de producto {_m(cv_unitario)}/sobre. '
               'No es flujo de efectivo.')
    if suma := sum(mezcla.values()):
        if abs(suma - 100) > 0.5:
            st.info(f'La mezcla suma {suma:.0f}%; se normaliza a 100%.')


# =====================================================================
# FLUJO COMERCIAL: CAPTACIÓN → CRM → PEDIDO → INVENTARIO → MARGEN → RECOMPRA
# =====================================================================
def vista_flujo(datos, cv_unitario, precio, canales, guardar, hoy):
    st.subheader('🔄 Flujo comercial conectado')
    with st.expander('¿Qué es real y qué es simulado en este prototipo?', expanded=False):
        st.markdown(
            '- **Operativo (guarda datos reales en la base):** CRM de prospectos, pedidos, inventario de sobres terminados, '
            'cálculo de margen por pedido, alertas de recompra y envío del pedido a contabilidad.\n'
            '- **Semi-integrado:** importación de clientes desde el CSV que exporta Shopify.\n'
            '- **Simulado:** el formulario de captación replica el formulario del sitio; la conexión automática '
            'Shopify → CRM (webhook) queda como siguiente fase.\n'
            '- **Estimado:** el costo de producto por pedido usa el costo variable del catálogo.')
    pros = datos['prospectos']
    emb = cm.embudo(datos)
    st.plotly_chart(go.Figure(go.Funnel(y=list(emb), x=list(emb.values()), marker_color=VERDE)).update_layout(
        height=260, margin=dict(t=10, b=10), paper_bgcolor='rgba(0,0,0,0)'), width='stretch')
    t1, t2, t3, t4 = st.tabs(['1 · Captación y CRM', '2 · Pedidos y margen', '3 · Inventario', '4 · Recompra'])

    with t1:
        st.markdown('##### Formulario de captación (simulación del sitio web)')
        with st.form('captacion', clear_on_submit=True):
            a, b = st.columns(2)
            nombre = a.text_input('Nombre o negocio')
            contacto = b.text_input('Teléfono o correo')
            tipo = a.selectbox('Tipo', cm.TIPOS_PROSPECTO)
            origen = b.selectbox('Origen', cm.ORIGENES)
            notas = st.text_area('Mensaje / interés', height=70)
            if st.form_submit_button('Registrar prospecto'):
                try:
                    pros.append(cm.nuevo_prospecto(nombre, tipo, origen, contacto, notas, fecha=hoy))
                    guardar()
                except ValueError as e:
                    st.error(str(e))
        with st.expander('Importar clientes desde Shopify (CSV de Clientes → Exportar)'):
            arch = st.file_uploader('CSV de clientes de Shopify', type=['csv'], key='shopify_csv')
            if arch is not None and st.button('Importar como prospectos'):
                try:
                    df = pd.read_csv(arch)
                    col = {c.lower().strip(): c for c in df.columns}
                    existentes = {p['Contacto'].casefold() for p in pros if p['Contacto']}
                    n = 0
                    for _, r in df.iterrows():
                        nom = ' '.join(str(r.get(col.get(k, ''), '') or '') for k in ['first name', 'last name']).replace('nan', '').strip()
                        mail = str(r.get(col.get('email', ''), '') or '').replace('nan', '').strip()
                        tel = str(r.get(col.get('phone', ''), '') or '').replace('nan', '').strip()
                        cont = mail or tel
                        if not (nom or cont) or (cont and cont.casefold() in existentes):
                            continue
                        pros.append(cm.nuevo_prospecto(nom or cont, 'Consumidor final', 'Formulario web (Shopify)', cont,
                                                       'Importado de Shopify', etapa='Cliente', fecha=hoy))
                        existentes.add(cont.casefold())
                        n += 1
                    st.success(f'{n} clientes importados.')
                    guardar()
                except Exception as e:
                    st.error(f'No se pudo leer el archivo: {e}')
        st.markdown('##### Seguimiento (edita etapa, próxima acción y notas)')
        if pros:
            df = pd.DataFrame(pros)
            ed = st.data_editor(df, hide_index=True, width='stretch', key='crm_editor',
                                disabled=['ID', 'Alta', 'Origen'],
                                column_config={'Etapa': st.column_config.SelectboxColumn(options=cm.ETAPAS, required=True),
                                               'Tipo': st.column_config.SelectboxColumn(options=cm.TIPOS_PROSPECTO, required=True)})
            if st.button('Guardar seguimiento'):
                nuevos = ed.fillna('').to_dict('records')
                for p in nuevos:
                    original = next((x for x in pros if x['ID'] == p['ID']), None)
                    if original and original != p:
                        p['Último contacto'] = hoy
                datos['prospectos'] = nuevos
                guardar()
        else:
            st.caption('Aún no hay prospectos registrados.')

    with t2:
        stock = cm.existencias(datos)
        st.caption(f'Inventario disponible: **{stock:,} sobres**. Costo variable estimado por sobre: {_m(cv_unitario)}.')
        if not pros:
            st.info('Primero registra un prospecto o cliente.')
        else:
            with st.form('pedido'):
                a, b = st.columns(2)
                pid = a.selectbox('Cliente', [p['ID'] for p in pros], format_func=lambda x: next(p['Nombre'] for p in pros if p['ID'] == x))
                canal = b.selectbox('Canal', canales)
                cantidad = a.number_input('Sobres', 1, 100000, 10)
                pr = b.number_input('Precio por sobre', 0.0, value=float(precio), step=1.0)
                envio = a.number_input('Costo de envío del pedido', 0.0, value=0.0)
                comision = b.number_input('Comisión de plataforma / pago', 0.0, value=0.0)
                fecha = a.date_input('Fecha del pedido', date.fromisoformat(hoy))
                ciclo = b.number_input('Días estimados para recompra', 7, 180, 30)
                if st.form_submit_button('Registrar pedido y descontar inventario'):
                    try:
                        ped = cm.nuevo_pedido(datos, pid, canal, cantidad, pr, envio, comision, fecha.isoformat(), ciclo, cv_unitario)
                        datos['pedidos'].append(ped)
                        datos['inventario'].append(cm.movimiento_inventario('Salida', cantidad, 'Pedido ' + ped['ID'], fecha.isoformat(), ped['ID']))
                        for p in pros:
                            if p['ID'] == pid and p['Etapa'] != 'Cliente':
                                p['Etapa'] = 'Cliente'
                        guardar()
                    except ValueError as e:
                        st.error(str(e))
        if datos['pedidos']:
            nombres = {p['ID']: p['Nombre'] for p in pros}
            vista = [{'Cliente': nombres.get(p['Prospecto ID'], '—'), **p} for p in datos['pedidos']]
            st.dataframe(pd.DataFrame(vista), hide_index=True, width='stretch')
            activos = [p for p in datos['pedidos'] if p['Estado'] != 'Cancelado']
            if activos:
                m = sum(p['Margen de contribución (est.)'] for p in activos)
                v = sum(p['Venta'] for p in activos)
                st.metric('Margen de contribución de pedidos (est.)', _m(m), f'{m / v * 100:.1f}% de la venta' if v else None)
            with st.form('estado_pedido'):
                a, b = st.columns(2)
                folio = a.selectbox('Pedido', [p['ID'] for p in datos['pedidos']])
                estado = b.selectbox('Nuevo estado', cm.ESTADOS_PEDIDO)
                a_cont = st.checkbox('Al marcar Entregado, enviar a contabilidad como venta (costo queda por confirmar)', value=True)
                if st.form_submit_button('Actualizar pedido'):
                    p = next(x for x in datos['pedidos'] if x['ID'] == folio)
                    if p['Estado'] == 'Cancelado':
                        st.error('El pedido está cancelado.')
                    else:
                        if estado == 'Cancelado' and not p['Enviado a contabilidad']:
                            datos['inventario'].append(cm.movimiento_inventario('Entrada', p['Cantidad'], 'Cancelación ' + folio, hoy, folio))
                        elif estado == 'Cancelado':
                            st.error('Ya está en contabilidad: anula la venta en "Ventas por Canal" y registra la devolución.')
                            st.stop()
                        p['Estado'] = estado
                        if estado == 'Entregado' and a_cont and not p['Enviado a contabilidad']:
                            from motor import validar_venta, evento
                            venta = cm.pedido_a_venta(p, nombres.get(p['Prospecto ID'], ''))
                            try:
                                validar_venta(venta, datos['operaciones'])
                                datos['operaciones'].append(venta)
                                evento(datos, 'Venta', None, venta)
                                p['Enviado a contabilidad'] = True
                            except ValueError as e:
                                st.error('No se envió a contabilidad: ' + str(e))
                                st.stop()
                        guardar()

    with t3:
        st.metric('Sobres terminados disponibles', f'{cm.existencias(datos):,}')
        with st.form('inventario', clear_on_submit=True):
            a, b, c = st.columns(3)
            tipo = a.selectbox('Movimiento', ['Entrada', 'Salida'])
            cant = b.number_input('Sobres', 1, 100000, 100)
            f = c.date_input('Fecha', date.fromisoformat(hoy))
            concepto = st.text_input('Concepto (ej. lote de producción, merma, muestras)')
            if st.form_submit_button('Registrar movimiento'):
                try:
                    if tipo == 'Salida' and cant > cm.existencias(datos):
                        raise ValueError('La salida supera las existencias.')
                    datos['inventario'].append(cm.movimiento_inventario(tipo, cant, concepto or tipo, f.isoformat()))
                    guardar()
                except ValueError as e:
                    st.error(str(e))
        if datos['inventario']:
            st.dataframe(pd.DataFrame(datos['inventario']).drop(columns='ID'), hide_index=True, width='stretch')
        st.caption('Inventario en unidades (sobres terminados). Su valor contable se registra en Estados financieros.')

    with t4:
        rec = cm.recompras(datos, hoy)
        if rec:
            st.dataframe(pd.DataFrame(rec), hide_index=True, width='stretch')
            st.caption('Genera los mensajes personalizados en el módulo 🤖 Asistente IA → "Mensajes de recompra".')
        else:
            st.info('No hay recompras próximas (ventana de 14 días).')


# =====================================================================
# ASISTENTE IA
# =====================================================================
def vista_ia(datos, contexto, guardar):
    st.subheader('🤖 Asistente de IA (Claude)')
    st.caption('La IA analiza los datos del sistema, propone acciones y redacta contenido. **Toda salida requiere revisión '
               'humana antes de usarse.** El asistente solo recibe el resumen que ves abajo, no datos personales de contacto.')
    key = ia.clave_api(st.secrets if _hay_secrets() else None)
    if not key:
        st.warning('Falta configurar la clave de Claude. En Streamlit Cloud: **Settings → Secrets** y agrega:\n\n'
                   '```\nANTHROPIC_API_KEY = "sk-ant-..."\n```')
    tarea = st.selectbox('¿Qué necesitas?', list(ia.TAREAS) + ['Pregunta libre'])
    pregunta = st.text_area('Indicación adicional (opcional)' if tarea != 'Pregunta libre' else 'Tu pregunta',
                            placeholder='Ej.: ¿Conviene subir el precio en Mercado Libre a $75?')
    with st.expander('Datos que recibirá la IA'):
        st.json(contexto)
    if st.button('Generar con IA', disabled=not key):
        if tarea == 'Pregunta libre' and not pregunta.strip():
            st.error('Escribe tu pregunta.')
        else:
            with st.spinner('Analizando…'):
                try:
                    texto = ia.consultar(ia.construir_prompt(tarea, contexto, pregunta), key,
                                         ia.modelo(st.secrets if _hay_secrets() else None))
                    st.session_state['ia_ultima'] = {'Tarea': tarea, 'Pregunta': pregunta, 'Respuesta': texto,
                                                     'Fecha': datetime.now().isoformat(timespec='minutes')}
                except Exception as e:
                    st.error(f'No se pudo consultar a Claude: {e}')
    ult = st.session_state.get('ia_ultima')
    if ult:
        st.markdown('---')
        st.markdown(ult['Respuesta'])
        st.download_button('📥 Descargar respuesta', ult['Respuesta'].encode('utf-8'), 'analisis_ia_legado_verde.md', 'text/markdown')
        with st.form('revision_ia'):
            ok = st.checkbox('Revisé esta respuesta y la apruebo para usarla')
            nota = st.text_input('Comentario de revisión (qué se usará o qué se corrigió)')
            if st.form_submit_button('Guardar en bitácora de decisiones'):
                if ok:
                    datos['ia_historial'].append({**ult, 'Revisado': True, 'Comentario': nota})
                    st.session_state.pop('ia_ultima', None)
                    guardar()
                else:
                    st.error('Marca la revisión antes de guardar.')
    if datos['ia_historial']:
        with st.expander(f"Bitácora de decisiones apoyadas por IA ({len(datos['ia_historial'])})"):
            for h in reversed(datos['ia_historial']):
                st.markdown(f"**{h['Fecha']} · {h['Tarea']}** — {h.get('Comentario', '')}")
                st.markdown(h['Respuesta'])
                st.markdown('---')


def _hay_secrets():
    try:
        return len(st.secrets) >= 0
    except Exception:
        return False


def contexto_ia(datos, cv_unitario, cf_mensual, precio, pe_unidades, pe_pesos, hoy):
    """Resumen agregado y sin datos de contacto para enviar a la IA."""
    hist = cm.historico_por_canal(datos['operaciones'], cv_unitario)
    nombres = {p['ID']: p['Nombre'] for p in datos['prospectos']}
    return {
        'fecha_de_hoy': hoy,
        'nota': 'Remanente = lo que la plataforma reportó tras sus deducciones (hecho). Contribución = remanente menos costo '
                'de producto estimado con catálogo (estimación). Registros sin fecha exacta están pendientes de conciliar.',
        'historico_por_canal': [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in f.items()} for f in hist],
        'catalogo_presupuesto': {'precio_promedio': precio, 'costo_variable_unitario_est': round(cv_unitario, 2),
                                 'costos_fijos_mensuales_est': round(cf_mensual, 2),
                                 'punto_equilibrio_teorico_sobres_mes': pe_unidades,
                                 'punto_equilibrio_teorico_mxn_mes': round(pe_pesos, 2) if pe_pesos else None,
                                 'conceptos': [{k: r[k] for k in ['Concepto', 'Clasificación', 'Importe Base', 'Frecuencia', 'Estado']}
                                               for r in datos['catalogo']]},
        'crm': {'embudo': cm.embudo(datos),
                'prospectos': [{k: p[k] for k in ['Nombre', 'Tipo', 'Origen', 'Etapa', 'Notas', 'Próxima acción']} for p in datos['prospectos']][:40]},
        'pedidos': [{'Cliente': nombres.get(p['Prospecto ID'], '—'), **{k: p[k] for k in
                     ['Canal', 'Fecha', 'Cantidad', 'Precio', 'Margen de contribución (est.)', 'Estado', 'Recompra sugerida']}}
                    for p in datos['pedidos']][-40:],
        'inventario_sobres': cm.existencias(datos),
        'recompras_proximas': cm.recompras(datos, hoy),
    }
