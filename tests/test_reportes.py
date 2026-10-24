import importlib
import unittest

from base import CasoBase

from lv import operaciones as op
from lv import reportes


class PruebasReportes(CasoBase):
    def test_indicadores_con_caso_controlado(self):
        # Caso: 10 sobres a $60 con costo 250 y comisión 30; 5 sobres a $60 con costo pendiente.
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(canal="Mercado Libre", costo=250, costo_confirmado=True, comisiones=30)))
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(presentaciones=5, devolucion=60, sobres_devueltos=1)))
        c = reportes.comerciales(self.datos(), "2026-10-01", "2026-10-31")
        self.assertEqual(c["ventas"], 2)
        self.assertEqual(c["venta_neta_producto"], 600 + 300 - 60)
        self.assertEqual(c["sobres"], 15)
        self.assertEqual(c["sobres_netos"], 14)
        self.assertIsNone(c["margen_contribucion"])  # una venta sin costo: no se muestra un total engañoso
        self.assertEqual(c["margen_pendientes"], 1)
        ml = reportes.comerciales(self.datos(), "2026-10-01", "2026-10-31", "Mercado Libre")
        self.assertEqual(ml["margen_contribucion"], 600 - 250 - 30)
        # La ecuación contable se mantiene tras venta + cobro (motor real)
        v = [r for r in self.datos()["operaciones"] if r.get("Canal") == "Mercado Libre" and r.get("Fecha")][0]
        self.repo.transaccion(lambda d: op.registrar_cobro(d, v["ID"], "2026-10-25", 570, referencia="DEP-1"))
        rep = importlib.import_module("motor").reporte(self.datos(), "2026-10-01", "2026-10-31")
        self.assertAlmostEqual(rep["descuadre"], 0, places=6)
        self.assertEqual(rep["efectivo_final"], 570)

    def test_pendientes_y_serie_sin_crecimiento_engañoso(self):
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(fecha="2026-09-10")))
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(fecha="2026-10-10", presentaciones=20)))
        temas = {p["Tema"] for p in reportes.pendientes(self.datos(), "2026-10-01", "2026-10-31")}
        self.assertIn("Ventas sin fecha exacta", temas)  # heredados
        self.assertIn("Costo de ventas sin confirmar", temas)
        serie = reportes.serie_mensual(self.datos(), 2026)
        self.assertIsNone(serie[9]["Variación %"])  # sin cobertura confirmada no se compara
        self.assertIsNone(serie[0]["Ventas netas MXN"])  # mes sin datos: desconocido, no cero

    def test_ebitda_oculto_si_falta_comision(self):
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(costo=200, costo_confirmado=True, comisiones=None)))
        self.assertEqual(len(reportes.ventas_incompletas(self.datos(), "2026-10-01", "2026-10-31")), 1)
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(fecha="2026-11-02", costo=200, costo_confirmado=True)))
        self.assertEqual(reportes.ventas_incompletas(self.datos(), "2026-11-01", "2026-11-30"), [])

    def test_simulador(self):
        r = reportes.simular(1000, 25.0, 10000, [
            {"Canal": "A", "% volumen": 50, "Precio por sobre": 60, "Comisión %": 10, "Logística por sobre": 5},
            {"Canal": "B", "% volumen": 50, "Precio por sobre": 60, "Comisión %": 0, "Logística por sobre": 0}])
        # A: 500*60=30000; cv 12500; com 3000; log 2500 → 12000. B: 30000-12500=17500.
        self.assertAlmostEqual(r["contribucion"], 29500)
        self.assertAlmostEqual(r["resultado"], 19500)
        self.assertAlmostEqual(r["pe_sobres"], 10000 / 29.5)


if __name__ == "__main__":
    unittest.main()
