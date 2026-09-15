# ============================================================
# Descripción:
# Punto único donde viven las rutas y los parámetros del
# proyecto. Cualquier módulo, script o notebook que necesite
# saber dónde está un fichero lo pregunta aquí, en lugar de
# escribir la ruta a mano.
#
# El proyecto está pensado para varios usuarios, así que la
# mayoría de las rutas se piden pasando el identificador del
# usuario. Los datos personales de cada uno viven en su propia
# carpeta; el catálogo musical es compartido, porque describe
# artistas y no personas.
#
# Se utiliza en:
# Todo el proyecto: ETL, enriquecimiento, modelado, aplicación
# y notebooks.
#
# Entrada:
# Opcionalmente, las variables de entorno TFM_RAIZ, TFM_USUARIO,
# MONGO_URI, MONGO_DB y LASTFM_API_KEY.
#
# Salida:
# Rutas (objetos Path) y constantes de configuración.
# ============================================================

import os
from pathlib import Path

# src/asistente/config.py -> parents[2] es la raíz del proyecto. Se deduce de la
# posición del fichero para que funcione igual desde el ordenador, desde un contenedor o
# desde un notebook, sin configurar nada.
RAIZ = Path(os.environ.get("TFM_RAIZ", Path(__file__).resolve().parents[2]))

DATOS = RAIZ / "datos"
USUARIOS = DATOS / "usuarios"     # una subcarpeta por usuario, con sus datos personales
CATALOGO = DATOS / "catalogo"     # etiquetas de artistas y caché de las APIs, compartido

DOCS = RAIZ / "docs"
NOTEBOOKS = RAIZ / "notebooks"   # notebooks del TFM original (no incluidos en esta versión)

# Usuario con el que se trabaja si no se indica otro. En el TFM es el usuario de
# desarrollo, el que tiene el historial completo con el que se ha construido todo.
USUARIO = os.environ.get("TFM_USUARIO", "usuario1")
ZONA_HORARIA = "Europe/Madrid"


# --- Datos de un usuario ---------------------------------------------------------
# Cada usuario tiene su carpeta con todo lo suyo dentro: el historial en bruto, los
# datos procesados, sus candidatos y su modelo. Borrar a un usuario del sistema es
# borrar su carpeta, lo que hace sencillo atender el derecho de supresión del RGPD.

def carpeta_usuario(usuario=USUARIO):
    return USUARIOS / usuario


def bruto(usuario=USUARIO):
    """Los JSON tal como los entrega Spotify."""
    return carpeta_usuario(usuario) / "bruto"


def reproducciones(usuario=USUARIO):
    """Historial limpio, salida del ETL."""
    return carpeta_usuario(usuario) / "reproducciones.parquet"


def dataset_modelado(usuario=USUARIO):
    """Tabla de entrenamiento, salida del notebook 02."""
    return carpeta_usuario(usuario) / "dataset_modelado.parquet"


def informe_calidad(usuario=USUARIO):
    return carpeta_usuario(usuario) / "informe_calidad.md"


def candidatos(usuario=USUARIO):
    """Canciones que este usuario no ha escuchado, para recomendarle.

    Son personales: se generan a partir de sus artistas más escuchados y excluyendo los
    que ya conoce.
    """
    return carpeta_usuario(usuario) / "candidatos.parquet"


def modelo_afinidad(usuario=USUARIO):
    """Modelo entrenado con el historial de este usuario."""
    return carpeta_usuario(usuario) / "modelo_afinidad.pkl"


def evaluacion(usuario=USUARIO):
    """Métricas y curvas de ese modelo, que lee la aplicación y la memoria."""
    return carpeta_usuario(usuario) / "evaluacion.pkl"


def figuras(usuario=USUARIO):
    """Figuras de los notebooks. Separadas por usuario para que no se pisen."""
    return NOTEBOOKS / "figuras" / usuario


def usuarios_disponibles():
    """Usuarios que tienen datos procesados, leyendo las carpetas que existen.

    Es lo que hoy sustituye al registro de usuarios. Cuando exista autenticación de
    verdad, esta función pasará a consultar la tabla de usuarios.
    """
    if not USUARIOS.is_dir():
        return []
    return sorted(c.name for c in USUARIOS.iterdir()
                  if c.is_dir() and not c.name.startswith("."))


# Usuarios del estudio: los dos historiales con los que se construyó el sistema y se hizo la
# réplica. La comparación del cuadro de mando es una pieza del estudio, no una pantalla de
# producto, así que se declara aquí y no se deduce de las carpetas que haya: dar de alta a
# otra persona en la aplicación no debe cambiar lo que esa comparación enseña. Se puede
# cambiar sin tocar el código con la variable de entorno TFM_USUARIOS_ESTUDIO.
USUARIOS_ESTUDIO = tuple(
    u.strip() for u in os.environ.get("TFM_USUARIOS_ESTUDIO", "usuario1,usuario2").split(",")
    if u.strip()
)


def usuarios_estudio():
    """Los usuarios del estudio que además tienen datos, en el orden en que se declaran."""
    disponibles = usuarios_disponibles()
    return [u for u in USUARIOS_ESTUDIO if u in disponibles]


# --- Catálogo musical compartido -------------------------------------------------
# Describe artistas, no personas, así que lo comparten todos los usuarios. Es además la
# parte cara de construir: al ser común, el coste se amortiza entre usuarios y cada
# usuario nuevo solo obliga a consultar los artistas que nadie había pedido antes.
TAGS_ARTISTAS = CATALOGO / "tags_artistas.parquet"
ARTISTAS_INFO = CATALOGO / "artistas_info.parquet"
CACHE_APIS = CATALOGO / "cache_apis.sqlite"
def informe_cobertura(usuario=USUARIO):
    """Cobertura de las fuentes externas sobre el historial de ESE usuario.

    Vive en el catálogo compartido porque describe qué parte del catálogo sirve, pero
    lleva el nombre del usuario: la cobertura depende de qué escucha cada uno.
    """
    return CATALOGO / f"informe_cobertura_{usuario}.md"

# --- Servicios externos ----------------------------------------------------------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "tfm_musica")
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")

# --- Spotify ---------------------------------------------------------------------
# Las mismas credenciales sirven para dos cosas distintas:
#   - Las portadas de la web, que usan el modo aplicación y no necesitan que nadie
#     inicie sesión, porque sólo piden datos públicos.
#   - Crear playlists en la cuenta del usuario, que sí necesita que esa persona
#     autorice la aplicación (flujo de código de autorización).
# Sin credenciales la web sigue funcionando: no hay portadas y el botón de crear
# playlist avisa de que la integración no está configurada.
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Dirección a la que Spotify devuelve al usuario después de autorizar. Tiene que ser
# EXACTAMENTE la misma que esté dada de alta en el panel de Spotify for Developers.
# Desde noviembre de 2025 Spotify no admite "localhost" como destino: en local hay que
# usar la dirección de bucle explícita 127.0.0.1, y fuera de local, HTTPS.
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI",
                                      "http://127.0.0.1:8501/spotify/callback")

# Permisos que se piden. Sólo el necesario para crear una playlist privada: no se pide
# leer el historial, ni la biblioteca, ni datos de la cuenta más allá del identificador.
SPOTIFY_PERMISOS = "playlist-modify-private"

# --- Recomendación y playlists ---------------------------------------------------
# Cuántas recomendaciones enseña la web y cuántas lleva la playlist. Son distintas a
# propósito: en pantalla caben pocas y se leen de un vistazo; una playlist se escucha.
RECOMENDACIONES_WEB = 6
CANCIONES_PLAYLIST = 20
# Proporción de canciones ya conocidas en cada lista. 0,5 reparte a partes iguales.
MEZCLA_CONOCIDAS = 0.5
# Máximo de canciones del mismo artista en una lista.
MAX_POR_ARTISTA = 2
# Peso del estado de ánimo al combinarlo con la puntuación del modelo.
PESO_ANIMO = 0.5
# Renovación de la lista. Con 0 se enseñan siempre las n mejores, que es lo que hacía el
# recomendador al principio y lo que provocaba que la misma persona con el mismo ánimo
# viera exactamente las mismas seis canciones todos los días. Con un valor mayor se abre
# una ventana de candidatos por encima de n (con 1, cinco veces n) y se sortean n de ella
# con probabilidad proporcional a su puntuación, sembrando el sorteo con la fecha. El
# valor está elegido a partir del experimento de igualdad y sesgos
# (experimento de sesgos del TFM original, no incluido en esta versión).
DIVERSIDAD = 0.5
# Nombre con el que empiezan las playlists creadas: "<prefijo> · <estado de ánimo>".
PLAYLIST_PREFIJO = os.environ.get("PLAYLIST_PREFIJO", "Sintonía")

# --- Parámetros del modelado -----------------------------------------------------
# La justificación de estos tres valores está en el notebook 02 y en el apartado 4.2.4
# de la memoria. Se dejan aquí para no tenerlos escritos en varios sitios.
VENTANA_DIAS = 30            # días que se observan tras descubrir una canción
MIN_REPETICIONES = 2         # repeticiones para considerar que la canción se quedó
SEG_ESCUCHA_VALIDA = 30      # segundos mínimos para que una escucha cuente
SEMILLA = 42
# Regularización de la regresión logística. El valor sale de la búsqueda de
# hiperparámetros del notebook 03; se guarda aquí para que el entrenamiento de un
# usuario nuevo use exactamente el mismo modelo que se estudió y se justificó.
C_REGULARIZACION = 0.03

CORTE_VALIDACION = "2024-01-01"
CORTE_PRUEBA = "2025-01-01"


def crear_carpetas(usuario=USUARIO):
    """Crea las carpetas que necesita un usuario, y el catálogo compartido."""
    for carpeta in (carpeta_usuario(usuario), bruto(usuario), CATALOGO, figuras(usuario)):
        carpeta.mkdir(parents=True, exist_ok=True)
