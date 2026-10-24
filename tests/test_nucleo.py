import json
import threading
import unittest

from base import CasoBase

from lv import operaciones as op
from lv.modelo import importes, migrar_v2


class PruebasNucleo(CasoBase):
    def test_siembra_conserva_datos_heredados(self):
        d = self.datos()
        self.assertEqual([r["ID"] for r in d["operaciones"]],
                         ["ML-001", "ML-002", "ML-003", "ML-004", "AMZ-001", "CAF-001"])
        caf = op.por_id(d, "CAF-001")
        self.assertEqual(caf["Remanente"], 15000.0)
        self.assertEqual(caf["Origen"], "Heredado sin verificar")
        self.assertIsNone(caf["Fecha"])
        self.assertIn("Shopify", [c["Nombre"] for c in d["config"]["canales"]])
        self.assertFalse(migrar_v2(d), "la migración debe ser idempotente")

    def test_registro_y_edicion(self):
        v, a = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave="k1")))
        self.assertIsNone(a)
        d = self.datos()
        g = op.por_id(d, v["ID"])
        self.assertEqual(g["Cantidad"], 10)
        self.assertEqual(g["Ventas Producto"], 600.0)
        self.assertIsNone(g["Costo de ventas"])  # costo pendiente
        h = op.huella_registro(g)
        self.repo.transaccion(lambda d: op.editar_venta(d, v["ID"], self.entrada(presentaciones=12, costo=250, costo_confirmado=True), h))
        g2 = op.por_id(self.datos(), v["ID"])
        self.assertEqual(g2["Cantidad"], 12)
        self.assertEqual(g2["Costo de ventas"], 250)
        self.assertEqual(importes(g2)["margen_contribucion"], 720 - 250)
        # editar con huella vieja falla (otra sesión cambió el registro)
        with self.assertRaises(ValueError):
            self.repo.transaccion(lambda d: op.editar_venta(d, v["ID"], self.entrada(), h))

    def test_paquetes_y_sobres_equivalentes(self):
        def conf(d):
            d["config"]["presentaciones"].append({"Nombre": "Paquete 3", "Sobres": 3})
        self.repo.transaccion(conf)
        v, _ = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(presentacion="Paquete 3", presentaciones=4, precio_presentacion=165)))
        self.assertEqual(v["Presentaciones"], 4)
        self.assertEqual(v["Cantidad"], 12)
        self.assertEqual(v["Ventas Producto"], 660.0)
        self.assertAlmostEqual(v["Precio"] * v["Cantidad"], 660.0, places=4)

    def test_doble_clic_no_duplica(self):
        e = self.entrada(clave="form-123")
        self.repo.transaccion(lambda d: op.registrar_venta(d, e, {"fecha": "2026-10-20", "importe": 600, "medio": "Transferencia"}))
        n_ops = len(self.datos()["operaciones"])
        n_as = len(self.datos()["asientos"])
        with self.assertRaises(op.Duplicado):
            self.repo.transaccion(lambda d: op.registrar_venta(d, e, {"fecha": "2026-10-20", "importe": 600}))
        self.assertEqual(len(self.datos()["operaciones"]), n_ops)
        self.assertEqual(len(self.datos()["asientos"]), n_as)

    def test_venta_y_cobro_atomicos(self):
        n = len(self.datos()["operaciones"])
        with self.assertRaises(ValueError):  # cobro mayor al total: no se guarda NADA
            self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave="x"), {"fecha": "2026-10-20", "importe": 9999}))
        self.assertEqual(len(self.datos()["operaciones"]), n)
        self.assertEqual(self.datos()["asientos"], [])
        v, a = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave="y"), {"fecha": "2026-10-20", "importe": 600, "medio": "Transferencia"}))
        self.assertTrue(a["Referencia pendiente"])
        self.assertIsNone(a["Referencia bancaria"])
        self.assertEqual(op.por_id(self.datos(), v["ID"])["Estado cobro"], "Cobrado")

    def test_cobro_parcial_y_reembolso(self):
        v, _ = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada()))
        self.repo.transaccion(lambda d: op.registrar_cobro(d, v["ID"], "2026-10-21", 200, referencia="SPEI-1"))
        d = self.datos()
        self.assertEqual(op.cobrado_neto(d, v["ID"]), 200)
        self.assertEqual(op.por_id(d, v["ID"])["Estado cobro"], "Parcial")
        with self.assertRaises(ValueError):  # referencia repetida
            self.repo.transaccion(lambda d: op.registrar_cobro(d, v["ID"], "2026-10-21", 10, referencia="spei-1"))
        with self.assertRaises(ValueError):  # supera saldo
            self.repo.transaccion(lambda d: op.registrar_cobro(d, v["ID"], "2026-10-22", 401))
        with self.assertRaises(ValueError):  # anterior a la venta
            self.repo.transaccion(lambda d: op.registrar_cobro(d, v["ID"], "2026-10-01", 10))
        self.repo.transaccion(lambda d: op.registrar_cobro(d, v["ID"], "2026-10-22", 50, tipo="Reembolso de venta", referencia="R-1"))
        self.assertEqual(op.cobrado_neto(self.datos(), v["ID"]), 150)

    def test_devolucion_dinero_y_unidades(self):
        v, _ = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(devolucion=120, sobres_devueltos=2, costo=200, costo_confirmado=True)))
        i = importes(v)
        self.assertEqual(i["venta_neta_producto"], 480)
        self.assertEqual(i["sobres_netos"], 8)
        with self.assertRaises(ValueError):
            self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(sobres_devueltos=11)))

    def test_anulacion(self):
        v, _ = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada()))
        h = op.huella_registro(v)
        with self.assertRaises(ValueError):
            self.repo.transaccion(lambda d: op.anular_venta(d, v["ID"], h, ""))
        self.repo.transaccion(lambda d: op.anular_venta(d, v["ID"], h, "Capturada dos veces"))
        g = op.por_id(self.datos(), v["ID"])
        self.assertTrue(g["Anulada"])
        with self.assertRaises(ValueError):
            self.repo.transaccion(lambda d: op.editar_venta(d, v["ID"], self.entrada(), None))

    def test_folio_interno_y_folio_unico_con_motor_real(self):
        v, _ = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada()))
        self.assertTrue(v["Referencia"].startswith("INT-20261020-"))
        self.assertTrue(v["Folio interno"])
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(referencia="F-9")))
        h = op.huella_registro([r for r in self.datos()["operaciones"] if r.get("Referencia") == "F-9"][0])
        fid = [r for r in self.datos()["operaciones"] if r.get("Referencia") == "F-9"][0]["ID"]
        self.repo.transaccion(lambda d: op.anular_venta(d, fid, h, "Error de captura"))
        with self.assertRaises(ValueError):  # el motor no permite reutilizar un folio anulado en el mismo canal
            self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(referencia="f-9")))

    def test_reinicio_conserva_datos(self):
        v, _ = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave="persist")))
        from lv.arranque import abrir
        repo2 = abrir(self.db)  # simula reinicio del proceso
        self.assertIsNotNone(op.por_clave(repo2.leer()[1], "persist"))

    def test_sesiones_concurrentes_no_se_pisan(self):
        errores = []

        def alta(i):
            try:
                self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave=f"c{i}", referencia=f"F{i}")), intentos=20)
            except Exception as e:  # noqa
                errores.append(e)
        hilos = [threading.Thread(target=alta, args=(i,)) for i in range(8)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual(errores, [])
        claves = [r.get("Clave") for r in self.datos()["operaciones"] if r.get("Clave")]
        self.assertEqual(sorted(claves), sorted(f"c{i}" for i in range(8)))

    def test_respaldo_y_restauracion(self):
        from lv import respaldos
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave="r1")))
        original = self.datos()
        restaurado = json.loads(respaldos.serializar(original))
        errores, resumen = respaldos.validar(restaurado, original)
        self.assertEqual(errores, [])
        self.assertEqual(resumen["Ventas actuales que desaparecerían"], 0)
        roto = json.loads(respaldos.serializar(original))
        roto["operaciones"].append(dict(roto["operaciones"][0]))
        self.assertTrue(respaldos.validar(roto, original)[0])
        # restaurar = reemplazo atómico con respaldo previo
        ruta = self.repo.respaldo_local(original, "antes-de-restaurar")
        self.assertTrue(ruta.exists())
        self.repo.transaccion(lambda d: (d.clear(), d.update(restaurado)))
        self.assertEqual(self.datos()["operaciones"], original["operaciones"])


if __name__ == "__main__":
    unittest.main()
