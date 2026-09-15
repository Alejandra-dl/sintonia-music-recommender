# ============================================================
# Descripción:
# Consigue las portadas de las canciones para la web.
#
# Last.fm ya no sirve imágenes de artista (devuelve siempre el
# mismo icono gris), así que la única fuente real es la API de
# Spotify. Se usa el modo aplicación (client id y secret), que no
# necesita que el usuario inicie sesión porque solo se piden
# datos públicos de canciones que ya están en el historial.
#
# Si no hay credenciales configuradas, la web sigue funcionando:
# las tarjetas se pintan con la inicial del artista sobre un
# color derivado de su nombre. Es deliberado, para que la
# aplicación no dependa de una API en mitad de una defensa.
#
# Se utiliza en:
# Las pantallas de resumen y de recomendaciones.
#
# Entrada:
# Una lista de identificadores de canción de Spotify.
#
# Salida:
# Un diccionario {id de canción: url de la portada}. Vacío si no
# hay credenciales.
# ============================================================

import base64
import json
import os
import urllib.parse
import urllib.request

from asistente import config
from asistente.etl.enriquecimiento import Cache

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

_cache = None
_token = None


def hay_credenciales():
    return bool(CLIENT_ID and CLIENT_SECRET)


def _abrir_cache():
    """La caché evita volver a pedir la misma portada en cada recarga."""
    global _cache
    if _cache is None:
        config.CATALOGO.mkdir(parents=True, exist_ok=True)
        _cache = Cache(config.CATALOGO / "portadas.sqlite")
    return _cache


def _pedir_token():
    """Token de aplicación de Spotify. Dura una hora; se pide una vez por proceso."""
    global _token
    if _token:
        return _token
    credenciales = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    peticion = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": f"Basic {credenciales}"})
    with urllib.request.urlopen(peticion, timeout=10) as r:
        _token = json.load(r)["access_token"]
    return _token


def _id(uri):
    """De 'spotify:track:1Kfrcx...' a '1Kfrcx...'."""
    return uri.rsplit(":", 1)[-1] if isinstance(uri, str) else ""


def de_canciones(uris):
    """Devuelve {uri: url de portada} para las canciones pedidas.

    Consulta primero la caché y pide a Spotify solo lo que falte, en bloques de 50,
    que es el máximo que admite la API en una sola llamada.
    """
    if not hay_credenciales():
        return {}

    cache = _abrir_cache()
    portadas, pendientes = {}, []
    for uri in uris:
        guardada = cache.get(f"portada:{uri}")
        if guardada is not None:
            portadas[uri] = guardada
        elif _id(uri):
            pendientes.append(uri)

    for i in range(0, len(pendientes), 50):
        bloque = pendientes[i:i + 50]
        ids = ",".join(_id(u) for u in bloque)
        peticion = urllib.request.Request(
            f"https://api.spotify.com/v1/tracks?ids={ids}",
            headers={"Authorization": f"Bearer {_pedir_token()}"})
        try:
            with urllib.request.urlopen(peticion, timeout=10) as r:
                datos = json.load(r)
        except Exception:
            break                      # sin conexión: se sigue con las iniciales

        for uri, cancion in zip(bloque, datos.get("tracks", [])):
            imagenes = (cancion or {}).get("album", {}).get("images", [])
            url = imagenes[-2]["url"] if len(imagenes) > 1 else (
                imagenes[0]["url"] if imagenes else "")
            cache.set(f"portada:{uri}", url)
            portadas[uri] = url

    return portadas


# Tonos de la paleta de la aplicación: verdes y azulados. Las tarjetas sin portada se
# pintan con uno de ellos para que no desentonen con el resto.
TONOS = [148, 160, 172, 186, 200, 214, 134, 168]


def color_de(nombre):
    """Color estable para las tarjetas sin portada, derivado del nombre.

    El mismo artista sale siempre del mismo color, lo que ayuda a reconocerlo de un
    vistazo aunque no haya imagen.
    """
    if not nombre:
        return "hsl(150 22% 26%)"
    return f"hsl({TONOS[sum(ord(c) for c in nombre) % len(TONOS)]} 26% 27%)"
