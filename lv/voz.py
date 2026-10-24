"""Lógica del conector de voz (Claude): consultar y registrar ventas en dos pasos.

Se separa del servidor MCP para probarla sin red. Todo cambio pasa por las
mismas reglas que la app (``construir_venta``, ``motor.validar_venta``,
``operaciones.registrar_venta``) y por ``Repositorio.transaccion``.

Registro en dos pasos
---------------------
1. ``preparar``: valida la venta contra los datos vigentes y la guarda como
   *pendiente* (no toca las ventas). Devuelve un resumen para leer en voz alta.
2. ``confirmar``: exige la frase literal del usuario con un «sí» claro y sin
   negaciones, al menos ``ESPERA_MINIMA`` segundos después de preparar y antes de
   que venza. La clave de idempotencia es el ID de la operación: si Claude
   reintenta la confirmación, no se duplica.
"""
from __future__ import annotations

import copy
import importlib
import re
from datetime import date, datetime, timedelta
from uuid import uuid4

from . import operaciones as op
from . import reportes
from .modelo import canales, config_completa, construir_venta, importes, presentaciones, tipo_canal
from .util import MESES, ahora_local, fin_de_mes, hoy_local, resolver_fecha

ESPERA_MINIMA = 4  # segundos
AFIRMATIVO = re.compile(r"\b(s[ií]|confirm[oa]|confirmada|dale|adelante|correcto|as[ií] es|ok(ay)?|de acuerdo|h[aá]zlo|"
                        r"reg[ií]strala|gu[aá]rdala|perfecto|exacto)\b", re.I)
NEGATIVO = re.compile(r"\b(no|cancela|cancelar|espera|alto|corrige|cambia|mejor no)\b", re.I)


def _pesos(v: float | None) -> str:
    if v is None:
        return "no disponible"
    return f"${v:,.0f}" if abs(v - round(v)) < 0.005 else f"${v:,.2f}"


def rango(periodo: str, hoy: date | None = None) -> tuple[str, str, str]:
    hoy = hoy or hoy_local()
    if periodo == "hoy":
        a = b = hoy
    elif periodo == "ayer":
        a = b = hoy - timedelta(days=1)
    elif periodo == "semana":
        a, b = hoy - timedelta(days=hoy.weekday()), hoy
    elif periodo == "mes_anterior":
        primero = hoy.replace(day=1) - timedelta(days=1)
        a, b = primero.replace(day=1), primero
    elif periodo == "anio":
        a, b = date(hoy.year, 1, 1), hoy
    elif periodo == "todo":
        a, b = date(2000, 1, 1), hoy
    else:  # mes
        a, b = hoy.replace(day=1), fin_de_mes(hoy.year, hoy.month)
    etiqueta = {"hoy": "hoy", "ayer": "ayer", "semana": "esta semana", "anio": f"en {hoy.year}", "todo": "en total",
                "mes_anterior": f"en {MESES[a.month - 1].lower()}"}.get(periodo, f"en {MESES[hoy.month - 1].lower()}")
    return a.isoformat(), b.isoformat(), etiqueta


def consultar(datos: dict, periodo: str = "mes", canal: str | None = None) -> dict:
    inicio, fin, etiqueta = rango(periodo)
    c = reportes.comerciales(datos, inicio, fin, canal)
    pend = reportes.pendientes(datos, inicio, fin)
    estimadas = sum(1 for r in reportes.ventas_periodo(datos, inicio, fin, canal) if r.get("Calidad") == "Estimada")
    texto = (f"{'En ' + canal + ', ' if canal else ''}{etiqueta} llevas {c['ventas']} venta{'s' if c['ventas'] != 1 else ''}, {c['sobres']:,} sobres y "
             f"{_pesos(c['venta_neta_producto'])} de venta neta de producto.")
    if c["margen_contribucion"] is not None:
        texto += f" El margen de contribución es {_pesos(c['margen_contribucion'])}; no es utilidad."
    elif c["ventas"]:
        texto += " El margen no está disponible porque faltan costos, comisiones o logística."
    if estimadas:
        texto += f" {estimadas} de esas ventas son estimadas."
    return {"periodo": {"inicio": inicio, "fin": fin}, "canal": canal or "Todos", "ventas": c["ventas"],
            "sobres": c["sobres"], "venta_neta_producto": round(c["venta_neta_producto"], 2),
            "margen_contribucion": None if c["margen_contribucion"] is None else round(c["margen_contribucion"], 2),
            "por_canal": {k: round(v, 2) for k, v in c["por_canal"].items()},
            "por_cobrar_registrado": round(c["por_cobrar"], 2), "preliminar": bool(pend),
            "resumen_para_voz": texto}


def ultimas(datos: dict, n: int = 5) -> dict:
    m = importlib.import_module("motor")
    ventas = [r for r in datos["operaciones"] if m.activo(r) and r.get("Fecha")]
    ventas.sort(key=lambda r: (r["Fecha"], r.get("Creado") or ""), reverse=True)
    filas = [{"fecha": r["Fecha"], "canal": r["Canal"], "sobres": r["Cantidad"], "cliente": r.get("Cliente"),
              "venta_neta": round(importes(r)["venta_neta_producto"], 2), "id": r["ID"]} for r in ventas[:max(1, min(n, 20))]]
    return {"ventas": filas}


def _entrada(datos: dict, a: dict) -> tuple[dict, dict | None, list[str]]:
    cfg = config_completa(datos)
    avisos = []
    canal = a["canal"]
    if canal not in canales(datos, solo_activos=False):
        raise ValueError(f"Canal desconocido: {canal}. Opciones: {', '.join(canales(datos))}.")
    pres = presentaciones(datos)
    nombre = a.get("presentacion") or "Sobre individual"
    if nombre not in pres:
        raise ValueError(f"Presentación no configurada: {nombre}. Opciones: {', '.join(pres)}.")
    fecha = resolver_fecha(a.get("fecha") or "hoy")
    if not fecha:
        raise ValueError("No entendí la fecha. Usa «hoy», «ayer» o AAAA-MM-DD.")
    if fecha > hoy_local().isoformat():
        raise ValueError("La fecha no puede ser futura.")
    unidades = int(a["unidades"])
    precio = a.get("precio_por_unidad")
    if precio is None:
        raise ValueError("Falta el precio por unidad. Pregúntale al usuario; no lo supongas.")
    directo = tipo_canal(datos, canal) == "Directo"
    com = a.get("comision")
    log = a.get("costo_envio")
    if com is None and directo:
        com = 0.0  # venta directa: sin intermediario que cobre comisión
    if log is None and directo:
        log = 0.0
        avisos.append("sin costo de entrega")
    costo_sobre = cfg.get("costo_sobre")
    sobres = unidades * pres[nombre]
    e = {"fecha": fecha, "canal": canal, "referencia": a.get("folio") or "", "cliente": a.get("cliente"),
         "presentacion": nombre, "presentaciones": unidades, "precio_presentacion": float(precio),
         "descuento": a.get("descuento") or 0.0, "envio": a.get("envio_cobrado") or 0.0,
         "comisiones": com, "logistica": log,
         "costo": round(costo_sobre * sobres, 2) if costo_sobre is not None else None,
         "costo_confirmado": costo_sobre is not None, "estado": "Entregado",
         "notas": ("Registrada por voz con Claude. " + (a.get("notas") or "")).strip(), "origen": "Voz (Claude)"}
    if costo_sobre is None:
        avisos.append("costo de producción pendiente")
    if com is None:
        avisos.append("comisión pendiente")
    cobro = None
    if a.get("cobrada"):
        cobro = {"fecha": resolver_fecha(a.get("fecha_cobro") or a.get("fecha") or "hoy"),
                 "importe": None, "medio": a.get("medio_cobro") or "No indicado", "referencia": a.get("referencia_cobro")}
    return e, cobro, avisos


def preparar(repo, pendientes, args: dict) -> dict:
    _, datos = repo.leer()
    e, cobro, avisos = _entrada(datos, args)
    venta = construir_venta(datos, e)
    i = importes(venta)
    if cobro:
        cobro["importe"] = round(i["ventas_netas_totales"], 2)
    if e["referencia"]:
        importlib.import_module("motor").validar_venta({**venta, "ID": "__vista_previa__"}, datos["operaciones"])
    pid = uuid4().hex[:10]
    pendientes.crear(pid, {"entrada": e, "cobro": cobro})
    f = date.fromisoformat(venta["Fecha"])
    cuando = "hoy" if venta["Fecha"] == hoy_local().isoformat() else f"el {f.day} de {MESES[f.month - 1].lower()}"
    unidad = "sobre" if venta["Presentación"] == "Sobre individual" else venta["Presentación"].lower()
    texto = (f"Venta en {venta['Canal']}{' a ' + venta['Cliente'] if venta.get('Cliente') else ''}: "
             f"{venta['Presentaciones']} {unidad}{'s' if venta['Presentaciones'] != 1 and unidad == 'sobre' else ''} "
             f"a {_pesos(venta['Precio presentación'])}, total {_pesos(i['venta_neta_producto'])}, {cuando}.")
    if venta["Presentación"] != "Sobre individual":
        texto += f" Son {venta['Cantidad']} sobres."
    if cobro:
        texto += f" Cobrada por {cobro['medio'].lower()}: {_pesos(cobro['importe'])}."
    if avisos:
        texto += " Nota: " + " y ".join(avisos) + "."
    texto += " ¿La confirmo?"
    return {"operacion_id": pid, "resumen_para_voz": texto, "vence_en_minutos": 5}


def confirmar(repo, pendientes, operacion_id: str, frase_usuario: str) -> dict:
    reg = pendientes.obtener(operacion_id)
    if not reg:
        raise ValueError("No encontré esa operación. Prepárala de nuevo.")
    if reg["estado"] == "Confirmada":
        return {"estado": "Ya registrada", "venta_id": reg["venta_id"],
                "resumen_para_voz": "Esa venta ya estaba registrada; no la dupliqué."}
    if reg["estado"] != "Pendiente":
        raise ValueError(f"La operación está {reg['estado'].lower()}. Prepárala de nuevo.")
    if pendientes.vencida(reg):
        pendientes.cerrar(operacion_id, "Vencida")
        raise ValueError("Pasaron más de 5 minutos; prepárala de nuevo.")
    if (ahora_local() - datetime.fromisoformat(reg["creado"])).total_seconds() < ESPERA_MINIMA:
        raise ValueError("Primero lee el resumen al usuario y espera su respuesta.")
    frase = (frase_usuario or "").strip()
    if not AFIRMATIVO.search(frase) or NEGATIVO.search(frase):
        raise ValueError("La respuesta del usuario no es una confirmación clara. No se guardó nada.")
    entrada = copy.deepcopy(reg["datos"]["entrada"])
    entrada["clave"] = f"voz-{operacion_id}"
    try:
        venta, asiento = repo.transaccion(lambda d: op.registrar_venta(d, entrada, reg["datos"]["cobro"]))
    except op.Duplicado as dup:
        venta, asiento = dup.registro, None
    _, verif = repo.leer()
    if not op.por_id(verif, venta["ID"]):
        raise RuntimeError("No pude verificar la venta en la base. Revisa el tablero.")
    pendientes.cerrar(operacion_id, "Confirmada", venta["ID"])
    return {"estado": "Registrada", "venta_id": venta["ID"], "folio": venta["Referencia"],
            "cobro_registrado": bool(asiento),
            "resumen_para_voz": f"Listo, registrada con folio {venta['Referencia']}."}


def cancelar(pendientes, operacion_id: str) -> dict:
    reg = pendientes.obtener(operacion_id)
    if reg and reg["estado"] == "Pendiente":
        pendientes.cerrar(operacion_id, "Cancelada")
    return {"estado": "Cancelada", "resumen_para_voz": "Cancelada, no guardé nada."}
