"""Almacén persistente en PostgreSQL con la misma interfaz que ``motor.Almacen``.

Si existe la variable ``DATABASE_URL`` (p. ej. una base gratuita de Neon), la
app y el conector de voz guardan aquí en lugar del archivo SQLite local, de
modo que los datos sobreviven a reinicios de Streamlit y ambos ven lo mismo.

Mismo modelo que el motor: un documento JSON con número de revisión. ``guardar``
solo escribe si la revisión no cambió (bloqueo de fila ``FOR UPDATE``); si otra
sesión guardó antes, lanza ``motor.Conflicto`` y ``Repositorio.transaccion``
reintenta sobre los datos nuevos.

``Pendientes`` guarda las ventas preparadas por voz que esperan confirmación.

El dialecto ``sqlite`` existe solo para pruebas automáticas.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from .util import ahora_local

TABLA_ESTADO = """CREATE TABLE IF NOT EXISTS lv_estado (
    id INTEGER PRIMARY KEY CHECK (id = 1), revision INTEGER NOT NULL, datos TEXT NOT NULL,
    actualizado TEXT)"""
TABLA_PENDIENTES = """CREATE TABLE IF NOT EXISTS lv_pendientes (
    id TEXT PRIMARY KEY, datos TEXT NOT NULL, creado TEXT NOT NULL, vence TEXT NOT NULL,
    estado TEXT NOT NULL, venta_id TEXT)"""


def url_base() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    return url or None


def descripcion_segura(url: str | None) -> str:
    """Describe la base sin revelar usuario ni contraseña."""
    if not url:
        return "SQLite local"
    from urllib.parse import urlparse
    u = urlparse(url)
    return f"PostgreSQL en {u.hostname or 'servidor externo'}"


class _Conexion:
    def __init__(self, url: str, dialecto: str):
        self.url, self.dialecto = url, dialecto
        self.ph = "%s" if dialecto == "postgres" else "?"

    @contextmanager
    def tx(self):
        if self.dialecto == "postgres":
            import psycopg  # requirements: psycopg[binary]
            with psycopg.connect(self.url, connect_timeout=15) as c:  # commit al salir, rollback con error
                yield c
        else:
            c = sqlite3.connect(self.url, timeout=30, isolation_level=None)
            try:
                c.execute("BEGIN IMMEDIATE")
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            finally:
                c.close()

    def q(self, sql: str) -> str:
        return sql.replace("?", self.ph)


class AlmacenSQL:
    def __init__(self, url: str, conflicto_exc, dialecto: str = "postgres"):
        self.db = _Conexion(url, dialecto)
        self.Conflicto = conflicto_exc
        with self.db.tx() as c:
            c.execute(TABLA_ESTADO)
            c.execute(TABLA_PENDIENTES)

    def leer(self):
        with self.db.tx() as c:
            fila = c.execute("SELECT revision, datos FROM lv_estado WHERE id = 1").fetchone()
        return (fila[0], json.loads(fila[1])) if fila else (0, None)

    def guardar(self, datos, revision):
        texto = json.dumps(datos, ensure_ascii=False, allow_nan=False)
        bloqueo = " FOR UPDATE" if self.db.dialecto == "postgres" else ""
        with self.db.tx() as c:
            fila = c.execute("SELECT revision FROM lv_estado WHERE id = 1" + bloqueo).fetchone()
            actual = fila[0] if fila else 0
            if actual != revision:
                raise self.Conflicto("Otro usuario modificó los datos. Recarga y vuelve a realizar el cambio.")
            if fila:
                c.execute(self.db.q("UPDATE lv_estado SET revision = ?, datos = ?, actualizado = ? WHERE id = 1"),
                          (actual + 1, texto, ahora_local().isoformat()))
            else:
                cur = c.execute(self.db.q("INSERT INTO lv_estado (id, revision, datos, actualizado) VALUES (1, ?, ?, ?) "
                                          "ON CONFLICT (id) DO NOTHING"), (1, texto, ahora_local().isoformat()))
                if cur.rowcount != 1:  # otra sesión creó la base al mismo tiempo
                    raise self.Conflicto("La base se inicializó en otra sesión. Recarga.")
        return actual + 1


class Pendientes:
    """Ventas preparadas por voz que esperan confirmación (vencen en pocos minutos)."""

    def __init__(self, url: str, dialecto: str = "postgres"):
        self.db = _Conexion(url, dialecto)
        with self.db.tx() as c:
            c.execute(TABLA_PENDIENTES)

    def crear(self, pid: str, datos: dict, minutos: int = 5) -> dict:
        ahora = ahora_local()
        reg = {"id": pid, "datos": datos, "creado": ahora.isoformat(),
               "vence": (ahora + timedelta(minutes=minutos)).isoformat(), "estado": "Pendiente"}
        with self.db.tx() as c:
            c.execute(self.db.q("INSERT INTO lv_pendientes (id, datos, creado, vence, estado) VALUES (?, ?, ?, ?, ?)"),
                      (pid, json.dumps(datos, ensure_ascii=False), reg["creado"], reg["vence"], reg["estado"]))
        return reg

    def obtener(self, pid: str) -> dict | None:
        with self.db.tx() as c:
            f = c.execute(self.db.q("SELECT id, datos, creado, vence, estado, venta_id FROM lv_pendientes WHERE id = ?"),
                          (pid,)).fetchone()
        if not f:
            return None
        return {"id": f[0], "datos": json.loads(f[1]), "creado": f[2], "vence": f[3], "estado": f[4], "venta_id": f[5]}

    def cerrar(self, pid: str, estado: str, venta_id: str | None = None):
        with self.db.tx() as c:
            c.execute(self.db.q("UPDATE lv_pendientes SET estado = ?, venta_id = ? WHERE id = ?"), (estado, venta_id, pid))

    @staticmethod
    def vencida(reg: dict) -> bool:
        return datetime.fromisoformat(reg["vence"]) < ahora_local()
