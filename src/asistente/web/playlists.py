# ============================================================
# Descripción:
# Convierte una lista de recomendaciones en una playlist dentro
# de la cuenta de Spotify del usuario.
#
# Tiene tres partes, y la primera es la que más trabajo da:
#
#   1. Conseguir el identificador de cada canción. Las canciones
#      conocidas ya lo traen del historial, porque Spotify lo
#      incluye en la descarga de portabilidad, así que no hay
#      que buscarlas. Las que vienen de Last.fm sólo tienen
#      título y artista y hay que buscarlas, comprobando que lo
#      encontrado es de verdad lo que se pedía.
#   2. Crear la playlist, privada salvo que se pida lo contrario.
#   3. Añadir las canciones, en bloques de cien, que es el
#      máximo que admite la API en una sola llamada.
#
# Si una canción no se encuentra no se detiene el proceso: se
# apunta y se informa al final. Una playlist con dieciocho
# canciones es mejor que un error.
#
# Se utiliza en:
# La ruta de creación de playlist de la aplicación Flask.
#
# Entrada:
# Un token de usuario válido y el DataFrame de recomendaciones.
#
# Salida:
# Un resumen con el nombre y la dirección de la playlist, cuántas
# canciones se añadieron de cada tipo y cuáles no se encontraron.
# ============================================================

import json
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

from asistente import config
from asistente.recomendacion.recomendador import ORIGEN_CONOCIDA, ORIGEN_DESCUBRIMIENTO
from asistente.web.spotify_oauth import ErrorSpotify

API = "https://api.spotify.com/v1"
MAXIMO_POR_LLAMADA = 100          # límite de la API al añadir canciones


# ---------------------------------------------------------------------------------
# Llamadas a la API
# ---------------------------------------------------------------------------------
def _llamar(metodo, url, token, cuerpo=None, reintentos=1):
    """Llamada a la API de Spotify con manejo de los errores que sí pueden ocurrir.

    El caso 429 es el límite de peticiones: Spotify indica en la cabecera cuántos
    segundos hay que esperar, y esperar es la única respuesta correcta.
    """
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(
        url, data=datos, method=metodo,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            texto = respuesta.read().decode("utf-8")
            return json.loads(texto) if texto else {}
    except urllib.error.HTTPError as e:
        if e.code == 429 and reintentos > 0:
            espera = int(e.headers.get("Retry-After", "2")) + 1
            time.sleep(min(espera, 30))
            return _llamar(metodo, url, token, cuerpo, reintentos - 1)
        cuerpo_error = e.read().decode("utf-8", "replace")[:300]
        if e.code == 401:
            raise ErrorSpotify("Tu sesión de Spotify ha caducado. Vuelve a conectar tu "
                               "cuenta y prueba otra vez.", f"HTTP 401: {cuerpo_error}") from e
        if e.code == 403:
            raise ErrorSpotify("Spotify no ha permitido crear la playlist con los permisos "
                               "concedidos. Vuelve a conectar la cuenta y acepta el permiso "
                               "para modificar playlists.", f"HTTP 403: {cuerpo_error}") from e
        if e.code == 429:
            raise ErrorSpotify("Spotify está limitando las peticiones ahora mismo. "
                               "Inténtalo de nuevo en unos minutos.", "HTTP 429") from e
        raise ErrorSpotify("Spotify ha devuelto un error al crear la playlist. Inténtalo "
                           "de nuevo en unos minutos.", f"HTTP {e.code}: {cuerpo_error}") from e
    except urllib.error.URLError as e:
        raise ErrorSpotify("No he podido conectar con Spotify. Comprueba tu conexión a "
                           "internet e inténtalo de nuevo.", str(e)) from e


# ---------------------------------------------------------------------------------
# Búsqueda de las canciones que no traen identificador
# ---------------------------------------------------------------------------------
def _sin_adornos(texto):
    """Deja un título o un nombre comparable: sin acentos, sin signos y en minúsculas.

    También quita lo que Spotify añade a los títulos y que Last.fm no tiene: los sufijos
    tipo "- Remastered 2011" y los paréntesis de "(feat. ...)". Sin esto, casi ninguna
    canción coincidiría aunque fuera la correcta.
    """
    texto = str(texto or "")
    for separador in (" - ", " – "):
        texto = texto.split(separador)[0]
    fuera, profundidad = [], 0
    for caracter in texto:
        if caracter in "([":
            profundidad += 1
        elif caracter in ")]":
            profundidad = max(0, profundidad - 1)
        elif profundidad == 0:
            fuera.append(caracter)
    texto = "".join(fuera)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = "".join(c if c.isalnum() or c.isspace() else " " for c in texto)
    return " ".join(texto.lower().split())


def _coincide(buscado, encontrado):
    """¿El texto encontrado se corresponde con el buscado?

    Se acepta la igualdad y que uno contenga al otro, que es lo que pasa cuando Spotify
    escribe "Rosalía, J Balvin" donde Last.fm escribe "Rosalía". No se acepta nada más:
    ante la duda es preferible saltarse la canción que meter otra distinta.
    """
    a, b = _sin_adornos(buscado), _sin_adornos(encontrado)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def buscar_cancion(token, artista, cancion):
    """Busca una canción en Spotify y devuelve su URI sólo si está segura de acertar.

    Se piden varios resultados en lugar de uno porque el primero no siempre es el bueno:
    puede ser una versión en directo de otro artista o una canción con el mismo título.
    Se recorre la lista y se devuelve el primero cuyo artista Y título coinciden.
    """
    consulta = f'track:{cancion} artist:{artista}'
    url = f"{API}/search?" + urllib.parse.urlencode(
        {"q": consulta, "type": "track", "limit": 10, "market": "ES"})
    datos = _llamar("GET", url, token)
    for pista in datos.get("tracks", {}).get("items", []):
        interpretes = [a.get("name", "") for a in pista.get("artists", [])]
        titulo_ok = _coincide(cancion, pista.get("name", ""))
        artista_ok = any(_coincide(artista, nombre) for nombre in interpretes)
        if titulo_ok and artista_ok:
            return pista.get("uri")
    return None


def resolver_uris(token, recomendaciones):
    """Devuelve la lista de URIs de las recomendaciones, y las que no se han podido.

    Las canciones conocidas salen del historial y ya traen su identificador, así que no se
    busca ninguna: además de ahorrar llamadas, evita el riesgo de acabar añadiendo una
    versión distinta de una canción que la persona ya tiene identificada.
    """
    uris, sin_encontrar, vistas = [], [], set()
    for _, fila in recomendaciones.iterrows():
        uri = fila.get("spotify_track_uri")
        if not (isinstance(uri, str) and uri.startswith("spotify:track:")):
            uri = buscar_cancion(token, fila.get("artista"), fila.get("cancion"))
        if not uri:
            sin_encontrar.append(f"{fila.get('cancion')} · {fila.get('artista')}")
            continue
        if uri in vistas:                     # la misma canción por dos caminos distintos
            continue
        vistas.add(uri)
        uris.append({"uri": uri, "origen": fila.get("origen")})
    return uris, sin_encontrar


# ---------------------------------------------------------------------------------
# Creación de la playlist
# ---------------------------------------------------------------------------------
def _nombre_y_descripcion(animo):
    nombre = f"{config.PLAYLIST_PREFIJO} · {animo}" if animo else config.PLAYLIST_PREFIJO
    descripcion = ("Generada a partir de tu historial de Spotify, de tus preferencias "
                   "musicales y del estado de ánimo que elegiste"
                   + (f": {animo}." if animo else "."))
    return nombre, descripcion


def crear_playlist(token, animo, publica=False):
    """Crea una playlist vacía en la cuenta del usuario y devuelve su id y su dirección."""
    nombre, descripcion = _nombre_y_descripcion(animo)
    creada = _llamar("POST", f"{API}/me/playlists", token,
                     {"name": nombre, "description": descripcion,
                      "public": bool(publica)})
    if not creada.get("id"):
        raise ErrorSpotify("Spotify no ha llegado a crear la playlist. Inténtalo otra vez.",
                           json.dumps(creada)[:300])
    return {"id": creada["id"],
            "nombre": creada.get("name", nombre),
            "url": (creada.get("external_urls") or {}).get("spotify", "")}


def anadir_canciones(token, playlist_id, uris):
    """Añade las canciones en bloques de cien y devuelve cuáles entraron y cuántas no.

    Si un bloque falla se apunta y se sigue con el siguiente: es preferible una playlist
    incompleta a ninguna, y al usuario se le dice cuántas entraron. Se devuelven las
    entradas concretas que se añadieron, no un recuento, para poder decir después cuántas
    eran conocidas y cuántas descubrimientos aunque falle un bloque intermedio.
    """
    anadidas, fallidas = [], 0
    for i in range(0, len(uris), MAXIMO_POR_LLAMADA):
        bloque = uris[i:i + MAXIMO_POR_LLAMADA]
        try:
            _llamar("POST", f"{API}/playlists/{playlist_id}/items", token,
                    {"uris": [u["uri"] for u in bloque]})
            anadidas.extend(bloque)
        except ErrorSpotify:
            fallidas += len(bloque)
    return anadidas, fallidas


def crear_desde_recomendaciones(token, recomendaciones, animo, publica=False):
    """Todo el proceso de una vez: resolver, crear y añadir.

    Devuelve un resumen con lo que hay que enseñar al usuario. No lanza excepción cuando
    faltan canciones: eso no es un fallo, es información.
    """
    if not len(recomendaciones):
        raise ErrorSpotify("No hay recomendaciones que añadir a una playlist.")

    uris, sin_encontrar = resolver_uris(token, recomendaciones)
    if not uris:
        raise ErrorSpotify("No he podido encontrar en Spotify ninguna de las canciones "
                           "recomendadas, así que no he creado la playlist.")

    playlist = crear_playlist(token, animo, publica)
    anadidas, fallidas = anadir_canciones(token, playlist["id"], uris)

    conocidas = sum(1 for u in anadidas if u["origen"] == ORIGEN_CONOCIDA)
    descubrimientos = sum(1 for u in anadidas if u["origen"] == ORIGEN_DESCUBRIMIENTO)
    pedidas = pd.Series(recomendaciones.get("origen", [])).value_counts()

    return {
        "nombre": playlist["nombre"],
        "url": playlist["url"],
        "anadidas": len(anadidas),
        "conocidas": conocidas,
        "descubrimientos": descubrimientos,
        # Se guardan unas pocas: esta lista viaja en la cookie de sesión hasta la
        # siguiente página, y el usuario sólo necesita ver un ejemplo, no el inventario.
        "no_encontradas": sin_encontrar[:8],
        "total_no_encontradas": len(sin_encontrar),
        "no_anadidas": fallidas,
        "equilibrada": (int(pedidas.get(ORIGEN_CONOCIDA, 0))
                        == int(pedidas.get(ORIGEN_DESCUBRIMIENTO, 0))),
        "animo": animo,
    }
