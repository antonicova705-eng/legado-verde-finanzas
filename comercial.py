"""Lógica del recorrido comercial e histórico por canal; independiente de Streamlit.

Convenciones:
- Los registros históricos heredados se agrupan por su campo 'Mes' tal como fue
  reportado; no se inventan fechas exactas.
- Todo lo calculado con el catálogo de costos es ESTIMACIÓN (presupuesto), no dato real.
"""
from datetime import date, datetime, timedelta
from uuid import uuid4

ETAPAS = ['Nuevo', 'Contactado', 'Muestra enviada', 'Negociación', 'Cliente', 'Perdido']
TIPOS_PROSPECTO = ['Cafetería', 'Consumidor final', 'Tienda / distribuidor', 'Otro']
ORIGENES = ['Formulario web (Shopify)', 'Mercado Libre', 'Amazon', 'Redes sociales', 'Referido', 'Visita directa', 'Otro']
ESTADOS_PEDIDO = ['Por surtir', 'Enviado', 'Entregado', 'Cancelado']


def asegurar_estructura(datos):
    """Agrega las tablas nuevas sin tocar las existentes. Devuelve True si cambió algo."""
    cambio = False
    for k, v in {'prospectos': [], 'pedidos': [], 'inventario': [], 'ia_historial': []}.items():
        if k not in datos:
            datos[k] = v
            cambio = True
    return cambio


# ---------------------------------------------------------------- Histórico
def historico_por_canal(operaciones, cv_unitario):
    """Resumen por canal de los registros reportados (incluye los que no tienen fecha exacta)."""
    canales = {}
    for r in operaciones:
        if r.get('Anulada') or r.get('Estado') == 'Cancelado':
            continue
        c = canales.setdefault(r['Canal'], {'Canal': r['Canal'], 'Registros': 0, 'Sobres': 0,
                                            'Ventas producto': 0.0, 'Ingresos envío': 0.0,
                                            'Comisiones': 0.0, 'Logística': 0.0, 'Ajustes': 0.0,
                                            'Remanente reportado': 0.0})
        c['Registros'] += 1
        c['Sobres'] += int(r.get('Cantidad', 0))
        c['Ventas producto'] += float(r.get('Ventas Producto', 0)) - float(r.get('Descuento', 0)) - float(r.get('Devolución', 0))
        c['Ingresos envío'] += float(r.get('Ingresos Envío', 0))
        c['Comisiones'] += float(r.get('Comisiones', 0))
        c['Logística'] += float(r.get('Costos Logísticos', 0))
        c['Ajustes'] += float(r.get('Ajustes', 0))
        c['Remanente reportado'] += float(r.get('Remanente', 0))
    filas = []
    for c in canales.values():
        esperado = c['Ventas producto'] + c['Ingresos envío'] - c['Comisiones'] - c['Logística'] + c['Ajustes']
        c['Deducciones no explicadas'] = round(esperado - c['Remanente reportado'], 2)
        c['Remanente por sobre'] = c['Remanente reportado'] / c['Sobres'] if c['Sobres'] else None
        c['Costo producto estimado'] = c['Sobres'] * cv_unitario
        c['Contribución estimada'] = c['Remanente reportado'] - c['Costo producto estimado']
        c['Contribución por sobre (est.)'] = c['Contribución estimada'] / c['Sobres'] if c['Sobres'] else None
        filas.append(c)
    return sorted(filas, key=lambda x: -x['Ventas producto'])


def historico_por_mes(operaciones):
    """Ventas de producto por 'Mes' reportado y canal."""
    filas = []
    for r in operaciones:
        if r.get('Anulada') or r.get('Estado') == 'Cancelado':
            continue
        filas.append({'Mes reportado': r.get('Mes') or 'Sin mes', 'Canal': r['Canal'],
                      'Sobres': int(r.get('Cantidad', 0)),
                      'Ventas producto': float(r.get('Ventas Producto', 0)) - float(r.get('Descuento', 0)) - float(r.get('Devolución', 0)),
                      'Fecha exacta': 'Sí' if r.get('Fecha') else 'No'})
    return filas


# ---------------------------------------------------------------- Escenarios
def escenario_mezcla(unidades, mezcla, neto_unitario, cv_unitario, cf_mensual):
    """mezcla: {canal: proporción}; neto_unitario: {canal: ingreso neto por sobre tras comisiones/envíos}."""
    total = sum(mezcla.values()) or 1
    contrib_unit = sum((p / total) * (neto_unitario[c] - cv_unitario) for c, p in mezcla.items())
    ingreso = sum(unidades * (p / total) * neto_unitario[c] for c, p in mezcla.items())
    resultado = unidades * contrib_unit - cf_mensual
    pe = cf_mensual / contrib_unit if contrib_unit > 0 else None
    return {'contribucion_unitaria': contrib_unit, 'ingreso_neto': ingreso,
            'resultado_operativo': resultado, 'pe_unidades': pe}


# ---------------------------------------------------------------- CRM
def nuevo_prospecto(nombre, tipo, origen, contacto, notas='', etapa='Nuevo', fecha=None):
    if not nombre.strip():
        raise ValueError('El nombre del prospecto es obligatorio.')
    if tipo not in TIPOS_PROSPECTO or origen not in ORIGENES or etapa not in ETAPAS:
        raise ValueError('Tipo, origen o etapa inválidos.')
    hoy = fecha or date.today().isoformat()
    return {'ID': 'P-' + uuid4().hex[:6].upper(), 'Nombre': nombre.strip(), 'Tipo': tipo, 'Origen': origen,
            'Contacto': contacto.strip(), 'Etapa': etapa, 'Notas': notas.strip(), 'Alta': hoy,
            'Último contacto': hoy, 'Próxima acción': ''}


# ---------------------------------------------------------------- Inventario
def existencias(datos):
    entradas = sum(m['Cantidad'] for m in datos['inventario'] if m['Tipo'] == 'Entrada')
    salidas = sum(m['Cantidad'] for m in datos['inventario'] if m['Tipo'] == 'Salida')
    return entradas - salidas


def movimiento_inventario(tipo, cantidad, concepto, fecha, referencia=''):
    if tipo not in ['Entrada', 'Salida'] or int(cantidad) <= 0:
        raise ValueError('Movimiento de inventario inválido.')
    date.fromisoformat(fecha)
    return {'ID': str(uuid4()), 'Fecha': fecha, 'Tipo': tipo, 'Cantidad': int(cantidad),
            'Concepto': concepto.strip(), 'Referencia': referencia}


# ---------------------------------------------------------------- Pedidos
def nuevo_pedido(datos, prospecto_id, canal, cantidad, precio, envio_costo, comision, fecha, ciclo_dias, cv_unitario):
    if int(cantidad) <= 0 or float(precio) < 0 or float(envio_costo) < 0 or float(comision) < 0:
        raise ValueError('Cantidad, precio y costos deben ser válidos.')
    if int(cantidad) > existencias(datos):
        raise ValueError(f'Inventario insuficiente: hay {existencias(datos)} sobres disponibles.')
    date.fromisoformat(fecha)
    venta = int(cantidad) * float(precio)
    costo_prod = int(cantidad) * cv_unitario
    margen = venta - costo_prod - float(envio_costo) - float(comision)
    folio = 'PED-' + uuid4().hex[:6].upper()
    return {'ID': folio, 'Prospecto ID': prospecto_id, 'Canal': canal, 'Fecha': fecha,
            'Cantidad': int(cantidad), 'Precio': float(precio), 'Venta': round(venta, 2),
            'Costo producto (est.)': round(costo_prod, 2), 'Envío': float(envio_costo),
            'Comisión': float(comision), 'Margen de contribución (est.)': round(margen, 2),
            'Margen %': round(margen / venta * 100, 1) if venta else None,
            'Ciclo recompra (días)': int(ciclo_dias),
            'Recompra sugerida': (date.fromisoformat(fecha) + timedelta(days=int(ciclo_dias))).isoformat(),
            'Estado': 'Por surtir', 'Enviado a contabilidad': False}


def pedido_a_venta(pedido, prospecto_nombre, producto='Guacamole Liofilizado 40g'):
    """Convierte un pedido entregado en venta contable; el costo queda pendiente de confirmar."""
    f = date.fromisoformat(pedido['Fecha'])
    meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
    return {'ID': str(uuid4()), 'Fecha': pedido['Fecha'], 'Fecha confirmada': True,
            'Mes': f'{meses[f.month-1]} {f.year}', 'Canal': pedido['Canal'],
            'Referencia': pedido['ID'], 'Producto': producto, 'Cantidad': pedido['Cantidad'],
            'Precio': pedido['Precio'], 'Ventas Producto': pedido['Venta'], 'Descuento': 0.0,
            'Devolución': 0.0, 'Costo de ventas': None, 'Costo confirmado': False,
            'Ingresos Envío': 0.0, 'Comisiones': pedido['Comisión'], 'Costos Logísticos': pedido['Envío'],
            'Remanente': round(pedido['Venta'] - pedido['Comisión'] - pedido['Envío'], 2),
            'Ajustes': 0.0, 'Estado': 'Entregado', 'Estado cobro': 'Por confirmar', 'Anulada': False,
            'Cliente': prospecto_nombre}


def recompras(datos, hoy, ventana=14):
    """Pedidos entregados cuya recompra sugerida cae en los próximos `ventana` días o ya venció."""
    out = []
    nombres = {p['ID']: p['Nombre'] for p in datos['prospectos']}
    limite = (date.fromisoformat(hoy) + timedelta(days=ventana)).isoformat()
    for p in datos['pedidos']:
        if p['Estado'] in ['Entregado', 'Enviado'] and p['Recompra sugerida'] <= limite:
            dias = (date.fromisoformat(p['Recompra sugerida']) - date.fromisoformat(hoy)).days
            out.append({'Pedido': p['ID'], 'Cliente': nombres.get(p['Prospecto ID'], '—'),
                        'Último pedido': p['Fecha'], 'Sobres': p['Cantidad'],
                        'Recompra sugerida': p['Recompra sugerida'],
                        'Situación': 'Vencida' if dias < 0 else f'En {dias} días'})
    return sorted(out, key=lambda x: x['Recompra sugerida'])


def embudo(datos):
    return {e: sum(1 for p in datos['prospectos'] if p['Etapa'] == e) for e in ETAPAS}
