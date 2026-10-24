"""Importación validada de ventas (JSON o CSV), p. ej. generadas por Claude.

Flujo: ``leer`` → ``previsualizar`` (no escribe) → confirmación del usuario →
``aplicar`` (una sola transacción: entran todas las filas confirmadas o ninguna).

Formato JSON (versión 1)::

    {"formato": "legado-verde-ventas", "version": 1,
     "ventas": [{"clave": "...", "fecha": "2026-10-23", "canal": "Cafeterías",
                 "presentacion": "Sobre individual", "presentaciones": 10,
                 "precio_presentacion": 60, "comisiones": null, "costo": null,
                 "cobro": {"fecha": "2026-10-23", "importe": 600,
                           "medio": "Transferencia", "referencia": null}}]}

``null`` significa *pendiente / desconocido*; nunca se convierte en cero
confirmado. La ``clave`` hace idempotente la importación: el mismo archivo
importado dos veces no duplica ventas ni cobros.
"""
from __future__ import annotations

import copy
import csv
import importlib
import io
import json

from . import operaciones as op
from .modelo import ORIGEN_IMPORTACION, canales, config_completa, construir_venta, importes, presentaciones
from .util import huella, numero, resolver_fecha

FORMATO = "legado-verde-ventas"

CAMPOS = ["clave", "fecha", "canal", "referencia", "cliente", "producto", "sku", "presentacion", "sobres_por_presentacion",
          "presentaciones", "precio_presentacion", "descuento", "devolucion", "sobres_devueltos",
          "envio", "comisiones", "logistica", "costo", "costo_confirmado", "estado", "notas",
          "cobro_fecha", "cobro_importe", "cobro_medio", "cobro_referencia"]


def _bool(v):
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "sí", "si", "verdadero", "x", "yes")


def _vacio(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def leer(contenido: bytes | str, nombre: str = "") -> list[dict]:
    texto = contenido.decode("utf-8-sig") if isinstance(contenido, bytes) else contenido
    if nombre.lower().endswith(".csv") or (not texto.lstrip().startswith(("{", "["))):
        filas = list(csv.DictReader(io.StringIO(texto)))
        ventas = []
        for f in filas:
            v = {k: (None if _vacio(f.get(k)) else f.get(k).strip()) for k in CAMPOS if k in f}
            cobro = None
            if any(not _vacio(f.get(k)) for k in ("cobro_fecha", "cobro_importe")):
                cobro = {"fecha": v.pop("cobro_fecha", None), "importe": v.pop("cobro_importe", None),
                         "medio": v.pop("cobro_medio", None), "referencia": v.pop("cobro_referencia", None)}
            for k in ("cobro_fecha", "cobro_importe", "cobro_medio", "cobro_referencia"):
                v.pop(k, None)
            v["cobro"] = cobro
            ventas.append(v)
        return ventas
    obj = json.loads(texto)
    if isinstance(obj, list):
        return obj
    if obj.get("formato") != FORMATO:
        raise ValueError(f"El archivo no es del formato «{FORMATO}».")
    if int(obj.get("version", 0)) != 1:
        raise ValueError("Versión de formato no soportada (se espera 1).")
    return obj.get("ventas", [])


def _entrada(v: dict) -> dict:
    """Normaliza una fila a la entrada de ``construir_venta``. Pendientes quedan en None."""
    fecha = resolver_fecha(v.get("fecha"))
    com = v.get("comisiones")
    log = v.get("logistica")
    costo = v.get("costo")
    e = {
        "fecha": fecha, "canal": v.get("canal"), "referencia": v.get("referencia") or "",
        "cliente": v.get("cliente"), "producto": v.get("producto"), "sku": v.get("sku"),
        "presentacion": v.get("presentacion") or "Sobre individual",
        "presentaciones": int(float(v["presentaciones"])) if not _vacio(v.get("presentaciones")) else None,
        "precio_presentacion": v.get("precio_presentacion"),
        "descuento": v.get("descuento"), "devolucion": v.get("devolucion"),
        "sobres_devueltos": None if _vacio(v.get("sobres_devueltos")) else int(float(v["sobres_devueltos"])),
        "envio": v.get("envio"),
        "comisiones": None if _vacio(com) else com, "logistica": None if _vacio(log) else log,
        "costo": None if _vacio(costo) else costo,
        "costo_confirmado": _bool(v.get("costo_confirmado")) and not _vacio(costo),
        "estado": v.get("estado") or "Entregado", "notas": v.get("notas"),
        "origen": ORIGEN_IMPORTACION,
    }
    if e["sobres_devueltos"] is None and not numero(v.get("devolucion") or 0):
        e["sobres_devueltos"] = 0  # sin dinero devuelto no hubo unidades devueltas
    return e


def _clave(v: dict, e: dict) -> str:
    if v.get("clave"):
        return str(v["clave"]).strip()
    # Sin clave explícita: huella del contenido (reimportar el mismo archivo no duplica).
    return "imp-" + huella({k: e.get(k) for k in ("fecha", "canal", "referencia", "presentacion",
                                                   "presentaciones", "precio_presentacion", "cliente")})


def previsualizar(datos: dict, ventas: list[dict]) -> list[dict]:
    """Valida sin escribir. Cada fila: estado, mensajes, pendientes, venta, cobro."""
    resultado, claves_vistas = [], set()
    canales_validos = set(canales(datos, solo_activos=False))
    pres = presentaciones(datos)
    try:
        nuevas = presentaciones_nuevas(datos, ventas)
    except (ValueError, TypeError) as ex:
        return [{"Fila": 1, "Estado": "Error", "Mensajes": [str(ex)], "Pendientes": [], "venta": None,
                 "cobro": None, "clave": None, "coincidencias": []}]
    if nuevas:
        datos = copy.deepcopy(datos)
        datos["config"].setdefault("presentaciones", copy.deepcopy(config_completa(datos)["presentaciones"]))
        datos["config"]["presentaciones"] += [{"Nombre": n, "Sobres": s} for n, s in nuevas.items()]
        pres = presentaciones(datos)
    for i, v in enumerate(ventas, start=1):
        fila = {"Fila": i, "Estado": "Nueva", "Mensajes": [], "Pendientes": [], "venta": None,
                "cobro": None, "clave": None, "coincidencias": []}
        try:
            if v.get("fecha") and resolver_fecha(v.get("fecha")) is None:
                raise ValueError(f"Fecha no reconocida: {v.get('fecha')!r}. Usa AAAA-MM-DD u «hoy».")
            e = _entrada(v)
            if str(v.get("fecha", "")).strip().lower() in ("hoy", "ayer"):
                fila["Mensajes"].append(f"Fecha relativa «{v['fecha']}» resuelta como {e['fecha']} "
                                        "(hora de Ciudad de México). Verifica que sea correcta.")
            if e["canal"] not in canales_validos:
                raise ValueError(f"Canal desconocido: {e['canal']!r}.")
            if e["presentacion"] not in pres:
                raise ValueError(f"Presentación no configurada: {e['presentacion']!r}. "
                                 "Agrégala en Configuración o incluye «sobres_por_presentacion» en el archivo.")
            if e["presentacion"] in nuevas:
                fila["Mensajes"].append(f"Se creará la presentación «{e['presentacion']}» con {nuevas[e['presentacion']]} sobres.")
            clave = _clave(v, e)
            e["clave"] = clave
            fila["clave"] = clave
            if clave in claves_vistas:
                raise ValueError("Clave repetida dentro del archivo; si son dos ventas reales, usa claves distintas.")
            claves_vistas.add(clave)
            venta = construir_venta(datos, e)
            fila["venta"] = venta
            existente = op.por_clave(datos, clave)
            if existente:
                fila["Estado"] = "Ya registrada"
                fila["Mensajes"].append(f"Se omitirá: ya existe con ID {existente['ID']}.")
            elif venta["Referencia"]:
                importlib.import_module("motor").validar_venta({**venta, "ID": "__vista_previa__"}, datos["operaciones"])
            else:
                fila["Mensajes"].append("Sin folio: se generará uno interno (INT-…).")
            c = v.get("cobro")
            if c:
                cf = resolver_fecha(c.get("fecha"))
                ci = numero(c.get("importe"))
                if cf is None or ci is None:
                    raise ValueError("El cobro necesita fecha e importe explícitos; si no los conoces, deja el cobro vacío.")
                fila["cobro"] = {"fecha": cf, "importe": ci, "medio": c.get("medio"),
                                 "referencia": c.get("referencia")}
                total = round(importes(venta)["ventas_netas_totales"], 2)
                if ci > total + 0.005:
                    raise ValueError(f"El cobro ({ci:,.2f}) supera la venta neta ({total:,.2f}).")
                if cf < venta["Fecha"]:
                    raise ValueError("El cobro no puede ser anterior a la venta.")
                if not c.get("referencia"):
                    fila["Pendientes"].append("Referencia bancaria del cobro")
            if not venta["Costo confirmado"]:
                fila["Pendientes"].append("Costo de ventas (margen, EBITDA y utilidad quedarán «No disponible»)")
            if not venta["Comisiones confirmadas"]:
                fila["Pendientes"].append("Comisiones")
            if not venta["Logística confirmada"]:
                fila["Pendientes"].append("Logística")
            if not venta.get("Cliente"):
                fila["Pendientes"].append("Cliente (opcional)")
            if fila["Estado"] == "Nueva":
                for r in datos["operaciones"]:
                    if (not r.get("Anulada") and r.get("Canal") == venta["Canal"] and r.get("Fecha") == venta["Fecha"]
                            and r.get("Cantidad") == venta["Cantidad"]
                            and abs(float(r.get("Ventas Producto") or 0) - venta["Ventas Producto"]) < 0.01):
                        fila["coincidencias"].append(r["ID"])
                if fila["coincidencias"]:
                    fila["Estado"] = "Posible duplicado"
                    fila["Mensajes"].append("Coincide en canal, fecha, sobres e importe con: "
                                            + ", ".join(fila["coincidencias"]) + ". Confírmala solo si es otra venta.")
        except (ValueError, KeyError, TypeError) as ex:
            fila["Estado"] = "Error"
            fila["Mensajes"].append(str(ex))
        resultado.append(fila)
    return resultado


def presentaciones_nuevas(datos: dict, ventas: list[dict]) -> dict[str, int]:
    """Presentaciones que el archivo define y aún no existen. Error si contradicen una existente."""
    pres = presentaciones(datos)
    nuevas: dict[str, int] = {}
    for v in ventas:
        nombre = (v.get("presentacion") or "").strip()
        if not nombre or _vacio(v.get("sobres_por_presentacion")):
            continue
        n = int(float(v["sobres_por_presentacion"]))
        if n < 1:
            raise ValueError(f"«{nombre}»: los sobres por presentación deben ser al menos 1.")
        if nombre in pres and pres[nombre] != n:
            raise ValueError(f"«{nombre}» ya existe con {pres[nombre]} sobres; el archivo dice {n}.")
        if nombre in nuevas and nuevas[nombre] != n:
            raise ValueError(f"«{nombre}» aparece con distinto número de sobres en el archivo.")
        if nombre not in pres:
            nuevas[nombre] = n
    return nuevas


def aplicar(datos: dict, filas: list[dict], aceptar_posibles_duplicados: set[int] = frozenset(),
            ventas: list[dict] | None = None) -> list[dict]:
    """Registra las filas «Nueva» (y las «Posible duplicado» aceptadas). Todo o nada.

    Si el archivo define presentaciones nuevas (``ventas`` originales), se agregan a la configuración.
    """
    salida = []
    if ventas:
        nuevas = presentaciones_nuevas(datos, ventas)
        if nuevas:
            importlib.import_module("motor").evento(datos, "Configuración", None, {"Presentaciones nuevas": nuevas})
            datos["config"].setdefault("presentaciones", copy.deepcopy(config_completa(datos)["presentaciones"]))
            datos["config"]["presentaciones"] += [{"Nombre": n, "Sobres": s} for n, s in nuevas.items()]
    for f in filas:
        if f["Estado"] == "Ya registrada":
            existente = op.por_clave(datos, f["clave"])
            salida.append({"Fila": f["Fila"], "Resultado": "Omitida (ya existía)", "ID": existente["ID"] if existente else None})
            continue
        if f["Estado"] == "Error":
            raise ValueError(f"La fila {f['Fila']} tiene errores; corrígela o quítala antes de importar.")
        if f["Estado"] == "Posible duplicado" and f["Fila"] not in aceptar_posibles_duplicados:
            salida.append({"Fila": f["Fila"], "Resultado": "No importada (posible duplicado sin confirmar)", "ID": None})
            continue
        e = {k: v for k, v in _reconstruir_entrada(f).items()}
        try:
            venta, asiento = op.registrar_venta(datos, e, f["cobro"])
        except op.Duplicado as d:
            salida.append({"Fila": f["Fila"], "Resultado": "Omitida (ya existía)", "ID": d.registro.get("ID")})
            continue
        salida.append({"Fila": f["Fila"], "Resultado": "Registrada", "ID": venta["ID"],
                       "Cobro": asiento["ID"] if asiento else None})
    return salida


def _reconstruir_entrada(f: dict) -> dict:
    v = f["venta"]
    return {
        "fecha": v["Fecha"], "canal": v["Canal"], "referencia": v["Referencia"], "cliente": v.get("Cliente"),
        "producto": v["Producto"], "sku": v.get("SKU"), "presentacion": v["Presentación"],
        "presentaciones": v["Presentaciones"], "precio_presentacion": v["Precio presentación"],
        "descuento": v["Descuento"], "devolucion": v["Devolución"], "sobres_devueltos": v["Sobres devueltos"],
        "envio": v["Ingresos Envío"],
        "comisiones": v["Comisiones"] if v["Comisiones confirmadas"] else None,
        "logistica": v["Costos Logísticos"] if v["Logística confirmada"] else None,
        "costo": v["Costo de ventas"], "costo_confirmado": v["Costo confirmado"],
        "estado": v["Estado"], "notas": v.get("Notas"), "origen": v["Origen"], "clave": f["clave"],
        # ID determinista: reintentos tras una caída producen el mismo ID.
        "id": "IMP-" + huella(f["clave"])[:12],
    }


def plantilla_csv() -> str:
    return ",".join(CAMPOS) + "\n"
