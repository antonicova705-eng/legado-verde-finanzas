"""Configuración común de pruebas: usa el motor.py REAL del proyecto y bases temporales."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


class CasoBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "prueba.sqlite3")
        self.integ = os.path.join(self.tmp.name, "integraciones.sqlite3")
        from lv.arranque import abrir
        self.repo = abrir(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def datos(self):
        return self.repo.leer()[1]

    def entrada(self, **kw):
        e = {"fecha": "2026-10-20", "canal": "Cafeterías", "referencia": "", "presentacion": "Sobre individual",
             "presentaciones": 10, "precio_presentacion": 60, "costo": None, "costo_confirmado": False,
             "comisiones": 0, "logistica": 0}
        e.update(kw)
        return e
