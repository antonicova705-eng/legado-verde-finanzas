"""Componentes visuales de la app (Streamlit + HTML acotado).

Paleta: bosque #0B5127 (marca y datos), noche #0A3A20 (barra lateral),
lima #A6D12B / oliva #8EB712 (acentos y periodos parciales), fondo #F5F6F1,
superficies blancas. Ámbar y rojo solo para pendiente y error.
"""
from __future__ import annotations

import html

import streamlit as st

BOSQUE = "#0B5127"
NOCHE = "#0A3A20"
OLIVA = "#8EB712"
LIMA = "#A6D12B"
FONDO = "#F5F6F1"
TINTA = "#18241C"
TENUE = "#5E6B62"
AMBAR = "#9A6A00"
ROJO = "#B3261E"
LINEA = "#E3E6DD"
SERIE = [BOSQUE, OLIVA, "#3E8E63", "#C9B458", "#6F8F7A", "#2F6F8F"]

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
html, body, .stApp, button, input, textarea, select, [data-testid="stMarkdownContainer"] {{
  font-family: 'Manrope', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}
.stApp {{ background: {FONDO}; color: {TINTA}; }}
.block-container {{ padding-top: 3.6rem; max-width: 1260px; }}
h1, h2, h3 {{ color: {TINTA} !important; letter-spacing: -0.02em; }}
h1 {{ font-size: 1.9rem !important; font-weight: 800 !important; }}
h3 {{ font-size: 1.08rem !important; font-weight: 700 !important; margin-top: .6rem !important; }}

/* Barra lateral: menú como lista con ícono, sin círculos de radio */
section[data-testid="stSidebar"] {{ background: {NOCHE}; }}
section[data-testid="stSidebar"] [data-testid="stImage"] img {{ border-radius: 14px; }}
section[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
section[data-testid="stSidebar"] [role="radiogroup"] label {{
  display: flex !important; width: 100% !important; box-sizing: border-box; padding: 9px 12px;
  border-radius: 10px; margin: 0; cursor: pointer; transition: background .15s ease; }}
/* El círculo del radio es el único hijo directo sin texto */
section[data-testid="stSidebar"] [role="radiogroup"] label > div:not(:has(p)) {{ display: none !important; }}
section[data-testid="stSidebar"] [role="radiogroup"] label > div:has(p) {{ padding-left: 0 !important; margin-left: 0 !important; }}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: rgba(255,255,255,.07); }}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: rgba(166,209,43,.16); box-shadow: inset 3px 0 0 {LIMA}; }}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ font-weight: 700; color: #fff; }}
section[data-testid="stSidebar"] [role="radiogroup"] p {{ font-size: .95rem; }}
section[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.12); }}

/* Botones */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{ font-weight: 600; border-radius: 10px; }}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
  background: {BOSQUE}; border: 1px solid {BOSQUE}; color: #fff; box-shadow: 0 1px 2px rgba(11,81,39,.25); }}
.stButton > button[kind="primary"]:hover {{ background: #0E6431; border-color: #0E6431; }}
button:focus-visible {{ outline: 3px solid {LIMA} !important; outline-offset: 2px; }}

/* Superficies */
[data-testid="stDataFrame"], [data-testid="stPlotlyChart"] {{ background: #fff; border-radius: 14px;
  border: 1px solid {LINEA}; padding: 6px; }}
div[data-testid="stExpander"] details {{ background: #fff; border-radius: 14px; border: 1px solid {LINEA}; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
.stTabs [data-baseweb="tab"] {{ border-radius: 999px; padding: 6px 14px; background: #fff; border: 1px solid {LINEA}; }}
.stTabs [aria-selected="true"] {{ background: {BOSQUE}; color: #fff; border-color: {BOSQUE}; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}
div[role="radiogroup"][aria-orientation="horizontal"] label {{ background: #fff; border: 1px solid {LINEA};
  border-radius: 999px; padding: 4px 14px; }}
div[role="radiogroup"][aria-orientation="horizontal"] label:has(input:checked) {{ background: {BOSQUE}; border-color: {BOSQUE}; }}
div[role="radiogroup"][aria-orientation="horizontal"] label:has(input:checked) p {{ color: #fff; font-weight: 700; }}
div[role="radiogroup"][aria-orientation="horizontal"] label > div:not(:has(p)) {{ display: none !important; }}

/* Indicadores: tarjetas; la destacada en verde bosque */
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: .3rem 0 1.1rem; }}
.kpi {{ background: #fff; border: 1px solid {LINEA}; border-radius: 16px; padding: 16px 18px 14px;
  box-shadow: 0 1px 2px rgba(24,36,28,.04); }}
.kpi .et {{ font-size: .82rem; color: {TENUE}; font-weight: 600; }}
.kpi .va {{ font-size: 1.55rem; font-weight: 800; color: {TINTA}; font-variant-numeric: tabular-nums;
  line-height: 1.2; margin-top: 6px; letter-spacing: -0.02em; }}
.kpi .va.nd {{ color: {TENUE}; font-size: 1.05rem; font-weight: 700; }}
.kpi .es {{ display: inline-block; margin-top: 10px; font-size: .74rem; font-weight: 600; padding: 2px 9px;
  border-radius: 999px; background: #F0F2EC; color: {TENUE}; }}
.kpi .es.ok {{ background: #E6F1E9; color: {BOSQUE}; }}
.kpi .es.pre {{ background: #FBF1DA; color: {AMBAR}; }}
.kpi .es.err {{ background: #FBE4E2; color: {ROJO}; }}
.es.ok::before {{ content: "✓ "; }} .es.pre::before {{ content: "◐ "; }}
.es.nd::before {{ content: "— "; }} .es.err::before {{ content: "✕ "; }}
.kpi.destacado {{ background: {BOSQUE}; border-color: {BOSQUE}; grid-column: span 2;
  background-image: radial-gradient(circle at 100% 0%, rgba(166,209,43,.28), transparent 55%); }}
.kpi.destacado .et {{ color: #CFE3D4; }}
.kpi.destacado .va {{ color: #fff; font-size: 2.2rem; }}
.kpi.destacado .va.nd {{ color: #E7EFE9; }}
.kpi.destacado .es {{ background: rgba(255,255,255,.14); color: #fff; }}

.periodo {{ color: {BOSQUE}; font-weight: 700; font-size: .9rem; margin-bottom: -.4rem; }}
.sub {{ color: {TENUE}; margin: -.3rem 0 1.1rem; font-size: .95rem; max-width: 72ch; }}
.vista-previa {{ background:#fff; border:1px solid {LINEA}; border-radius: 16px; padding: 14px 18px;
  font-variant-numeric: tabular-nums; }}
.vista-previa table {{ width:100%; border-collapse: collapse; }}
.vista-previa td {{ padding: 4px 0; }}
.vista-previa td:last-child {{ text-align: right; font-weight: 600; }}
.vista-previa tr.total td {{ border-top: 1px solid {LINEA}; padding-top: 8px; color: {BOSQUE}; font-weight: 800; }}
.vista-previa .nota {{ color: {TENUE}; font-size: .8rem; margin-top: 6px; }}
@media (max-width: 640px) {{
  .block-container {{ padding: 1.2rem 1rem; }}
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  [data-testid="stColumn"] {{ min-width: 100% !important; }}
  .kpi.destacado {{ grid-column: span 1; }}
  .kpi .va {{ font-size: 1.3rem; }} .kpi.destacado .va {{ font-size: 1.8rem; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style>
"""

ESTADOS = {"ok": "Registrado", "pre": "Preliminar", "nd": "No disponible", "err": "Revisar"}


def estilos():
    st.markdown(CSS, unsafe_allow_html=True)


def franja(indicadores: list[dict]):
    """indicadores: {"etiqueta", "valor" (texto o None), "estado": ok|pre|nd|err, "nota", "destacado"}."""
    partes = []
    for i in indicadores:
        valor = i.get("valor")
        estado = i.get("estado") or ("nd" if valor is None else "ok")
        texto_valor = "No disponible" if valor is None else valor
        nota = i.get("nota") or ESTADOS[estado]
        clase = "kpi destacado" if i.get("destacado") else "kpi"
        partes.append(
            f'<div class="{clase}"><div class="et">{html.escape(i["etiqueta"])}</div>'
            f'<div class="va{" nd" if valor is None else ""}">{html.escape(str(texto_valor))}</div>'
            f'<div class="es {estado}">{html.escape(nota)}</div></div>')
    st.markdown(f'<div class="kpis">{"".join(partes)}</div>', unsafe_allow_html=True)


def periodo(texto: str):
    st.markdown(f'<div class="periodo">{html.escape(texto)}</div>', unsafe_allow_html=True)


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
        height=alto, margin=dict(l=8, r=8, t=44 if titulo else 12, b=8),
        title=dict(text=titulo, x=0.01, font=dict(size=15, color=TINTA, family="Manrope, system-ui, sans-serif")) if titulo else None,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", bargap=0.35, barcornerradius=6,
        font=dict(family="Manrope, system-ui, sans-serif", color=TENUE, size=12),
        xaxis=dict(gridcolor="#EEF0EA", zeroline=False, linecolor=LINEA),
        yaxis=dict(gridcolor="#EEF0EA", zeroline=False),
        legend=dict(orientation="h", y=-0.18), hoverlabel=dict(font_family="Manrope, system-ui, sans-serif", bgcolor="#fff"))
    return fig
