import json
import subprocess
import sys
import unittest

from base import RAIZ, CasoBase

from lv import importacion, operaciones as op
from lv.util import hoy_local

EJEMPLO = {
    "formato": "legado-verde-ventas", "version": 1,
    "ventas": [{
        "clave": "claude-prueba-0001", "fecha": "hoy", "canal": "Cafeterías",
        "presentacion": "Sobre individual", "presentaciones": 10, "precio_presentacion": 60,
        "comisiones": None, "logistica": None, "costo": None,
        "cobro": {"fecha": "hoy", "importe": 600, "medio": "Transferencia", "referencia": None},
    }],
}


class PruebasImportacion(CasoBase):
    def test_vista_previa_no_escribe_y_marca_pendientes(self):
        antes = self.datos()
        filas = importacion.previsualizar(antes, importacion.leer(json.dumps(EJEMPLO)))
        self.assertEqual(self.datos(), antes)
        f = filas[0]
        self.assertEqual(f["Estado"], "Nueva")
        self.assertEqual(f["venta"]["Fecha"], hoy_local().isoformat())
        self.assertTrue(any("Costo" in p for p in f["Pendientes"]))
        self.assertIn("Comisiones", f["Pendientes"])
        self.assertIn("Referencia bancaria del cobro", f["Pendientes"])

    def test_importacion_idempotente(self):
        ventas = importacion.leer(json.dumps(EJEMPLO))
        r1 = self.repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas)))
        self.assertEqual(r1[0]["Resultado"], "Registrada")
        n_ops, n_as = len(self.datos()["operaciones"]), len(self.datos()["asientos"])
        r2 = self.repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas)))
        self.assertEqual(r2[0]["Resultado"], "Omitida (ya existía)")
        self.assertEqual(r2[0]["ID"], r1[0]["ID"])
        self.assertEqual((len(self.datos()["operaciones"]), len(self.datos()["asientos"])), (n_ops, n_as))
        v = op.por_id(self.datos(), r1[0]["ID"])
        self.assertFalse(v["Costo confirmado"])
        self.assertFalse(v["Comisiones confirmadas"])
        self.assertEqual(v["Estado cobro"], "Cobrado")

    def test_reimportar_con_folio_y_presentacion_nueva(self):
        doc = {"formato": "legado-verde-ventas", "version": 1, "ventas": [
            {"clave": "ml-2000015425212699", "fecha": "2026-10-08", "canal": "Mercado Libre", "referencia": "2000015425212699",
             "presentacion": "Paquete de 10", "sobres_por_presentacion": 10, "presentaciones": 1, "precio_presentacion": 895,
             "comisiones": 161.1, "logistica": 95.5, "costo": 450, "costo_confirmado": True}]}
        ventas = importacion.leer(json.dumps(doc))
        r = self.repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas), set(), ventas))
        self.assertEqual(r[0]["Resultado"], "Registrada")
        d = self.datos()
        self.assertIn({"Nombre": "Paquete de 10", "Sobres": 10}, d["config"]["presentaciones"])
        self.assertEqual(op.por_id(d, r[0]["ID"])["Cantidad"], 10)
        filas = importacion.previsualizar(d, ventas)
        self.assertEqual(filas[0]["Estado"], "Ya registrada")
        r2 = self.repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas), set(), ventas))
        self.assertEqual(r2[0]["Resultado"], "Omitida (ya existía)")
        doc["ventas"][0]["sobres_por_presentacion"] = 12  # contradice la existente
        self.assertEqual(importacion.previsualizar(self.datos(), importacion.leer(json.dumps(doc)))[0]["Estado"], "Error")

    def test_errores_bloquean_todo(self):
        malo = json.loads(json.dumps(EJEMPLO))
        malo["ventas"].append({"clave": "x2", "fecha": "ayer", "canal": "Canal inventado",
                               "presentaciones": 1, "precio_presentacion": 60})
        ventas = importacion.leer(json.dumps(malo))
        n = len(self.datos()["operaciones"])
        with self.assertRaises(ValueError):
            self.repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas)))
        self.assertEqual(len(self.datos()["operaciones"]), n)

    def test_cobro_sin_importe_es_error(self):
        malo = json.loads(json.dumps(EJEMPLO))
        malo["ventas"][0]["cobro"] = {"fecha": "hoy", "importe": None}
        f = importacion.previsualizar(self.datos(), importacion.leer(json.dumps(malo)))[0]
        self.assertEqual(f["Estado"], "Error")

    def test_csv_y_posible_duplicado(self):
        csv = importacion.plantilla_csv() + "c1,2026-10-20,Cafeterías,,,,,Sobre individual,,10,60,,,,,0,0,,,,,,,,\n"
        ventas = importacion.leer(csv, "v.csv")
        self.repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas)))
        # la misma venta con otra clave: se detecta como posible duplicado y no entra sin confirmación
        ventas2 = importacion.leer(csv.replace("c1,", "c2,"), "v.csv")
        filas = importacion.previsualizar(self.datos(), ventas2)
        self.assertEqual(filas[0]["Estado"], "Posible duplicado")
        r = self.repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas2)))
        self.assertIsNone(r[0]["ID"])
        r = self.repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas2), {1}))
        self.assertEqual(r[0]["Resultado"], "Registrada")

    def test_cli_vista_previa_y_confirmacion(self):
        archivo = RAIZ / "ejemplos" / "venta_ejemplo_claude.json"
        env = {"PATH": "/usr/bin:/bin"}
        r = subprocess.run([sys.executable, str(RAIZ / "registrar_venta.py"), str(archivo), "--db", self.db],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no se escribió nada", r.stdout)
        for _ in range(2):  # repetir la confirmación no duplica
            r = subprocess.run([sys.executable, str(RAIZ / "registrar_venta.py"), str(archivo), "--db", self.db, "--confirmar"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Omitida (ya existía)", r.stdout)
        self.assertNotIn("NO VERIFICADA", r.stdout)


if __name__ == "__main__":
    unittest.main()
