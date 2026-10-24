"""Acceso transaccional al almacén de ``motor``.

``Repositorio.transaccion(fn)`` lee la versión vigente, aplica ``fn`` sobre una
copia y la guarda con control de versión. Si otra sesión guardó antes
(``Conflicto``), vuelve a leer y reaplica ``fn`` sobre los datos nuevos. Como
``fn`` valida contra el estado vigente (claves de idempotencia, huellas de
registros editados), un reintento nunca sobrescribe en silencio el trabajo de
otra sesión ni duplica registros.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from .util import ahora_local


class Repositorio:
    def __init__(self, almacen, conflicto_exc, carpeta_respaldos: str | Path | None = None):
        self.almacen = almacen
        self.Conflicto = conflicto_exc
        self.carpeta_respaldos = Path(carpeta_respaldos) if carpeta_respaldos else None

    def leer(self):
        return self.almacen.leer()

    def transaccion(self, fn, intentos: int = 3):
        ultimo = None
        for _ in range(intentos):
            revision, datos = self.almacen.leer()
            if datos is None:
                raise RuntimeError("La base no está inicializada.")
            copia = copy.deepcopy(datos)
            resultado = fn(copia)  # una excepción aquí descarta la copia: no se guarda nada
            if copia == datos:
                return resultado
            try:
                self.almacen.guardar(copia, revision)
                return resultado
            except self.Conflicto as e:
                ultimo = e
                continue
        raise RuntimeError("Hubo cambios simultáneos en otra sesión y no se pudo guardar. "
                           "Recarga e inténtalo de nuevo.") from ultimo

    def respaldo_local(self, datos: dict, motivo: str) -> Path | None:
        """Copia JSON previa a operaciones delicadas (p. ej. restaurar)."""
        if not self.carpeta_respaldos:
            return None
        self.carpeta_respaldos.mkdir(parents=True, exist_ok=True)
        nombre = f"{ahora_local():%Y%m%d-%H%M%S}-{motivo}.json"
        ruta = self.carpeta_respaldos / nombre
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(tmp, ruta)
        return ruta
