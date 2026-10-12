"""Cálculos contables y persistencia; independiente de Streamlit."""
import calendar
import copy
import json
import math
import sqlite3
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

MESES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
CUENTAS = {
 'Efectivo': ('Activo circulante', 1),
 'Clientes': ('Activo circulante', 1),
 'Inventarios': ('Activo circulante', 1),
 'Otros activos circulantes': ('Activo circulante', 1),
 'Equipo': ('Activo no circulante', 1),
 'Depreciación acumulada': ('Activo no circulante', -1),
 'Amortización acumulada': ('Activo no circulante', -1),
 'Otros activos no circulantes': ('Activo no circulante', 1),
 'Proveedores': ('Pasivo corto plazo', -1),
 'Impuestos por pagar': ('Pasivo corto plazo', -1),
 'Deuda corto plazo': ('Pasivo corto plazo', -1),
 'Deuda largo plazo': ('Pasivo largo plazo', -1),
 'Capital': ('Capital', -1),
 'Resultados anteriores': ('Capital', -1),
 'Ventas': ('Ingreso', -1),
 'Costo de ventas': ('Costo', 1),
 'Gasto operativo fijo': ('Gasto', 1),
 'Gasto operativo variable': ('Gasto', 1),
 'Depreciación': ('Depreciación', 1),
 'Amortización': ('Amortización', 1),
 'Ingreso financiero': ('Financiero', -1),
 'Gasto financiero': ('Financiero', 1),
 'Impuestos': ('Impuestos', 1),
}

class Conflicto(Exception):
 pass

class Almacen:
 def __init__(self, path):
  self.path = Path(path)
  self.path.parent.mkdir(parents=True, exist_ok=True)
  with self.conectar() as db:
   db.execute('CREATE TABLE IF NOT EXISTS estado (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, datos TEXT NOT NULL)')
 def conectar(self):
  return sqlite3.connect(str(self.path), timeout=15)
 def leer(self):
  with self.conectar() as db:
   row = db.execute('SELECT revision,datos FROM estado WHERE id=1').fetchone()
  return (row[0], json.loads(row[1])) if row else (0, None)
 def guardar(self, datos, revision):
  encoded = json.dumps(datos, ensure_ascii=False, allow_nan=False)
  with self.conectar() as db:
   db.execute('BEGIN IMMEDIATE')
   row = db.execute('SELECT revision FROM estado WHERE id=1').fetchone()
   actual = row[0] if row else 0
   if actual != revision:
    raise Conflicto('Otro usuario modificó los datos. Recarga y vuelve a realizar el cambio.')
   db.execute('INSERT OR REPLACE INTO estado VALUES (1,?,?)',(actual+1,encoded))
  return actual+1

def migrar(ops):
 resultado = copy.deepcopy(ops)
 for r in resultado:
  # No convertir resúmenes mensuales en fechas de venta inventadas.
  for k,v in {'Fecha':None,'Descuento':0.0,'Devolución':0.0,'Costo de ventas':None,
              'Costo confirmado':False,'Precio':None,'Estado cobro':'Por confirmar',
              'Anulada':False,'Fecha confirmada':False}.items():
   r.setdefault(k,v)
  if r['Precio'] is None and r.get('Cantidad',0):
   r['Precio'] = r['Ventas Producto']/r['Cantidad']
  if r.get('Estado') == 'Cancelado':
   r['Anulada'] = True
 return resultado

def activo(r):
 return not r.get('Anulada',False) and r.get('Estado') != 'Cancelado'

def neta(r):
 return float(r['Ventas Producto'])-float(r.get('Descuento',0))-float(r.get('Devolución',0))

def en_periodo(r, inicio, fin):
 return activo(r) and r.get('Fecha') and inicio <= r['Fecha'] <= fin

def validar_venta(r, ops):
 if any(x['ID'] != r['ID'] and x['Canal']==r['Canal'] and x['Referencia'].strip().casefold()==r['Referencia'].strip().casefold() for x in ops):
  raise ValueError('Ya existe esta referencia en el mismo canal, incluso si está anulada.')
 if not r['Referencia'].strip() or not r['Producto'].strip():
  raise ValueError('Referencia y producto son obligatorios.')
 date.fromisoformat(r['Fecha'])
 if r['Cantidad'] <= 0:
  raise ValueError('La cantidad debe ser positiva.')
 for k in ['Precio','Ventas Producto','Descuento','Devolución','Comisiones','Costos Logísticos','Ingresos Envío']:
  if not math.isfinite(float(r[k])) or float(r[k]) < 0:
   raise ValueError(f'{k}: usa un importe finito no negativo.')
 if neta(r)<0:
  raise ValueError('Descuentos y devoluciones no pueden superar la venta.')
 if r.get('Costo de ventas') is not None and (not math.isfinite(float(r['Costo de ventas'])) or r['Costo de ventas']<0):
  raise ValueError('El costo de ventas debe ser no negativo.')

def evento(datos, entidad, antes, despues):
 if entidad in ['Venta','Anulación de venta','Asiento','Anulación de asiento']:
  datos['cobertura'] = []  # Reconfirmar cobertura tras cambiar operaciones contables.
 datos['historial'].append({'ID':str(uuid4()),'Fecha UTC':datetime.utcnow().isoformat(timespec='seconds'),
                           'Entidad':entidad,'Antes':copy.deepcopy(antes),'Después':copy.deepcopy(despues)})

def fila_asiento(fecha, lineas, **extra):
 if extra.get('Flujo', 'Sin clasificar') not in ['Operación','Inversión','Financiamiento','Sin clasificar']:
  raise ValueError('Clasificación de flujo inválida.')
 for l in lineas:
  if l['Cuenta'] not in CUENTAS or any(not math.isfinite(float(l[k])) or float(l[k]) < 0 for k in ['Debe','Haber']):
   raise ValueError('Cuenta o importe inválido.')
  if l['Debe'] and l['Haber']:
   raise ValueError('Cada línea debe llevar un cargo o un abono, no ambos.')
 if abs(sum(l['Debe']-l['Haber'] for l in lineas))>0.005 or not any(l['Debe'] for l in lineas):
  raise ValueError('El asiento debe tener cargos y abonos positivos e iguales.')
 date.fromisoformat(fecha)
 return {'ID':str(uuid4()),'Fecha':fecha,'Líneas':lineas,'Anulada':False,**extra}

def cargo(cuenta, monto):
 return {'Cuenta':cuenta,'Debe':round(monto,2),'Haber':0.0}

def abono(cuenta, monto):
 return {'Cuenta':cuenta,'Debe':0.0,'Haber':round(monto,2)}

def asientos(datos):
 """Ventas devengadas; cobros y pagos solo mediante asientos independientes."""
 out=[]
 ids={r['ID'] for r in datos['operaciones'] if activo(r)}
 for a in datos['asientos']:
  if not a.get('Anulada') and (not a.get('Venta ID') or a['Venta ID'] in ids):
   out.append(a)
 for r in datos['operaciones']:
  if not activo(r) or not r.get('Fecha'):
   continue
  total=round(neta(r)+r.get('Ingresos Envío',0),2)
  ls=[cargo('Clientes',total),abono('Ventas',total)]
  if r.get('Costo confirmado') and r.get('Costo de ventas') is not None:
   c=r['Costo de ventas']
   ls += [cargo('Costo de ventas',c),abono('Inventarios',c)]
  gastos=r.get('Comisiones',0)+r.get('Costos Logísticos',0)
  if gastos:
   ls += [cargo('Gasto operativo variable',gastos),abono('Proveedores',gastos)]
  # Ajustes y remanente heredados no tienen naturaleza contable verificada.
  out.append({'ID':'AUTO-'+r['ID'],'Fecha':r['Fecha'],'Líneas':ls,'Tipo':'Venta automática','Venta ID':r['ID']})
 return out

def reporte(datos, inicio, fin):
 ledger=asientos(datos)
 mov={k:0.0 for k in CUENTAS}
 sal={k:0.0 for k in CUENTAS}
 inicial=0.0
 flujos={'Operación':0.0,'Inversión':0.0,'Financiamiento':0.0,'Sin clasificar':0.0}
 for a in ledger:
  for l in a['Líneas']:
   v=l['Debe']-l['Haber']
   if a['Fecha']<=fin:
    sal[l['Cuenta']]+=v
   if a['Fecha']<inicio and l['Cuenta']=='Efectivo':
    inicial+=v
   if inicio<=a['Fecha']<=fin and a.get('Tipo')!='Apertura':
    mov[l['Cuenta']]+=v
    if l['Cuenta']=='Efectivo':
     flujos[a.get('Flujo','Sin clasificar')]+=v
   elif inicio<=a['Fecha']<=fin and a.get('Tipo')=='Apertura' and l['Cuenta']=='Efectivo':
    flujos['Sin clasificar']+=v
 ventas=-mov['Ventas']
 costo=mov['Costo de ventas']
 gasto=mov['Gasto operativo fijo']+mov['Gasto operativo variable']
 ebitda=ventas-costo-gasto
 da=mov['Depreciación']+mov['Amortización']
 financiero=-mov['Ingreso financiero']-mov['Gasto financiero']
 utilidad=ebitda-da+financiero-mov['Impuestos']
 resultado_acum=-sum(sal[k] for k,(grupo,_) in CUENTAS.items() if grupo in ['Ingreso','Costo','Gasto','Depreciación','Amortización','Financiero','Impuestos'])
 # Contra-activos se muestran negativos dentro del activo.
 grupos={g:0.0 for g in ['Activo circulante','Activo no circulante','Pasivo corto plazo','Pasivo largo plazo','Capital']}
 for k,(g,signo) in CUENTAS.items():
  if g in grupos:
   grupos[g] += sal[k] if g.startswith('Activo') else -sal[k]
 grupos['Capital']+=resultado_acum
 activos=grupos['Activo circulante']+grupos['Activo no circulante']
 pasivos=grupos['Pasivo corto plazo']+grupos['Pasivo largo plazo']
 return {'ventas':ventas,'costo':costo,'gasto':gasto,'ebitda':ebitda,'da':da,'operativa':ebitda-da,
         'financiero':financiero,'impuestos':mov['Impuestos'],'utilidad':utilidad,'mov':mov,'saldos':sal,
         'grupos':grupos,'descuadre':activos-pasivos-grupos['Capital'],'flujos':flujos,
         'efectivo_inicial':inicial,'efectivo_final':sal['Efectivo'],'ledger':ledger}

def calculo_pe(datos,inicio,fin):
 r=reporte(datos,inicio,fin)
 ventas=r['ventas']
 variables=r['costo']+r['mov']['Gasto operativo variable']
 fijos=r['mov']['Gasto operativo fijo']+r['da']
 margen=(ventas-variables)/ventas if ventas>0 else None
 faltantes=[x['ID'] for x in datos['operaciones'] if en_periodo(x,inicio,fin) and not x.get('Costo confirmado')]
 meta=fijos/margen if margen and margen>0 and not faltantes else None
 return {'ventas':ventas,'variables':variables,'fijos':fijos,'margen':margen,'meta':meta,
         'avance':ventas/meta*100 if meta and meta>0 else None,'faltantes':faltantes}

def costos_catalogo(cat,tc,vol):
 cv=cf=0.0
 for r in cat:
  importe=float(r['Importe Base'])*(tc if r['Moneda']=='USD' else 1)
  frecuencia=r['Frecuencia']
  if r['Clasificación']=='Variable':
   cv+=importe/vol if frecuencia=='Mensual' else importe/(12*vol) if frecuencia=='Anual' else importe
  elif r['Clasificación']=='Fijo':
   cf+=importe/12 if frecuencia=='Anual' else importe if frecuencia=='Mensual' else importe*vol
 return cv,cf
