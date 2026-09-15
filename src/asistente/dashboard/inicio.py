# ============================================================
# Dashboard analítico de Sintonía (Streamlit, puerto 8502).
#
# Esta interfaz está separada de la aplicación Flask: aquí se
# analizan los datos, el enriquecimiento y la evaluación del
# modelo. No contiene documentación del código ni rutas internas.
# ============================================================

import streamlit as st

from asistente import config
from asistente.dashboard import estado, estilo
from asistente.dashboard.paginas import (animo, comparacion, descubrir, evaluacion,
                                         general, perfil)

st.set_page_config(
    page_title="Sintonía · Panel analítico",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)
estilo.aplicar_estilo()

with st.sidebar:
    st.markdown("# Sintonía")
    st.caption("Panel analítico · Big Data & Machine Learning")
    st.divider()

    disponibles = config.usuarios_disponibles()
    if not disponibles:
        st.error("No hay usuarios con datos procesados disponibles.")
        st.stop()

    st.selectbox("Usuario analizado", disponibles, key=estado.CLAVE_USUARIO)

recomendador, datos = estado.preparar(estado.usuario_actual())

paginas = [
    st.Page(general.mostrar, title="Visión general", url_path="general", default=True),
    st.Page(perfil.mostrar, title="Consumo musical", url_path="consumo"),
    st.Page(descubrir.mostrar, title="Descubrimiento", url_path="descubrimiento"),
    st.Page(animo.mostrar, title="Ánimo y recomendaciones", url_path="animo"),
    st.Page(evaluacion.mostrar, title="Evaluación del modelo", url_path="evaluacion"),
]
if len(disponibles) >= 2:
    paginas.append(st.Page(comparacion.mostrar, title="Comparación de usuarios", url_path="usuarios"))

with st.sidebar:
    st.divider()
    st.caption("FUENTE DE DATOS")
    st.markdown(f"**{datos['origen']}**")
    if recomendador.hay_fuentes_externas:
        st.caption(f"{len(recomendador.candidatos):,} canciones candidatas".replace(",", "."))
    else:
        st.caption("Sin catálogo de candidatos disponible")

st.navigation(paginas).run()
