"""Proceso de sincronización con Mercado Libre y Amazon (independiente de Streamlit).

Ejemplos:
    python sync_worker.py --estado
    python sync_worker.py --autorizar-ml CODIGO          # una vez, tras autorizar en el navegador
    python sync_worker.py --inicial --desde 2026-07-01   # historial
    python sync_worker.py --una-vez                      # incremental + cola de notificaciones
    python sync_worker.py --continuo --minutos 15        # servicio permanente

Credenciales: variables de entorno (ver .env.example). Nunca en el código.
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lv.arranque import abrir  # noqa: E402
from lv.integraciones import mercadolibre  # noqa: E402
from lv.integraciones.estado import Estado  # noqa: E402
from lv.integraciones.sincronizador import construir  # noqa: E402
from lv.util import ZONA  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("legado_verde.worker")
_detener = False


def _parar(*_):
    global _detener
    _detener = True


def ciclo(sinc) -> None:
    for plat in sinc.clientes:
        r = sinc.sincronizar(plat)
        log.info("%s: %s", plat, {k: v for k, v in r.items() if k != "mensaje"} | ({"mensaje": r["mensaje"]} if r.get("mensaje") else {}))
    r = sinc.procesar_cola()
    if r["procesadas"] or r["errores"]:
        log.info("Cola de notificaciones: %s", r)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--estado", action="store_true")
    g.add_argument("--una-vez", action="store_true")
    g.add_argument("--continuo", action="store_true")
    g.add_argument("--inicial", action="store_true")
    g.add_argument("--autorizar-ml", metavar="CODIGO")
    p.add_argument("--desde", help="AAAA-MM-DD (inicial)")
    p.add_argument("--hasta", help="AAAA-MM-DD (inicial, opcional)")
    p.add_argument("--plataforma", choices=["Mercado Libre", "Amazon"])
    p.add_argument("--minutos", type=int, default=15)
    a = p.parse_args(argv)

    estado = Estado()
    if a.autorizar_ml:
        if not mercadolibre.configurada():
            print("Faltan ML_CLIENT_ID, ML_CLIENT_SECRET o ML_SELLER_ID.")
            return 2
        mercadolibre.MercadoLibre(estado).intercambiar_codigo(a.autorizar_ml)
        print("Cuenta de Mercado Libre autorizada. El token quedó en la base de integraciones (no en archivos de código).")
        return 0
    repo = abrir()
    sinc = construir(repo, estado)
    if not sinc.clientes:
        print("No hay plataformas configuradas. Revisa las variables de entorno (.env.example).")
        if not a.estado:
            return 2
    if a.estado:
        print(json.dumps(sinc.estado_general(), ensure_ascii=False, indent=2, default=str))
        return 0
    if a.inicial:
        if not a.desde:
            print("Indica --desde AAAA-MM-DD")
            return 2
        desde = datetime.fromisoformat(a.desde).replace(tzinfo=ZONA)
        hasta = datetime.fromisoformat(a.hasta).replace(tzinfo=ZONA) if a.hasta else None
        for plat in ([a.plataforma] if a.plataforma else list(sinc.clientes)):
            print(plat, sinc.sincronizar(plat, desde, hasta, tipo="inicial"))
        return 0
    if a.una_vez:
        ciclo(sinc)
        return 0
    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)
    log.info("Worker iniciado: cada %s min; cola de notificaciones cada 30 s.", a.minutos)
    siguiente = 0.0
    while not _detener:
        if time.monotonic() >= siguiente:
            try:
                ciclo(sinc)
            except Exception as e:  # el servicio no se detiene por un error puntual
                log.error("Ciclo fallido: %s", e)
            siguiente = time.monotonic() + a.minutos * 60
        else:
            try:
                sinc.procesar_cola()
            except Exception as e:
                log.error("Cola fallida: %s", e)
        for _ in range(30):
            if _detener:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
