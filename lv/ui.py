"""Componentes visuales de la app (Streamlit + HTML acotado)."""
from __future__ import annotations

import html

import streamlit as st

BOSQUE = "#0B5127"
OLIVA = "#8EB712"
BEIGE = "#F4F0EA"
TINTA = "#1E2B22"
TENUE = "#5B6B60"
AMBAR = "#9A6A00"
ROJO = "#A4262C"
LINEA = "#DDD6CA"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stApp, button, input, textarea, select {{
  font-family: 'Manrope', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}
.stApp {{ background: {BEIGE}; color: {TINTA}; }}
section[data-testid="stSidebar"] {{ background: #EDE6DA; border-right: 1px solid {LINEA}; }}
h1, h2, h3 {{ color: {BOSQUE} !important; letter-spacing: -0.01em; }}
h1 {{ font-size: 1.75rem !important; font-weight: 700 !important; }}
h2 {{ font-size: 1.3rem !important; font-weight: 700 !important; }}
h3 {{ font-size: 1.05rem !important; font-weight: 600 !important; }}
.block-container {{ padding-top: 1.6rem; max-width: 1240px; }}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: {BOSQUE}; border: 1px solid {BOSQUE}; color: #fff; font-weight: 600;
}}
.stButton > button[kind="primary"]:hover {{ background: #0E6431; border-color: #0E6431; }}
.stButton > button:focus-visible {{ outline: 3px solid {OLIVA}; outline-offset: 2px; }}
[data-testid="stDataFrame"] {{ background: #fff; border-radius: 8px; }}
div[data-testid="stExpander"] details {{ background: #fff; border-radius: 8px; border: 1px solid {LINEA}; }}
/* Franja de indicadores: una superficie, divisiones internas, estado del dato escrito */
.franja {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  background: #fff; border: 1px solid {LINEA}; border-radius: 12px; margin: .25rem 0 1rem; overflow: hidden; }}
.ind {{ padding: 14px 18px 12px; border-right: 1px solid {LINEA}; border-bottom: 1px solid {LINEA}; margin: 0 -1px -1px 0; }}
.ind .et {{ font-size: .82rem; color: {TENUE}; font-weight: 500; }}
.ind .va {{ font-size: 1.45rem; font-weight: 700; color: {BOSQUE}; font-variant-numeric: tabular-nums;
  line-height: 1.25; margin-top: 2px; }}
.ind .va.nd {{ color: {TENUE}; font-size: 1.05rem; font-weight: 600; }}
.ind .es {{ font-size: .78rem; margin-top: 4px; color: {TENUE}; }}
.es.ok::before {{ content: "✓ "; color: {BOSQUE}; font-weight: 700; }}
.es.pre::before {{ content: "◐ "; color: {AMBAR}; font-weight: 700; }}
.es.nd::before {{ content: "— "; color: {TENUE}; font-weight: 700; }}
.es.err::before {{ content: "✕ "; color: {ROJO}; font-weight: 700; }}
.encabezado {{ display:flex; align-items:flex-end; justify-content:space-between; gap: 1rem; flex-wrap: wrap; }}
.sub {{ color: {TENUE}; margin: -.4rem 0 1rem; font-size: .95rem; max-width: 70ch; }}
.etiqueta {{ display:inline-block; padding: 1px 8px; border-radius: 999px; font-size: .78rem; font-weight: 600;
  border: 1px solid {LINEA}; background: #fff; color: {TINTA}; }}
.vista-previa {{ background:#fff; border:1px solid {LINEA}; border-left: 4px solid {OLIVA}; border-radius: 10px;
  padding: 12px 16px; font-variant-numeric: tabular-nums; }}
.vista-previa table {{ width:100%; border-collapse: collapse; }}
.vista-previa td {{ padding: 3px 0; }}
.vista-previa td:last-child {{ text-align: right; font-weight: 600; }}
.vista-previa tr.total td {{ border-top: 1px solid {LINEA}; padding-top: 6px; color: {BOSQUE}; }}
.vista-previa .nota {{ color: {TENUE}; font-size: .8rem; }}
@media (max-width: 640px) {{
  .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  [data-testid="stColumn"] {{ min-width: 100% !important; }}
  .ind .va {{ font-size: 1.25rem; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>
"""

ESTADOS = {"ok": "Registrado", "pre": "Preliminar", "nd": "No disponible", "err": "Revisar"}


def estilos():
    st.markdown(CSS, unsafe_allow_html=True)


def franja(indicadores: list[dict]):
    """indicadores: {"etiqueta", "valor" (texto o None), "estado": ok|pre|nd|err, "nota"}."""
    partes = []
    for i in indicadores:
        valor = i.get("valor")
        estado = i.get("estado") or ("nd" if valor is None else "ok")
        texto_valor = "No disponible" if valor is None else valor
        nota = i.get("nota") or ESTADOS[estado]
        partes.append(
            f'<div class="ind"><div class="et">{html.escape(i["etiqueta"])}</div>'
            f'<div class="va{" nd" if valor is None else ""}">{html.escape(str(texto_valor))}</div>'
            f'<div class="es {estado}">{html.escape(nota)}</div></div>')
    st.markdown(f'<div class="franja">{"".join(partes)}</div>', unsafe_allow_html=True)


def subtitulo(texto: str):
    st.markdown(f'<p class="sub">{html.escape(texto)}</p>', unsafe_allow_html=True)


def vista_previa(filas: list[tuple], total: tuple | None = None, nota: str | None = None):
    cuerpo = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td></tr>" for a, b in filas)
    if total:
        cuerpo += f'<tr class="total"><td>{html.escape(total[0])}</td><td>{html.escape(total[1])}</td></tr>'
    extra = f'<div class="nota">{html.escape(nota)}</div>' if nota else ""
    st.markdown(f'<div class="vista-previa"><table>{cuerpo}</table>{extra}</div>', unsafe_allow_html=True)


def layout_grafica(fig, alto: int = 320, titulo: str | None = None):
    fig.update_layout(
        height=alto, margin=dict(l=8, r=8, t=40 if titulo else 12, b=8),
        title=dict(text=titulo, x=0, font=dict(size=15, color=BOSQUE)) if titulo else None,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Manrope, system-ui, sans-serif", color=TINTA, size=13),
        xaxis=dict(gridcolor="#EEE9E0", zeroline=False), yaxis=dict(gridcolor="#EEE9E0", zeroline=False),
        legend=dict(orientation="h", y=-0.2), hoverlabel=dict(font_family="Manrope, system-ui, sans-serif"))
    return fig
