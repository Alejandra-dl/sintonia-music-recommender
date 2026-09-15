# ============================================================
# Descripción:
# Estado compartido entre las pantallas de la aplicación.
# Guarda qué usuario se está viendo y carga una sola vez su
# historial y su modelo, que tardan unos segundos.
#
# Sin esto, cada cambio de pantalla volvería a leer los datos y
# a cargar el modelo. Con la caché de Streamlit se hace una vez
# por usuario y sesión.
#
# Se utiliza en:
# Las cinco pantallas y el arranque de la aplicación.
#
# Entrada:
# El identificador del usuario seleccionado.
#
# Salida:
# El recomendador ya construido y el detalle del origen de los
# datos, para mostrarlo en la barra lateral.
# ============================================================

import streamlit as st

from asistente import config
from asistente.datos.acceso import cargar
from asistente.recomendacion.recomendador import Recomendador

CLAVE_USUARIO = "usuario"


def usuario_actual():
    """Usuario que se está viendo ahora mismo.

    Hoy lo elige un desplegable en la barra lateral. Cuando exista registro e inicio de
    sesión, esta función devolverá el usuario de la sesión autenticada y el resto de la
    aplicación no tendrá que cambiar.
    """
    return st.session_state.get(CLAVE_USUARIO, config.USUARIO)


@st.cache_resource(show_spinner="Cargando historial y modelo…")
def preparar(usuario):
    """Devuelve el recomendador de ese usuario y de dónde se han leído sus datos.

    La caché va por usuario, así que cambiar de usuario en el desplegable carga sus datos
    una vez y luego navega igual de rápido.
    """
    datos = cargar(usuario=usuario)
    recomendador = Recomendador(usuario=usuario,
                                reproducciones=datos["reproducciones"],
                                tags=datos["tags"],
                                candidatos=datos["candidatos"])
    return recomendador, datos
