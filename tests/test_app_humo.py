"""Prueba de humo de app.py con Streamlit y Plotly FALSOS (sin navegador).

Ejecuta cada sección y algunos flujos completos para detectar errores de
ejecución. No valida el diseño visual ni el comportamiento real de Streamlit.
"""
import io
import json
import os
import runpy
import sys
import unittest

from base import RAIZ, CasoBase

sys.path.insert(0, str(RAIZ / "tests" / "stubs"))
import streamlit as st  # noqa: E402  (falso)

from lv import operaciones as op  # noqa: E402


class Archivo(io.BytesIO):
    def __init__(self, contenido: bytes, nombre: str):
        super().__init__(contenido)
        self.name = nombre


class PruebaHumoApp(CasoBase):
    def setUp(self):
        super().setUp()
        os.environ["LEGADO_VERDE_DB"] = self.db
        os.environ["LEGADO_VERDE_INTEG_DB"] = self.integ
        for k in [k for k in os.environ if k.startswith(("ML_", "AMZ_"))]:
            del os.environ[k]
        st.session_state.clear()
        st.CLICS.clear()
        st.VALORES.clear()
        st.SALIDA.clear()
        st.ARCHIVOS.clear()

    def correr(self, max_reejecuciones=4):
        for _ in range(max_reejecuciones):
            try:
                runpy.run_path(str(RAIZ / "app.py"), run_name="__main__")
                return
            except st.Reejecutar:
                st.CLICS.clear()  # un clic solo cuenta en una ejecución
                continue
            except st.Detener:
                return
        self.fail("Demasiadas re-ejecuciones")

    def errores(self):
        # El aviso de disco temporal es correcto aquí: las pruebas usan /tmp.
        return [m for t, m in st.SALIDA if t == "error" and "disco temporal" not in m]

    def test_todas_las_secciones(self):
        for pagina in ["Inicio", "Ventas", "Costos y gastos", "Finanzas", "Simulador", "Configuración y respaldos"]:
            st.session_state.clear()
            st.SALIDA.clear()
            st.session_state["pagina"] = pagina
            self.correr()
            self.assertEqual(self.errores(), [], pagina)
        for vista in ["Registro de ventas", "Registrar o editar", "Cobros", "Importar", "Historial"]:
            st.session_state.clear()
            st.session_state.update(pagina="Ventas", ventas_vista=vista)
            self.correr()
            self.assertEqual(self.errores(), [], vista)

    def test_boton_registrar_venta_y_doble_clic(self):
        st.session_state["pagina"] = "Inicio"
        st.CLICS.add("Registrar venta")
        self.correr()
        self.assertEqual(st.session_state["pagina"], "Ventas")
        self.assertEqual(st.session_state["ventas_vista"], "Registrar o editar")
        n = len(self.datos()["operaciones"])
        st.VALORES.update({"Cantidad de presentaciones": 10, "Precio por presentación (MXN)": 60.0,
                           "Canal": "Cafeterías", "¿Ya cobraste esta venta?": "Sí, registrar el cobro ahora"})
        st.CLICS.add("Guardar venta")
        self.correr()
        self.assertEqual(self.errores(), [])
        d = self.datos()
        self.assertEqual(len(d["operaciones"]), n + 1)
        self.assertEqual(len(d["asientos"]), 1)
        vid = st.session_state["venta_guardada"]
        self.assertEqual(op.por_id(d, vid)["Estado cobro"], "Cobrado")
        # Segundo clic: el formulario ya no existe (se muestra la confirmación), no se duplica
        st.CLICS.add("Guardar venta")
        self.correr()
        self.assertEqual(len(self.datos()["operaciones"]), n + 1)
        # Aun si se reenvía con la misma clave, la capa de negocio lo rechaza
        clave = st.session_state["clave_form"]
        with self.assertRaises(op.Duplicado):
            self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave=clave)))

    def test_editar_venta_desde_formulario(self):
        v, _ = self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada()))
        st.session_state.update(pagina="Ventas", ventas_vista="Registrar o editar", venta_sel=v["ID"])
        st.VALORES.update({"Costo de ventas confirmado": True, "Costo de ventas total (neto)": 230.0})
        st.CLICS.add("Guardar cambios")
        self.correr()
        self.assertEqual(self.errores(), [])
        g = op.por_id(self.datos(), v["ID"])
        self.assertTrue(g["Costo confirmado"])
        self.assertEqual(g["Costo de ventas"], 230.0)

    def test_importar_desde_app(self):
        contenido = (RAIZ / "ejemplos" / "venta_ejemplo_claude.json").read_bytes()
        st.session_state.update(pagina="Ventas", ventas_vista="Importar")
        st.ARCHIVOS["Archivo de ventas"] = Archivo(contenido, "v.json")
        st.VALORES["Revisé la vista previa y quiero registrar 1 venta(s)"] = True
        st.CLICS.add("Importar ventas")
        self.correr()
        self.assertEqual(self.errores(), [])
        self.assertIsNotNone(op.por_clave(self.datos(), "claude-20261023-ejemplo-0001"))
        st.ARCHIVOS["Archivo de ventas"] = Archivo(contenido, "v.json")
        st.CLICS.add("Importar ventas")
        self.correr()
        claves = [r.get("Clave") for r in self.datos()["operaciones"]]
        self.assertEqual(claves.count("claude-20261023-ejemplo-0001"), 1)

    def test_simulador_no_modifica_datos(self):
        antes = self.datos()
        st.session_state["pagina"] = "Simulador"
        st.VALORES.update({"Volumen base mensual (sobres)": 5000, "Costo variable por sobre": 30.0})
        st.CLICS.add("Restablecer supuestos")
        self.correr()
        self.assertEqual(self.errores(), [])
        self.assertEqual(self.datos(), antes)

    def test_restaurar_desde_app(self):
        from lv import respaldos
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave="antes")))
        copia = respaldos.serializar(self.datos())
        self.repo.transaccion(lambda d: op.registrar_venta(d, self.entrada(clave="despues")))
        st.session_state["pagina"] = "Configuración y respaldos"
        st.ARCHIVOS["Respaldo generado por este sistema"] = Archivo(copia, "r.json")
        st.VALORES["Confirmo reemplazar los datos del servidor por este respaldo"] = True
        st.CLICS.add("Restaurar respaldo")
        self.correr()
        self.assertEqual(self.errores(), [])
        d = self.datos()
        self.assertIsNotNone(op.por_clave(d, "antes"))
        self.assertIsNone(op.por_clave(d, "despues"))
        self.assertTrue(list((__import__("pathlib").Path(self.db).parent / "respaldos").glob("*antes-de-restaurar.json")))


if __name__ == "__main__":
    unittest.main()
