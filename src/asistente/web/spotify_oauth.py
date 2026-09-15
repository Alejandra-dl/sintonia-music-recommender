# ============================================================
# Descripción:
# Conexión de la cuenta de Spotify del usuario, con el flujo de
# código de autorización (authorization code). Es el flujo que
# corresponde a una aplicación con servidor como esta, porque el
# secreto nunca sale del contenedor y el navegador sólo ve un
# código de un solo uso.
#
# Este módulo NO habla con las playlists: sólo consigue y
# mantiene vivo el token del usuario. Crear la playlist es cosa
# de playlists.py.
#
# Nota sobre la dirección de retorno: desde la migración de
# noviembre de 2025 Spotify no admite "localhost" como Redirect
# URI, ni el flujo implícito. En local hay que registrar la
# dirección de bucle explícita, http://127.0.0.1:8501/...
#
# Se utiliza en:
# Las rutas /spotify/... de la aplicación Flask.
#
# Entrada:
# Las credenciales de la aplicación y la sesión de Flask.
#
# Salida:
# Un token de acceso válido, o un error con un mensaje que se le
# puede enseñar a una persona.
# ============================================================

import base64
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from asistente import config

AUTORIZAR = "https://accounts.spotify.com/authorize"
TOKEN = "https://accounts.spotify.com/api/token"
PERFIL = "https://api.spotify.com/v1/me"

# Claves con las que se guarda el token en la sesión de Flask.
CLAVE_TOKEN = "spotify_token"
CLAVE_ESTADO = "spotify_estado"


class ErrorSpotify(Exception):
    """Error de la integración con un mensaje pensado para el usuario.

    El detalle técnico se guarda aparte, para el registro del servidor. Al usuario se le
    enseña sólo `mensaje`, que nunca contiene tokens, códigos ni nombres de variables.
    """

    def __init__(self, mensaje, detalle=""):
        super().__init__(detalle or mensaje)
        self.mensaje = mensaje
        self.detalle = detalle


def hay_configuracion():
    """¿Están puestas las tres variables que hacen falta?"""
    return bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET
                and config.SPOTIFY_REDIRECT_URI)


def _cabecera_basica():
    credenciales = f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}"
    return "Basic " + base64.b64encode(credenciales.encode()).decode()


def _pedir_token(datos):
    """Llama al endpoint de token y devuelve su respuesta ya interpretada."""
    peticion = urllib.request.Request(
        TOKEN,
        data=urllib.parse.urlencode(datos).encode(),
        headers={"Authorization": _cabecera_basica(),
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            return json.load(respuesta)
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")[:300]
        if e.code in (400, 401):
            raise ErrorSpotify(
                "Spotify no ha aceptado la conexión. Vuelve a conectar tu cuenta y, si "
                "sigue fallando, revisa que la dirección de retorno configurada en "
                "Spotify sea exactamente la misma que usa la aplicación.",
                f"HTTP {e.code}: {cuerpo}") from e
        raise ErrorSpotify("Spotify no está respondiendo ahora mismo. Inténtalo de nuevo "
                           "en unos minutos.", f"HTTP {e.code}: {cuerpo}") from e
    except urllib.error.URLError as e:
        raise ErrorSpotify("No he podido conectar con Spotify. Comprueba tu conexión a "
                           "internet e inténtalo de nuevo.", str(e)) from e


# ---------------------------------------------------------------------------------
# Paso 1: mandar al usuario a Spotify
# ---------------------------------------------------------------------------------
def url_autorizacion(sesion):
    """Dirección a la que hay que enviar al usuario para que autorice la aplicación.

    El parámetro `state` es una cadena aleatoria que se guarda en la sesión y que Spotify
    devuelve tal cual. Comprobarla al volver es lo que evita que alguien fabrique una
    vuelta falsa desde otra pestaña.
    """
    if not hay_configuracion():
        raise ErrorSpotify("La conexión con Spotify no está configurada en este equipo.")
    estado = secrets.token_urlsafe(16)
    sesion[CLAVE_ESTADO] = estado
    parametros = {
        "client_id": config.SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.SPOTIFY_REDIRECT_URI,
        "scope": config.SPOTIFY_PERMISOS,
        "state": estado,
        "show_dialog": "false",
    }
    return AUTORIZAR + "?" + urllib.parse.urlencode(parametros)


# ---------------------------------------------------------------------------------
# Paso 2: cambiar el código por un token
# ---------------------------------------------------------------------------------
def canjear_codigo(sesion, codigo, estado_recibido):
    """Cambia el código de un solo uso por un token y lo guarda en la sesión."""
    esperado = sesion.pop(CLAVE_ESTADO, None)
    if not esperado or estado_recibido != esperado:
        raise ErrorSpotify("La conexión con Spotify no ha podido verificarse. "
                           "Vuelve a intentarlo desde la aplicación.",
                           "el parámetro state no coincide")
    datos = _pedir_token({"grant_type": "authorization_code",
                          "code": codigo,
                          "redirect_uri": config.SPOTIFY_REDIRECT_URI})
    _guardar(sesion, datos)
    return datos


def _guardar(sesion, datos, refresco_anterior=None):
    """Guarda el token en la sesión con el momento en que caduca.

    Spotify no siempre devuelve un refresh_token nuevo al refrescar: si no viene, hay que
    conservar el que ya se tenía o la sesión se perdería en una hora.
    """
    sesion[CLAVE_TOKEN] = {
        "access_token": datos.get("access_token", ""),
        "refresh_token": datos.get("refresh_token") or refresco_anterior or "",
        "caduca_en": time.time() + int(datos.get("expires_in", 3600)) - 60,
    }


# ---------------------------------------------------------------------------------
# Paso 3: usar el token, refrescándolo cuando toque
# ---------------------------------------------------------------------------------
def hay_sesion(sesion):
    return bool(sesion.get(CLAVE_TOKEN, {}).get("access_token"))


def token_de_acceso(sesion):
    """Devuelve un token válido, refrescándolo si ha caducado.

    Se refresca un minuto antes de la hora, para que no caduque en mitad de una llamada.
    """
    guardado = sesion.get(CLAVE_TOKEN)
    if not guardado or not guardado.get("access_token"):
        raise ErrorSpotify("Conecta tu cuenta de Spotify para poder crear la playlist.")

    if time.time() < guardado.get("caduca_en", 0):
        return guardado["access_token"]

    refresco = guardado.get("refresh_token")
    if not refresco:
        olvidar(sesion)
        raise ErrorSpotify("Tu sesión de Spotify ha caducado. Vuelve a conectar tu cuenta.")

    datos = _pedir_token({"grant_type": "refresh_token", "refresh_token": refresco})
    _guardar(sesion, datos, refresco_anterior=refresco)
    return sesion[CLAVE_TOKEN]["access_token"]


def olvidar(sesion):
    """Desconecta la cuenta borrando el token de la sesión de esta aplicación.

    No revoca el permiso en Spotify: eso se hace desde la propia cuenta del usuario, y así
    se le indica en la interfaz.
    """
    sesion.pop(CLAVE_TOKEN, None)
    sesion.pop(CLAVE_ESTADO, None)


def perfil(token):
    """Identificador y nombre de la persona conectada. Es lo único que se consulta."""
    peticion = urllib.request.Request(PERFIL, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            datos = json.load(respuesta)
    except urllib.error.HTTPError as e:
        raise ErrorSpotify("No he podido leer tu cuenta de Spotify. Vuelve a conectarla.",
                           f"HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise ErrorSpotify("No he podido conectar con Spotify.", str(e)) from e
    return {"id": datos.get("id", ""), "nombre": datos.get("display_name") or datos.get("id", "")}
