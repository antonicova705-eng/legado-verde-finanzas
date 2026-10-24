"""Conector de voz y almacén externo (dialecto SQLite como sustituto de PostgreSQL)."""
import os
import threading
import unittest
from datetime import timedelta
from unittest import mock

from base import CasoBase

import motor
from lv import operaciones as op
from lv import voz
from lv.almacen_sql import AlmacenSQL, Pendientes, descripcion_segura
from lv.persistencia import Repositorio
from lv.util import ahora_local, hoy_local


class PruebasAlmacenSQL(CasoBase):
    def test_revision_y_conflicto(self):
        a = AlmacenSQL(os.path.join(self.tmp.name, "pg.sqlite3"), motor.Conflicto, dialecto="sqlite")
        self.assertEqual(a.leer(), (0, None))
        r1 = a.guardar({"x": 1}, 0)
        self.assertEqual(a.leer(), (1, {"x": 1}))
        with self.assertRaises(motor.Conflicto):
            a.guardar({"x": 2}, 0)  # revisión vieja
        self.assertEqual(a.guardar({"x": 3}, r1), 2)

    def test_concurrencia_sin_perdidas(self):
        a = AlmacenSQL(os.path.join(self.tmp.name, "pg.sqlite3"), motor.Conflicto, dialecto="sqlite")
        a.guardar({"n": []}, 0)
        repo = Repositorio(a, motor.Conflicto)
        hilos = [threading.Thread(target=lambda i=i: repo.transaccion(lambda d: d["n"].append(i), intentos=50)) for i in range(10)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual(sorted(a.leer()[1]["n"]), list(range(10)))

    def test_descripcion_no_revela_contrasena(self):
        d = descripcion_segura("postgresql://usuario:SECRETO@ep-x.neon.tech/db?sslmode=require")
        self.assertNotIn("SECRETO", d)
        self.assertNotIn("usuario", d)


class PruebasVoz(CasoBase):
    def setUp(self):
        super().setUp()
        self.pend = Pendientes(os.path.join(self.tmp.name, "pend.sqlite3"), "sqlite")

    def _envejecer(self, pid, segundos=10):
        reg = self.pend.obtener(pid)
        creado = (ahora_local() - timedelta(seconds=segundos)).isoformat()
        with self.pend.db.tx() as c:
            c.execute("UPDATE lv_pendientes SET creado = ? WHERE id = ?", (creado, pid))
        return reg

    def test_flujo_completo_cafeteria_cobrada(self):
        r = voz.preparar(self.repo, self.pend, {"canal": "Cafeterías", "unidades": 10, "precio_por_unidad": 70,
                                                 "cliente": "Café Prueba", "cobrada": True, "medio_cobro": "Transferencia"})
        self.assertIn("10 sobres a $70, total $700, hoy", r["resumen_para_voz"])
        self.assertIn("¿La confirmo?", r["resumen_para_voz"])
        n = len(self.datos()["operaciones"])
        self.assertEqual(len(self.datos()["operaciones"]), n)  # preparar no escribe
        with self.assertRaises(ValueError):  # demasiado pronto
            voz.confirmar(self.repo, self.pend, r["operacion_id"], "sí")
        self._envejecer(r["operacion_id"])
        with self.assertRaises(ValueError):
            voz.confirmar(self.repo, self.pend, r["operacion_id"], "no, espera")
        res = voz.confirmar(self.repo, self.pend, r["operacion_id"], "Sí, regístrala")
        self.assertEqual(res["estado"], "Registrada")
        v = op.por_id(self.datos(), res["venta_id"])
        self.assertEqual((v["Fecha"], v["Cantidad"], v["Cliente"], v["Estado cobro"]), (hoy_local().isoformat(), 10, "Café Prueba", "Cobrado"))
        self.assertEqual(v["Origen"], "Voz (Claude)")
        self.assertFalse(v["Costo confirmado"])  # costo por sobre aún no configurado
        # reintento de Claude: no duplica
        res2 = voz.confirmar(self.repo, self.pend, r["operacion_id"], "sí")
        self.assertEqual(res2["venta_id"], res["venta_id"])
        self.assertEqual(len(self.datos()["operaciones"]), n + 1)
        self.assertEqual(len(self.datos()["asientos"]), 1)

    def test_costo_configurado_y_paquete(self):
        def conf(d):
            d["config"]["costo_sobre"] = 45.0
            d["config"]["presentaciones"].append({"Nombre": "Paquete de 10", "Sobres": 10})
        self.repo.transaccion(conf)
        r = voz.preparar(self.repo, self.pend, {"canal": "Venta directa", "unidades": 2, "precio_por_unidad": 600,
                                                 "presentacion": "Paquete de 10", "fecha": "ayer"})
        self.assertIn("Son 20 sobres", r["resumen_para_voz"])
        self._envejecer(r["operacion_id"])
        res = voz.confirmar(self.repo, self.pend, r["operacion_id"], "ok, dale")
        v = op.por_id(self.datos(), res["venta_id"])
        self.assertEqual((v["Costo de ventas"], v["Costo confirmado"]), (900.0, True))
        self.assertEqual(v["Fecha"], (hoy_local() - timedelta(days=1)).isoformat())

    def test_validaciones(self):
        with self.assertRaises(ValueError):
            voz.preparar(self.repo, self.pend, {"canal": "Cafeterías", "unidades": 3, "precio_por_unidad": None})
        with self.assertRaises(ValueError):
            voz.preparar(self.repo, self.pend, {"canal": "Cafeterías", "unidades": 3, "precio_por_unidad": 70,
                                                 "fecha": "2099-01-01"})
        r = voz.preparar(self.repo, self.pend, {"canal": "Mercado Libre", "unidades": 1, "precio_por_unidad": 149})
        self.assertIn("comisión pendiente", r["resumen_para_voz"])
        self.pend.cerrar(r["operacion_id"], "Pendiente")
        with mock.patch.object(Pendientes, "vencida", return_value=True):
            self._envejecer(r["operacion_id"])
            with self.assertRaises(ValueError):
                voz.confirmar(self.repo, self.pend, r["operacion_id"], "sí")

    def test_consulta(self):
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(fecha=hoy_local().isoformat())))
        c = voz.consultar(self.datos(), "mes")
        self.assertEqual(c["ventas"], 1)
        self.assertIn("1 venta, 10 sobres", c["resumen_para_voz"])


if __name__ == "__main__":
    unittest.main()
