"""Bus de eventos en proceso para Server-Sent Events.

Publica desde código síncrono (endpoints en threadpool, tareas de fondo) hacia
clientes SSE async. Para varias instancias, sustituir por Postgres LISTEN/NOTIFY o Redis.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any


class Bus:
    def __init__(self) -> None:
        self._colas: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def vincular(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def suscribir(self) -> asyncio.Queue:
        cola: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._colas.add(cola)
        return cola

    def cancelar(self, cola: asyncio.Queue) -> None:
        self._colas.discard(cola)

    def publicar(self, tipo: str, datos: dict[str, Any]) -> None:
        mensaje = {"event": tipo, "data": json.dumps(datos, ensure_ascii=False, default=str)}
        if not self._loop or self._loop.is_closed():
            return
        for cola in list(self._colas):
            self._loop.call_soon_threadsafe(self._encolar, cola, mensaje)

    @staticmethod
    def _encolar(cola: asyncio.Queue, mensaje: dict) -> None:
        if cola.full():  # cliente lento: se descarta el más antiguo
            cola.get_nowait()
        cola.put_nowait(mensaje)


bus = Bus()
