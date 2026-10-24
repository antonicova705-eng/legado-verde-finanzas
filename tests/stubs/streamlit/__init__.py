"""STREAMLIT FALSO para pruebas de humo: ejecuta app.py sin navegador.

No dibuja nada; devuelve valores por omisión de cada widget (o los de
session_state) y permite simular clics. Sirve para detectar errores de
ejecución (nombres indefinidos, tipos) en cada sección, no para revisar el
diseño visual.
"""
from __future__ import annotations

import datetime as _dt
import types


class Detener(Exception):
    pass


class Reejecutar(Exception):
    pass


class _Estado(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


session_state = _Estado()
CLICS: set = set()          # etiquetas de botones que se "presionan"
VALORES: dict = {}          # etiqueta -> valor a devolver
SALIDA: list = []           # registro de mensajes mostrados
ARCHIVOS: dict = {}         # etiqueta de file_uploader -> objeto con getvalue() y name


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, nombre):
        return globals()[nombre]


def _reg(tipo, *a):
    SALIDA.append((tipo, " ".join(str(x) for x in a)))


def _valor(label, key, defecto):
    if key is not None and key in session_state:
        return session_state[key]
    if label in VALORES:
        v = VALORES[label]
    else:
        v = defecto
    if key is not None:
        session_state[key] = v
    return v


def set_page_config(**k): pass
def markdown(*a, **k): _reg("markdown", *a)
def write(*a, **k): _reg("write", *a)
def caption(*a, **k): _reg("caption", *a)
def code(*a, **k): pass
def json(*a, **k): pass
def image(*a, **k): pass
def divider(*a, **k): pass
def title(*a, **k): _reg("title", *a)
def subheader(*a, **k): pass
def error(*a, **k): _reg("error", *a)
def warning(*a, **k): _reg("warning", *a)
def info(*a, **k): _reg("info", *a)
def success(*a, **k): _reg("success", *a)
def toast(*a, **k): _reg("toast", *a)
def metric(*a, **k): _reg("metric", *a)
def dataframe(df=None, **k): _reg("dataframe", getattr(df, "shape", None))
def plotly_chart(*a, **k): _reg("chart")
def download_button(*a, **k): return False
def spinner(*a, **k): return _Ctx()
def expander(*a, **k): return _Ctx()
def form(*a, **k): return _Ctx()
def container(*a, **k): return _Ctx()


def stop():
    raise Detener()


def rerun():
    raise Reejecutar()


def cache_resource(f=None, **k):
    memo = {}

    def envoltura(*a):
        if a not in memo:
            memo[a] = f(*a)
        return memo[a]
    return envoltura if f else (lambda g: cache_resource(g))


def columns(spec, **k):
    n = spec if isinstance(spec, int) else len(spec)
    return [_Ctx() for _ in range(n)]


def tabs(nombres):
    return [_Ctx() for _ in nombres]


def button(label, key=None, on_click=None, disabled=False, **k):
    presionado = label in CLICS and not disabled
    if presionado and on_click:
        on_click()
    return presionado


def form_submit_button(label, **k):
    return button(label, **k)


def selectbox(label, options, index=0, key=None, format_func=str, **k):
    options = list(options)
    v = _valor(label, key, options[index] if options else None)
    if options and v not in options:
        v = options[0]
    format_func(v) if v is not None else None
    return v


def radio(label, options, index=0, key=None, **k):
    return selectbox(label, options, index, key)


def number_input(label, min_value=None, max_value=None, value=None, key=None, **k):
    if value is None:
        value = min_value if min_value is not None else 0
    return _valor(label, key, value)


def date_input(label, value=None, key=None, **k):
    return _valor(label, key, value or _dt.date.today())


def text_input(label, value="", key=None, **k):
    return _valor(label, key, value)


def text_area(label, value="", key=None, **k):
    return _valor(label, key, value)


def checkbox(label, value=False, key=None, **k):
    return _valor(label, key, value)


def toggle(label, value=False, key=None, **k):
    return _valor(label, key, value)


def data_editor(df, key=None, **k):
    return df


def file_uploader(label, key=None, **k):
    return ARCHIVOS.get(label)


class _ColumnConfig:
    def __getattr__(self, nombre):
        return lambda *a, **k: (nombre, a, k)


column_config = _ColumnConfig()
sidebar = types.SimpleNamespace(**{n: globals()[n] for n in [
    "selectbox", "radio", "number_input", "date_input", "button", "caption", "error", "warning", "info",
    "image", "divider", "columns", "markdown", "success", "download_button", "expander"]})
