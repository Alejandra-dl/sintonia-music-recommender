"""Estilo visual del dashboard analítico.

El dashboard tiene una identidad distinta de la aplicación Flask: fondo oscuro, acento
verde y una paleta multicolor para comparar categorías. Las funciones de este módulo son
solo de presentación; no alteran datos ni resultados.
"""

import plotly.graph_objects as go
import streamlit as st

FONDO = "#0b0f0c"
SUPERFICIE = "#111713"
SUPERFICIE_2 = "#171f19"
BORDE = "#263128"
TINTA = "#f2f6f2"
TINTA_2 = "#b4c0b6"
APAGADO = "#758078"
REJILLA = "#263128"

# Acento de la interfaz: rótulos, bordes y notas. No se usa para pintar datos,
# porque es demasiado claro para funcionar como marca sobre el fondo del panel.
ACENTO = "#1ed760"

# Paleta categórica de las gráficas. Los ocho tonos y su orden están validados
# sobre el fondo del panel: todos caen en la banda de luminosidad del modo
# oscuro, superan el contraste 3:1 y mantienen separación suficiente entre
# tonos contiguos también para las formas más frecuentes de daltonismo.
# El orden es parte de esa garantía: no conviene reordenarlos sin volver a
# comprobarlo.
VERDE = "#199e70"        # serie 1
NARANJA = "#d95926"      # serie 2
AZUL = "#3987e5"         # serie 3
AMARILLO = "#c98500"     # serie 4
ROSA = "#d55181"         # serie 5
VERDE_OSCURO = "#008300"  # serie 6
VIOLETA = "#9085e9"      # serie 7
ROJO = "#e66767"         # serie 8
TURQUESA = VERDE         # nombre heredado, apunta a la serie 1
COLORES = [VERDE, NARANJA, AZUL, AMARILLO, ROSA, VERDE_OSCURO, VIOLETA, ROJO]

TIPOGRAFIA = "Inter, system-ui, -apple-system, Segoe UI, sans-serif"

# Rampa secuencial de un solo tono, para magnitudes continuas (mapas de calor).
RAMPA = ["#0f2419", "#134a31", "#166b45", "#199e70", "#3fbf90", "#7ed9b4"]
ESCALA_CALOR = [[i / (len(RAMPA) - 1), c] for i, c in enumerate(RAMPA)]

PLANTILLA = go.layout.Template(layout=dict(
    font=dict(family=TIPOGRAFIA, size=13, color=TINTA_2),
    paper_bgcolor=SUPERFICIE,
    plot_bgcolor=SUPERFICIE,
    title=dict(font=dict(size=15, color=TINTA), x=0.01, xanchor="left",
               y=0.97, yanchor="top"),
    # automargin deja que Plotly reserve el sitio que necesitan las etiquetas.
    # Sin esto, los nombres largos de artista o de modelo se cortaban.
    xaxis=dict(showgrid=False, linecolor=BORDE, automargin=True,
               tickfont=dict(color=APAGADO), title_font=dict(color=TINTA_2)),
    yaxis=dict(gridcolor=REJILLA, zeroline=False, linecolor="rgba(0,0,0,0)",
               automargin=True, tickfont=dict(color=APAGADO),
               title_font=dict(color=TINTA_2)),
    margin=dict(l=20, r=24, t=58, b=48),
    colorway=COLORES,
    bargap=0.28,
    bargroupgap=0.08,
    # Leyenda en la misma banda que el título, alineada a la derecha: no roba
    # altura al área de dibujo y las gráficas de una sola serie, que no llevan
    # leyenda, no dejan un hueco vacío bajo el título.
    legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1, xanchor="right",
                font=dict(color=TINTA_2)),
    hoverlabel=dict(bgcolor=SUPERFICIE_2, font_color=TINTA,
                    bordercolor=BORDE),
))
# Barras con las esquinas del extremo redondeadas, igual en todas las gráficas.
PLANTILLA.data.bar = [go.Bar(marker=dict(cornerradius=4))]


def aplicar_estilo():
    """Inyecta el tema visual del panel una vez por renderizado."""
    st.markdown(
        f"""
        <style>
        .stApp {{ background: {FONDO}; color: {TINTA}; }}
        [data-testid="stSidebar"] {{ background: #0e130f; border-right: 1px solid {BORDE}; }}
        [data-testid="stSidebar"] * {{ color: {TINTA_2}; }}
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 {{ color: {TINTA}; }}
        [data-testid="stMetric"] {{
            background: {SUPERFICIE}; border: 1px solid {BORDE}; border-radius: 14px;
            padding: 14px 16px; min-height: 104px;
        }}
        [data-testid="stMetricLabel"] {{ color: {APAGADO}; }}
        [data-testid="stMetricValue"] {{ color: {TINTA}; }}
        div[data-testid="stPlotlyChart"] {{
            background:{SUPERFICIE}; border:1px solid {BORDE}; border-radius:14px; overflow:hidden;
        }}
        .stDataFrame {{ border:1px solid {BORDE}; border-radius:12px; overflow:hidden; }}
        .stSelectbox label, .stSlider label, .stRadio label {{ color:{TINTA_2} !important; }}
        hr {{ border-color:{BORDE} !important; }}
        .analitica-kicker {{ color:{ACENTO}; font-size:.76rem; font-weight:700; letter-spacing:.12em; margin-bottom:.15rem; }}
        .analitica-subtitulo {{ color:{TINTA_2}; margin-top:-.35rem; margin-bottom:1.3rem; max-width:900px; }}
        .interpretacion {{
            margin:.25rem 0 1.25rem; padding:.75rem 1rem; border-left:3px solid {ACENTO};
            background:rgba(30,215,96,.06); color:{TINTA_2}; border-radius:0 9px 9px 0;
            font-size:.92rem;
        }}
        .nota-metodo {{ color:{APAGADO}; font-size:.82rem; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def cabecera(titulo, subtitulo, kicker="ANÁLISIS"):
    st.markdown(f'<div class="analitica-kicker">{kicker}</div>', unsafe_allow_html=True)
    st.header(titulo)
    st.markdown(f'<div class="analitica-subtitulo">{subtitulo}</div>', unsafe_allow_html=True)


def interpretacion(texto):
    if texto:
        st.markdown(f'<div class="interpretacion">{texto}</div>', unsafe_allow_html=True)


def figura(titulo="", alto=330, **kwargs):
    fig = go.Figure()
    fig.update_layout(template=PLANTILLA, title=titulo, height=alto, **kwargs)
    return fig


def grafica(fig, **kwargs):
    """Pinta una figura en el panel conservando la plantilla del proyecto.

    Streamlit aplica su propio tema a las gráficas de Plotly y pisa la plantilla, lo que
    dejaba figuras de fondo blanco dentro de un panel oscuro. Con `theme=None` manda la
    plantilla de este módulo, que es la que tiene la paleta comprobada sobre este fondo.
    Todas las páginas pintan por aquí para no tener que acordarse en cada llamada.
    """
    st.plotly_chart(fig, theme=None, width="stretch", **kwargs)


def envolver(texto, ancho=16):
    """Parte una etiqueta larga en varias líneas, respetando las palabras.

    Es solo presentación: no cambia el texto, únicamente dónde salta de línea,
    para que los nombres largos quepan bajo el eje.
    """
    palabras, lineas, actual = str(texto).split(), [], ""
    for palabra in palabras:
        if actual and len(actual) + 1 + len(palabra) > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    if actual:
        lineas.append(actual)
    return "<br>".join(lineas)


def miles(n):
    return f"{n:,.0f}".replace(",", ".")
