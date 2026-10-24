"""Receptor de notificaciones de Mercado Libre (tópico orders_v2).

Responde HTTP 200 de inmediato (Mercado Libre exige respuesta en < 500 ms) y
solo encola el recurso; el worker consulta el pedido con su propio token. Por
eso una notificación falsa no puede insertar datos: a lo sumo provoca una
consulta a la API oficial.

    python webhook_ml.py --puerto 8080

Debe publicarse detrás de HTTPS (proxy inverso) en la URL configurada como
«URL de retorno de notificaciones» de tu aplicación en Mercado Libre.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lv.integraciones.estado import Estado  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("legado_verde.webhook")
TOPICOS = {"orders_v2"}
RUTA = "/notificaciones/mercadolibre"


def aceptar(cuerpo: dict, estado: Estado, app_id: str | None, seller_id: str | None) -> bool:
    if cuerpo.get("topic") not in TOPICOS:
        return False
    if app_id and str(cuerpo.get("application_id")) != str(app_id):
        return False
    if seller_id and str(cuerpo.get("user_id")) != str(seller_id):
        return False
    recurso = str(cuerpo.get("resource") or "")
    if not recurso.startswith("/orders/") or not recurso.split("/")[-1].isdigit():
        return False
    estado.encolar("Mercado Libre", str(cuerpo.get("user_id")), cuerpo["topic"], recurso)
    return True


def servidor(puerto: int, estado: Estado | None = None) -> ThreadingHTTPServer:
    estado = estado or Estado()
    app_id = os.environ.get("ML_CLIENT_ID")
    seller = os.environ.get("ML_SELLER_ID")

    class Manejador(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0] != RUTA:
                self.send_response(404)
                self.end_headers()
                return
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 10_000)
                cuerpo = json.loads(self.rfile.read(n) or b"{}")
                ok = aceptar(cuerpo, estado, app_id, seller)
            except Exception as e:  # nunca devolver 500: Mercado Libre desactivaría el tópico
                log.warning("Notificación inválida: %s", type(e).__name__)
                ok = False
            self.send_response(200)
            self.end_headers()
            if ok:
                log.info("Encolada notificación %s", cuerpo.get("resource"))

        def do_GET(self):  # noqa: N802  verificación de salud
            self.send_response(200 if self.path == "/salud" else 404)
            self.end_headers()

        def log_message(self, *a):  # evita registrar cuerpos o encabezados
            pass

    return ThreadingHTTPServer(("0.0.0.0", puerto), Manejador)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--puerto", type=int, default=int(os.environ.get("PORT", 8080)))
    a = p.parse_args()
    log.info("Escuchando en :%s%s", a.puerto, RUTA)
    servidor(a.puerto).serve_forever()
