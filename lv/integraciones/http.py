"""Cliente HTTP mínimo con reintentos, límite de ritmo y registros sin secretos."""
from __future__ import annotations

import json
import logging
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("legado_verde.integraciones")

_SECRETO = re.compile(r"(access_token|refresh_token|client_secret|code|Authorization|x-amz-access-token)=?[^&\s,]*", re.I)


def ocultar(texto: str) -> str:
    """Elimina tokens y secretos antes de escribir en registros o en la base."""
    return _SECRETO.sub(r"\1=***", str(texto))[:800]


class ErrorAPI(Exception):
    def __init__(self, estado: int | None, mensaje: str, reintentable: bool = False):
        super().__init__(ocultar(f"HTTP {estado}: {mensaje}" if estado else mensaje))
        self.estado = estado
        self.reintentable = reintentable


class Transporte:
    """Realiza solicitudes HTTP. Las pruebas lo sustituyen por un transporte falso."""

    def solicitar(self, metodo: str, url: str, encabezados: dict, cuerpo: bytes | None, tiempo: float):
        req = urllib.request.Request(url, data=cuerpo, method=metodo, headers=encabezados)
        try:
            with urllib.request.urlopen(req, timeout=tiempo) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read()


class LimiteRitmo:
    """Cubeta de fichas: ``ritmo`` solicitudes por segundo con ráfaga ``rafaga``."""

    def __init__(self, ritmo: float, rafaga: int, reloj=time.monotonic, dormir=time.sleep):
        self.ritmo, self.rafaga = ritmo, rafaga
        self.fichas = float(rafaga)
        self.reloj, self.dormir = reloj, dormir
        self.ultimo = reloj()

    def esperar(self):
        ahora = self.reloj()
        self.fichas = min(self.rafaga, self.fichas + (ahora - self.ultimo) * self.ritmo)
        self.ultimo = ahora
        if self.fichas < 1:
            espera = (1 - self.fichas) / self.ritmo
            self.dormir(espera)
            self.ultimo = self.reloj()
            self.fichas = 1.0
        self.fichas -= 1


class ClienteHTTP:
    def __init__(self, transporte: Transporte | None = None, intentos: int = 5, tiempo: float = 30,
                 dormir=time.sleep):
        self.t = transporte or Transporte()
        self.intentos = intentos
        self.tiempo = tiempo
        self.dormir = dormir

    def json(self, metodo: str, url: str, params: dict | None = None, encabezados: dict | None = None,
             formulario: dict | None = None, limite: LimiteRitmo | None = None):
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=False)
        enc = {"Accept": "application/json", "User-Agent": "LegadoVerde-Finanzas/2.0"}
        enc.update(encabezados or {})
        cuerpo = None
        if formulario is not None:
            cuerpo = urllib.parse.urlencode(formulario).encode()
            enc["Content-Type"] = "application/x-www-form-urlencoded"
        for intento in range(1, self.intentos + 1):
            if limite:
                limite.esperar()
            try:
                estado, cab, datos = self.t.solicitar(metodo, url, enc, cuerpo, self.tiempo)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                if intento == self.intentos:
                    raise ErrorAPI(None, f"Sin conexión: {e}", reintentable=True)
                self._pausa(intento, None)
                continue
            if 200 <= estado < 300:
                return json.loads(datos or b"null")
            texto = (datos or b"")[:400].decode("utf-8", "replace")
            reintentable = estado == 429 or estado >= 500
            if not reintentable or intento == self.intentos:
                raise ErrorAPI(estado, texto, reintentable)
            log.warning("Reintento %s/%s tras HTTP %s en %s", intento, self.intentos, estado,
                        ocultar(url.split("?")[0]))
            self._pausa(intento, cab.get("Retry-After") or cab.get("retry-after"))
        raise ErrorAPI(None, "Reintentos agotados", True)  # pragma: no cover

    def _pausa(self, intento: int, retry_after):
        try:
            espera = float(retry_after) if retry_after else min(60, 2 ** intento) + random.random()
        except ValueError:
            espera = min(60, 2 ** intento)
        self.dormir(espera)
