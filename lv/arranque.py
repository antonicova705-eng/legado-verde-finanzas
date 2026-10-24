"""Apertura de la base: siembra inicial (solo si está vacía) y migración de esquema."""
from __future__ import annotations

import copy
import importlib
import os
from pathlib import Path

from .datos_iniciales import CATALOGO_INICIAL, CONFIG_INICIAL, OPERACIONES_INICIALES
from .modelo import migrar_v2
from .persistencia import Repositorio


def ruta_base() -> str:
    return os.environ.get("LEGADO_VERDE_DB",
                          str(Path(__file__).resolve().parent.parent / "datos" / "legado_verde.sqlite3"))


def abrir(db_path: str | None = None) -> Repositorio:
    m = importlib.import_module("motor")
    db_path = db_path or ruta_base()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    repo = Repositorio(m.Almacen(db_path), m.Conflicto,
                       carpeta_respaldos=Path(db_path).parent / "respaldos")
    revision, guardado = repo.leer()
    if guardado is None:
        datos = {
            "config": copy.deepcopy(CONFIG_INICIAL),
            "catalogo": copy.deepcopy(CATALOGO_INICIAL),
            "operaciones": m.migrar(copy.deepcopy(OPERACIONES_INICIALES)),
            "asientos": [], "historial": [], "cobertura": [],
            "apertura_confirmada": False, "fecha_apertura": None,
        }
        migrar_v2(datos)
        try:
            repo.almacen.guardar(datos, revision)
        except m.Conflicto:
            pass  # otra sesión la sembró al mismo tiempo; se usa la suya
    else:
        repo.transaccion(lambda d: migrar_v2(d))
    return repo
