"""Registra ventas desde un archivo JSON/CSV usando la misma lógica de la app.

Uso (en la máquina donde vive la base de datos):

    python registrar_venta.py ventas.json              # solo vista previa, no escribe
    python registrar_venta.py ventas.json --confirmar  # escribe y verifica

Variables: LEGADO_VERDE_DB (ruta de la base). Repetir el comando con el mismo
archivo no duplica: cada venta trae una clave de idempotencia.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lv import importacion, operaciones as op  # noqa: E402
from lv.arranque import abrir  # noqa: E402
from lv.util import moneda  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("archivo")
    p.add_argument("--db", help="Ruta de la base (por omisión LEGADO_VERDE_DB o datos/legado_verde.sqlite3)")
    p.add_argument("--confirmar", action="store_true", help="Escribir en la base")
    p.add_argument("--aceptar-posibles-duplicados", default="", help="Filas a importar pese a coincidir, p. ej. 2,5")
    a = p.parse_args(argv)
    repo = abrir(a.db)
    ventas = importacion.leer(Path(a.archivo).read_bytes(), a.archivo)
    _, datos = repo.leer()
    filas = importacion.previsualizar(datos, ventas)
    for f in filas:
        v = f["venta"] or {}
        print(f"Fila {f['Fila']}: {f['Estado']} · {v.get('Fecha')} · {v.get('Canal')} · "
              f"{v.get('Cantidad')} sobres · venta neta {moneda((v.get('Ventas Producto') or 0) - (v.get('Descuento') or 0) - (v.get('Devolución') or 0))}"
              + (f" · cobro {moneda(f['cobro']['importe'])} el {f['cobro']['fecha']}" if f["cobro"] else ""))
        for m in f["Mensajes"]:
            print("   -", m)
        if f["Pendientes"]:
            print("   Pendientes:", "; ".join(f["Pendientes"]))
    if any(f["Estado"] == "Error" for f in filas):
        print("\nHay errores: no se escribió nada.")
        return 2
    if not a.confirmar:
        print("\nVista previa: no se escribió nada. Repite con --confirmar para registrar.")
        return 0
    aceptadas = {int(x) for x in a.aceptar_posibles_duplicados.split(",") if x.strip()}
    salida = repo.transaccion(lambda d: importacion.aplicar(d, importacion.previsualizar(d, ventas), aceptadas, ventas))
    _, verif = repo.leer()
    print()
    for s in salida:
        ok = s["ID"] is None or op.por_id(verif, s["ID"]) is not None
        print(f"Fila {s['Fila']}: {s['Resultado']} · ID {s['ID']}" + (f" · cobro {s['Cobro']}" if s.get("Cobro") else "")
              + ("" if ok else "  ⚠ NO VERIFICADA EN LA BASE"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
