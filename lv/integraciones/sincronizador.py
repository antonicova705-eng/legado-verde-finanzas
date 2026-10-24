"""Orquestación de sincronizaciones: inicial, incremental, cola y recuperación.

Garantías
---------
* Las partidas se guardan primero en la base de integraciones (con su JSON
  original e historial de versiones) y solo después se incorporan a ventas.
* El cursor de la cuenta avanza únicamente cuando la corrida termina bien. Si se
  interrumpe, la siguiente corrida relee la misma ventana: como la carga es
  idempotente (por clave), no se pierde ni se duplica nada.
* Un bloqueo por cuenta impide que el worker y el botón «Sincronizar ahora»
  trabajen la misma cuenta a la vez.
"""
from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime

from ..util import ahora_iso, ahora_local
from .conciliacion import conciliar
from .estado import ESTADOS_LOCALES as E
from .estado import Estado
from .http import ErrorAPI, ocultar

log = logging.getLogger("legado_verde.integraciones")

REPROCESABLES = [E["POR_INCORPORAR"], E["REV_SKU"], E["REV_MONEDA"]]


class Sincronizador:
    def __init__(self, repo, estado: Estado, clientes: list):
        self.repo = repo
        self.estado = estado
        self.clientes = {c.plataforma: c for c in clientes}
        self.yo = f"proc-{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------ carga
    def _registrar(self, cliente, o: dict, contadores: dict):
        if cliente.plataforma == "Amazon":
            fin = None
            st = (o.get("fulfillment") or {}).get("fulfillmentStatus")
            if st in ("SHIPPED", "PARTIALLY_SHIPPED", "CANCELLED"):
                try:
                    fin = cliente.eventos_financieros(o["orderId"])
                except ErrorAPI as e:  # sin finanzas, las comisiones quedan pendientes
                    log.warning("Finanzas no disponibles para %s: %s", o.get("orderId"), e)
            partidas = cliente.normalizar(o, fin)
        else:
            partidas = cliente.normalizar(o)
        for p in partidas:
            inicial = E["PENDIENTE"] if p["clase"] == "pendiente" else E["POR_INCORPORAR"]
            r = self.estado.guardar_partida(p, o, inicial)
            contadores["pedidos"] += 1
            if r == "nuevo":
                contadores["nuevos"] += 1
            elif r == "cambio":
                contadores["cambios"] += 1

    def sincronizar(self, plataforma: str, desde_inicial: datetime | None = None,
                    hasta: datetime | None = None, tipo: str = "incremental") -> dict:
        cliente = self.clientes[plataforma]
        cuenta = cliente.cuenta
        nombre = f"sync:{plataforma}:{cuenta}"
        if not self.estado.adquirir(nombre, self.yo, minutos=60):
            return {"estado": "Omitida", "mensaje": "Otra sincronización de esta cuenta está en curso."}
        c = self.estado.cuenta(plataforma, cuenta)
        if tipo == "inicial":
            if not desde_inicial:
                raise ValueError("La sincronización inicial necesita fecha de inicio.")
            desde, hasta = desde_inicial, (hasta or ahora_local())
        else:
            if not c.get("cursor") and not desde_inicial:
                self.estado.liberar(nombre, self.yo)
                return {"estado": "Omitida", "mensaje": "Primero ejecuta la sincronización inicial con un rango de fechas."}
            desde, hasta = cliente.ventana_incremental(c.get("cursor"), desde_inicial)
        cid = self.estado.abrir_corrida(plataforma, cuenta, tipo, desde.isoformat(), hasta.isoformat())
        cont = {"paginas": 0, "pedidos": 0, "nuevos": 0, "cambios": 0, "incorporados": 0}
        try:
            for clase, o in cliente.pedidos_actualizados(desde, hasta):
                if clase == "pagina":
                    cont["paginas"] += 1
                    self.estado.adquirir(nombre, self.yo, minutos=60)  # renueva el bloqueo
                else:
                    self._registrar(cliente, o, cont)
            cont["incorporados"] = self.incorporar()
            nuevo_cursor = hasta.isoformat()
            if c.get("cursor") and c["cursor"] > nuevo_cursor:
                nuevo_cursor = c["cursor"]  # una carga histórica no retrocede el cursor
            self.estado.actualizar_cuenta(plataforma, cuenta, cursor=nuevo_cursor, ultimo_ok=ahora_iso(),
                                          estado="Sincronización comprobada", comprobada=1,
                                          ultimo_error=None)
            self.estado.cerrar_corrida(cid, "Correcta", **cont)
            return {"estado": "Correcta", **cont}
        except Exception as e:  # se registra y se informa; el cursor no avanza
            msg = ocultar(str(e))
            self.estado.actualizar_cuenta(plataforma, cuenta, estado="Error", ultimo_error=msg,
                                          ultimo_error_en=ahora_iso())
            self.estado.cerrar_corrida(cid, "Error", mensaje=msg, **cont)
            log.error("Sincronización %s falló: %s", plataforma, msg)
            return {"estado": "Error", "mensaje": msg, **cont}
        finally:
            self.estado.liberar(nombre, self.yo)

    # ------------------------------------------------------------------ cola (notificaciones)
    def procesar_cola(self) -> dict:
        hechos = errores = 0
        for item in self.estado.cola_pendiente():
            cliente = self.clientes.get(item["plataforma"])
            if not cliente:
                continue
            try:
                pedido_id = item["recurso"].rstrip("/").split("/")[-1]
                o = cliente.pedido(pedido_id)
                self._registrar(cliente, o, {"pedidos": 0, "nuevos": 0, "cambios": 0})
                self.estado.cerrar_cola([item["id"]])
                hechos += 1
            except Exception as e:
                self.estado.cerrar_cola([item["id"]], error=ocultar(str(e)))
                errores += 1
        incorporados = self.incorporar() if hechos else 0
        return {"procesadas": hechos, "errores": errores, "incorporados": incorporados}

    # ------------------------------------------------------------------ incorporación
    def incorporar(self, lote: int = 50) -> int:
        decisiones = self.estado.decisiones()
        pendientes = self.estado.pedidos(REPROCESABLES, limite=10000)
        con_decision = [p for p in self.estado.pedidos([E["REV_DUP"], E["REV_CONFLICTO"], E["REV_OTRO"]], 10000)
                        if p["clave"] in decisiones]
        filas = pendientes + con_decision
        total = 0
        for i in range(0, len(filas), lote):
            grupo = filas[i:i + lote]

            def aplicar(d, grupo=grupo):
                salida = []
                for f in grupo:
                    copia = copy.deepcopy(d)
                    try:
                        res = conciliar(copia, f["normalizado"], decisiones.get(f["clave"]))
                        d.clear()
                        d.update(copia)
                    except (ValueError, KeyError, TypeError) as e:
                        res = (E["REV_OTRO"], None, f"No se pudo incorporar: {e}")
                    salida.append((f["clave"], *res))
                return salida

            for clave, est, vid, msg in self.repo.transaccion(aplicar):
                self.estado.marcar_pedido(clave, est, vid, msg)
                if est == E["INCORPORADO"]:
                    total += 1
        return total

    def estado_general(self) -> dict:
        return {"cuentas": self.estado.cuentas(), "resumen": self.estado.resumen(),
                "corridas": self.estado.corridas(10), "cola": len(self.estado.cola_pendiente())}


def construir(repo, estado: Estado | None = None, http=None) -> Sincronizador:
    """Crea el sincronizador con las plataformas que tengan credenciales en el entorno."""
    from . import amazon, mercadolibre
    estado = estado or Estado()
    clientes = []
    if mercadolibre.configurada():
        clientes.append(mercadolibre.MercadoLibre(estado, http))
    if amazon.configurada():
        clientes.append(amazon.Amazon(estado, http))
    for cl in clientes:
        estado.cuenta(cl.plataforma, cl.cuenta)
    return Sincronizador(repo, estado, clientes)


__all__ = ["Sincronizador", "construir", "datetime"]
