"""Base de datos de integraciones (SQLite, separada de la contable)."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from ..util import ZONA, ahora_iso, ahora_local

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS cuentas (
    plataforma TEXT NOT NULL, cuenta TEXT NOT NULL, nombre TEXT,
    estado TEXT NOT NULL DEFAULT 'Preparada', cursor TEXT,
    ultimo_ok TEXT, ultimo_error TEXT, ultimo_error_en TEXT,
    comprobada INTEGER NOT NULL DEFAULT 0, actualizado TEXT,
    PRIMARY KEY (plataforma, cuenta));
CREATE TABLE IF NOT EXISTS tokens (
    plataforma TEXT NOT NULL, cuenta TEXT NOT NULL,
    refresh_token TEXT, access_token TEXT, expira TEXT, actualizado TEXT,
    PRIMARY KEY (plataforma, cuenta));
CREATE TABLE IF NOT EXISTS pedidos (
    clave TEXT PRIMARY KEY, plataforma TEXT NOT NULL, cuenta TEXT NOT NULL,
    pedido TEXT NOT NULL, partida TEXT NOT NULL,
    estado_plataforma TEXT, fecha_pedido TEXT, actualizado_plataforma TEXT, sku TEXT,
    normalizado TEXT NOT NULL, crudo TEXT NOT NULL, huella TEXT NOT NULL,
    estado_local TEXT NOT NULL, venta_id TEXT, mensaje TEXT,
    recibido TEXT NOT NULL, procesado TEXT);
CREATE INDEX IF NOT EXISTS pedidos_estado ON pedidos(estado_local);
CREATE TABLE IF NOT EXISTS historial_pedidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, clave TEXT NOT NULL, huella TEXT NOT NULL,
    crudo TEXT NOT NULL, recibido TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cola (
    id INTEGER PRIMARY KEY AUTOINCREMENT, plataforma TEXT NOT NULL, cuenta TEXT,
    topico TEXT, recurso TEXT NOT NULL, recibido TEXT NOT NULL,
    procesado TEXT, intentos INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS corridas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, plataforma TEXT, cuenta TEXT, tipo TEXT,
    inicio TEXT, fin TEXT, estado TEXT, desde TEXT, hasta TEXT,
    paginas INTEGER DEFAULT 0, pedidos INTEGER DEFAULT 0, nuevos INTEGER DEFAULT 0,
    cambios INTEGER DEFAULT 0, incorporados INTEGER DEFAULT 0, mensaje TEXT);
CREATE TABLE IF NOT EXISTS bloqueos (nombre TEXT PRIMARY KEY, dueno TEXT, expira TEXT);
CREATE TABLE IF NOT EXISTS decisiones (
    clave TEXT PRIMARY KEY, decision TEXT NOT NULL, venta_id TEXT, fecha TEXT);
"""

ESTADOS_LOCALES = {
    "PENDIENTE": "Pedido pendiente (no reconocido)",
    "POR_INCORPORAR": "Por incorporar",
    "INCORPORADO": "Incorporado",
    "CANCELADO": "Cancelado en plataforma",
    "REV_DUP": "Revisión: posible duplicado",
    "REV_SKU": "Revisión: SKU sin mapear",
    "REV_MONEDA": "Revisión: moneda distinta de MXN",
    "REV_CONFLICTO": "Revisión: edición manual en conflicto",
    "REV_OTRO": "Revisión: requiere decisión",
    "IGNORADO": "Ignorado por decisión del usuario",
}


def ruta_integraciones() -> str:
    return os.environ.get("LEGADO_VERDE_INTEG_DB",
                          str(Path(__file__).resolve().parents[2] / "datos" / "integraciones.sqlite3"))


class Estado:
    def __init__(self, ruta: str | None = None):
        self.ruta = ruta or ruta_integraciones()
        Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        nueva = not Path(self.ruta).exists()
        with self.conexion() as c:
            c.executescript(ESQUEMA_SQL)
        if nueva:
            try:  # contiene tokens: solo lectura/escritura para el dueño del proceso
                os.chmod(self.ruta, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

    @contextmanager
    def conexion(self):
        c = sqlite3.connect(self.ruta, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def tx(self):
        with self.conexion() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    # ---------------------------------------------------------------- cuentas
    def cuenta(self, plataforma: str, cuenta: str) -> dict:
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO cuentas (plataforma, cuenta, actualizado) VALUES (?,?,?)",
                      (plataforma, cuenta, ahora_iso()))
            return dict(c.execute("SELECT * FROM cuentas WHERE plataforma=? AND cuenta=?",
                                  (plataforma, cuenta)).fetchone())

    def cuentas(self) -> list[dict]:
        with self.conexion() as c:
            return [dict(r) for r in c.execute("SELECT * FROM cuentas ORDER BY plataforma, cuenta")]

    def actualizar_cuenta(self, plataforma: str, cuenta: str, **campos):
        campos["actualizado"] = ahora_iso()
        sets = ", ".join(f"{k}=?" for k in campos)
        with self.tx() as c:
            c.execute(f"UPDATE cuentas SET {sets} WHERE plataforma=? AND cuenta=?",
                      (*campos.values(), plataforma, cuenta))

    # ---------------------------------------------------------------- tokens
    def token(self, plataforma: str, cuenta: str) -> dict | None:
        with self.conexion() as c:
            r = c.execute("SELECT * FROM tokens WHERE plataforma=? AND cuenta=?", (plataforma, cuenta)).fetchone()
            return dict(r) if r else None

    def guardar_token(self, plataforma, cuenta, access_token, expira_en_seg, refresh_token=None):
        expira = (ahora_local() + timedelta(seconds=max(int(expira_en_seg) - 120, 60))).isoformat()
        with self.tx() as c:
            previo = c.execute("SELECT refresh_token FROM tokens WHERE plataforma=? AND cuenta=?",
                               (plataforma, cuenta)).fetchone()
            rt = refresh_token or (previo["refresh_token"] if previo else None)
            c.execute("INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?,?)",
                      (plataforma, cuenta, rt, access_token, expira, ahora_iso()))

    @staticmethod
    def vigente(tok: dict | None) -> bool:
        return bool(tok and tok.get("access_token") and tok.get("expira")
                    and datetime.fromisoformat(tok["expira"]) > ahora_local())

    # ---------------------------------------------------------------- bloqueos
    def adquirir(self, nombre: str, dueno: str, minutos: int = 20) -> bool:
        ahora = ahora_local()
        with self.tx() as c:
            r = c.execute("SELECT dueno, expira FROM bloqueos WHERE nombre=?", (nombre,)).fetchone()
            if r and r["dueno"] != dueno and datetime.fromisoformat(r["expira"]) > ahora:
                return False
            c.execute("INSERT OR REPLACE INTO bloqueos VALUES (?,?,?)",
                      (nombre, dueno, (ahora + timedelta(minutes=minutos)).isoformat()))
            return True

    def liberar(self, nombre: str, dueno: str):
        with self.tx() as c:
            c.execute("DELETE FROM bloqueos WHERE nombre=? AND dueno=?", (nombre, dueno))

    # ---------------------------------------------------------------- pedidos
    def guardar_partida(self, p: dict, crudo: dict, estado_local: str, mensaje: str | None = None) -> str:
        """Inserta o actualiza una partida. Devuelve 'nuevo', 'cambio' o 'igual'."""
        from ..util import huella
        h = huella(p)
        with self.tx() as c:
            r = c.execute("SELECT huella, estado_local FROM pedidos WHERE clave=?", (p["clave"],)).fetchone()
            if r and r["huella"] == h:
                return "igual"
            crudo_txt = json.dumps(crudo, ensure_ascii=False, default=str)
            c.execute("INSERT INTO historial_pedidos (clave, huella, crudo, recibido) VALUES (?,?,?,?)",
                      (p["clave"], h, crudo_txt, ahora_iso()))
            if r:
                # Lo ya decidido por el usuario (Ignorado) se respeta salvo que cambie el pedido.
                c.execute("""UPDATE pedidos SET estado_plataforma=?, fecha_pedido=?, actualizado_plataforma=?, sku=?,
                             normalizado=?, crudo=?, huella=?, estado_local=?, mensaje=?, recibido=?, procesado=NULL
                             WHERE clave=?""",
                          (p["estado_plataforma"], p["fecha_pedido"], p["actualizado"], p.get("sku"),
                           json.dumps(p, ensure_ascii=False), crudo_txt, h, estado_local, mensaje, ahora_iso(), p["clave"]))
                return "cambio"
            c.execute("""INSERT INTO pedidos (clave, plataforma, cuenta, pedido, partida, estado_plataforma, fecha_pedido,
                         actualizado_plataforma, sku, normalizado, crudo, huella, estado_local, mensaje, recibido)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (p["clave"], p["plataforma"], p["cuenta"], p["pedido"], p["partida"], p["estado_plataforma"],
                       p["fecha_pedido"], p["actualizado"], p.get("sku"), json.dumps(p, ensure_ascii=False),
                       crudo_txt, h, estado_local, mensaje, ahora_iso()))
            return "nuevo"

    def pedidos(self, estados: list[str] | None = None, limite: int = 1000) -> list[dict]:
        with self.conexion() as c:
            if estados:
                q = f"SELECT * FROM pedidos WHERE estado_local IN ({','.join('?' * len(estados))}) ORDER BY fecha_pedido LIMIT ?"
                filas = c.execute(q, (*estados, limite)).fetchall()
            else:
                filas = c.execute("SELECT * FROM pedidos ORDER BY fecha_pedido DESC LIMIT ?", (limite,)).fetchall()
        out = []
        for f in filas:
            d = dict(f)
            d["normalizado"] = json.loads(d["normalizado"])
            out.append(d)
        return out

    def marcar_pedido(self, clave: str, estado_local: str, venta_id: str | None = None, mensaje: str | None = None):
        with self.tx() as c:
            c.execute("UPDATE pedidos SET estado_local=?, venta_id=COALESCE(?, venta_id), mensaje=?, procesado=? WHERE clave=?",
                      (estado_local, venta_id, mensaje, ahora_iso(), clave))

    def decidir(self, clave: str, decision: str, venta_id: str | None = None):
        """Decisión del usuario sobre un pedido en revisión: 'incorporar', 'vincular' o 'ignorar'."""
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO decisiones VALUES (?,?,?,?)", (clave, decision, venta_id, ahora_iso()))
            c.execute("UPDATE pedidos SET estado_local=?, procesado=NULL WHERE clave=?",
                      (ESTADOS_LOCALES["IGNORADO"] if decision == "ignorar" else ESTADOS_LOCALES["POR_INCORPORAR"], clave))

    def decisiones(self) -> dict[str, dict]:
        with self.conexion() as c:
            return {r["clave"]: dict(r) for r in c.execute("SELECT * FROM decisiones")}

    # ---------------------------------------------------------------- cola
    def encolar(self, plataforma: str, cuenta: str | None, topico: str, recurso: str):
        with self.tx() as c:
            c.execute("INSERT INTO cola (plataforma, cuenta, topico, recurso, recibido) VALUES (?,?,?,?,?)",
                      (plataforma, cuenta, topico, recurso, ahora_iso()))

    def cola_pendiente(self, limite=200) -> list[dict]:
        with self.conexion() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM cola WHERE procesado IS NULL AND intentos < 10 ORDER BY id LIMIT ?", (limite,))]

    def cerrar_cola(self, ids: list[int], error: str | None = None):
        with self.tx() as c:
            for i in ids:
                if error:
                    c.execute("UPDATE cola SET intentos=intentos+1, error=? WHERE id=?", (error[:500], i))
                else:
                    c.execute("UPDATE cola SET procesado=? WHERE id=?", (ahora_iso(), i))

    # ---------------------------------------------------------------- corridas
    def abrir_corrida(self, plataforma, cuenta, tipo, desde, hasta) -> int:
        with self.tx() as c:
            cur = c.execute("INSERT INTO corridas (plataforma, cuenta, tipo, inicio, estado, desde, hasta) VALUES (?,?,?,?,?,?,?)",
                            (plataforma, cuenta, tipo, ahora_iso(), "En curso", desde, hasta))
            return cur.lastrowid

    def cerrar_corrida(self, cid: int, estado: str, **contadores):
        contadores["fin"] = ahora_iso()
        contadores["estado"] = estado
        sets = ", ".join(f"{k}=?" for k in contadores)
        with self.tx() as c:
            c.execute(f"UPDATE corridas SET {sets} WHERE id=?", (*contadores.values(), cid))

    def corridas(self, limite=50) -> list[dict]:
        with self.conexion() as c:
            return [dict(r) for r in c.execute("SELECT * FROM corridas ORDER BY id DESC LIMIT ?", (limite,))]

    def resumen(self) -> dict:
        with self.conexion() as c:
            return {r["estado_local"]: r["n"] for r in c.execute(
                "SELECT estado_local, COUNT(*) n FROM pedidos GROUP BY estado_local")}


def iso_utc(dt: datetime) -> str:
    from datetime import timezone
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["Estado", "ESTADOS_LOCALES", "iso_utc", "ZONA"]
