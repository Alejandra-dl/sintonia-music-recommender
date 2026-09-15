# ============================================================
# Aplicación web de Sintonía.
#
# Esta interfaz está pensada para la persona que usa el producto:
# perfil musical, recomendaciones según su estado de ánimo y la
# posibilidad de llevarse esas recomendaciones a una playlist de
# su cuenta de Spotify. La evaluación, las métricas y el análisis
# del sistema viven en el dashboard de Streamlit (puerto 8502).
#
# Las recomendaciones se reparten a partes iguales entre música
# que la persona ya conoce y descubrimientos de artistas que no
# ha escuchado nunca. En pantalla se enseñan seis; la playlist
# lleva veinte, porque una lista se escucha y una pantalla se
# lee.
# ============================================================

import logging
import os
import secrets

import pandas as pd
from flask import (Flask, redirect, render_template, request, session, url_for)

from asistente import config
from asistente.datos.acceso import cargar
from asistente.recomendacion.animo import MAPEO_ANIMO
from asistente.recomendacion.recomendador import ORIGEN_CONOCIDA, Recomendador
from asistente.web import playlists, portadas, resumen, spotify_oauth
from asistente.web.spotify_oauth import ErrorSpotify

app = Flask(__name__)
# Sin CLAVE_SESION se genera una clave aleatoria por proceso (las sesiones no sobreviven a un reinicio).
app.secret_key = os.environ.get("CLAVE_SESION") or secrets.token_hex(32)
registro = logging.getLogger("sintonia")

# Metadatos exclusivamente visuales. Las claves son exactamente las que existen en
# MAPEO_ANIMO; aquí no se crea ningún estado nuevo ni se modifica el recomendador.
ANIMOS_UI = {
    "Fiesta": {"icono": "🎉", "texto": "Ritmo alto para salir, celebrar o animarte."},
    "Con energía": {"icono": "⚡", "texto": "Temas con empuje para ponerte en marcha."},
    "Para bailar": {"icono": "💃", "texto": "Una selección pensada para moverte."},
    "Tranquila": {"icono": "☁️", "texto": "Música más suave para bajar el ritmo."},
    "Romántica": {"icono": "❤️", "texto": "Canciones para un momento más íntimo."},
    "Nostálgica": {"icono": "🕰️", "texto": "Sonidos que conectan con otras épocas."},
}

MOMENTOS = {
    "manana": {"nombre": "Mañana", "hora": 10, "icono": "☀️"},
    "tarde": {"nombre": "Tarde", "hora": 18, "icono": "🌤️"},
    "noche": {"nombre": "Noche", "hora": 23, "icono": "🌙"},
}

# Claves con las que se guarda para la siguiente página el resultado de crear una
# playlist. Se leen una vez y se borran, para que no reaparezcan al recargar.
CLAVE_RESULTADO = "resultado_playlist"
CLAVE_ERROR = "error_playlist"

_recomendadores = {}


def preparar(usuario):
    """Carga historial y recomendador una única vez por usuario y proceso."""
    if usuario not in _recomendadores:
        datos = cargar(usuario=usuario)
        rec = Recomendador(
            usuario=usuario,
            reproducciones=datos["reproducciones"],
            tags=datos["tags"],
            candidatos=datos["candidatos"],
        )
        _recomendadores[usuario] = (rec, datos)
    return _recomendadores[usuario]


def usuario_actual():
    return session.get("usuario")


def _momento_valido(clave):
    return clave if clave in MOMENTOS else "tarde"


def _anio_valido(valor, disponibles):
    """El año pedido en la URL, sólo si ese usuario tiene datos de ese año.

    Cualquier otra cosa —vacío, «global», un año inventado o texto— cae en la vista
    global. Así la pantalla nunca se queda sin datos por un parámetro mal escrito.
    """
    try:
        anio = int(valor)
    except (TypeError, ValueError):
        return None
    return anio if anio in disponibles else None


# Cómo se reparte la lista entre música conocida y descubrimientos. El valor por
# defecto es el del proyecto, mitad y mitad; las otras dos opciones piden sólo una de
# las dos mitades. No son un modo nuevo del recomendador: es el parámetro `mezcla` que
# ya existe, con las tres posiciones que tienen sentido para una persona.
MEZCLAS = {
    "equilibrada": {"nombre": "Mitad y mitad", "valor": config.MEZCLA_CONOCIDAS},
    "conocidas": {"nombre": "Solo lo que ya conozco", "valor": 1.0},
    "nuevas": {"nombre": "Solo descubrimientos", "valor": 0.0},
}


def _mezcla_valida(clave):
    return clave if clave in MEZCLAS else "equilibrada"


def _vuelta_valida(valor):
    """Cuántas veces se ha pedido otra selección con los mismos filtros.

    Entra en la semilla del sorteo, así que basta con un número pequeño: se acota entre
    0 y 99 para que un valor disparatado en la URL no tenga ningún efecto raro. Cualquier
    cosa que no sea un número cae en 0, que es la selección del día.
    """
    try:
        return max(0, min(99, int(valor)))
    except (TypeError, ValueError):
        return 0


def _instante(momento):
    """Convierte el momento del día elegido en una fecha y hora concretas."""
    return pd.Timestamp.now(tz=config.ZONA_HORARIA).replace(
        hour=MOMENTOS[momento]["hora"], minute=0, second=0, microsecond=0)


def _explicacion_usuario(rec, fila, animo=None):
    """Explicación breve y no técnica para la interfaz de producto.

    No modifica el ranking ni la lógica del recomendador. Sólo traduce señales que ya
    están en la fila a lenguaje de usuario, sin probabilidades ni nombres internos.
    """
    encaja = (animo and pd.notna(fila.get("afinidad_animo"))
              and float(fila.get("afinidad_animo") or 0) > 0)

    if fila.get("origen") == ORIGEN_CONOCIDA:
        escuchas = fila.get("reproducciones_usuario")
        veces = (f" La has escuchado {int(escuchas)} veces."
                 if pd.notna(escuchas) and int(escuchas) > 1 else "")
        base = "Ya forma parte de tu historial." + veces
        if encaja:
            return f"{base} Encaja con el estado de ánimo que has elegido."
        return f"{base} Vuelve porque encaja con lo que sueles escuchar."

    semilla = fila.get("artista_semilla")
    if isinstance(semilla, str) and semilla.strip():
        base = f"Es un descubrimiento: se parece a {semilla}, que escuchas a menudo."
    else:
        base = "Es un descubrimiento basado en artistas relacionados con tus gustos."
    if encaja:
        return f"{base} Además encaja con cómo te sientes hoy."
    return f"{base} Es un artista que no aparece en tu historial."


def _recomendaciones(rec, animo, momento, cuantas, mezcla=None, vuelta=0):
    """Genera la lista y le añade la explicación en lenguaje de usuario."""
    lista = rec.recomendar(n=cuantas, animo=animo, momento=_instante(momento),
                           peso_animo=config.PESO_ANIMO,
                           mezcla=config.MEZCLA_CONOCIDAS if mezcla is None else mezcla,
                           max_por_artista=config.MAX_POR_ARTISTA,
                           variante=str(vuelta) if vuelta else "")
    filas = lista.to_dict("records")
    for fila in filas:
        fila["motivo_usuario"] = _explicacion_usuario(rec, fila, animo)
        fila["etiqueta_origen"] = ("Ya la conoces" if fila.get("origen") == ORIGEN_CONOCIDA
                                   else "Descubrimiento")
    return lista, filas


@app.route("/")
def entrada():
    if usuario_actual():
        return redirect(url_for("pantalla_inicio"))
    return render_template("entrada.html", usuarios=config.usuarios_disponibles())


@app.route("/entrar", methods=["POST"])
def entrar():
    elegido = request.form.get("usuario", "")
    if elegido in config.usuarios_disponibles():
        session["usuario"] = elegido
        return redirect(url_for("pantalla_inicio"))
    return redirect(url_for("entrada"))


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("entrada"))


@app.route("/inicio")
def pantalla_inicio():
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("entrada"))

    rec, _ = preparar(usuario)
    rep = rec.reproducciones
    ind = resumen.indicadores(rep)
    curiosos = resumen.datos_curiosos(rep)
    return render_template(
        "inicio_usuario.html",
        usuario=usuario,
        ind=ind,
        curioso=curiosos["principal"],
    )


@app.route("/perfil")
@app.route("/resumen")
def pantalla_resumen():
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("entrada"))

    rec, _ = preparar(usuario)
    rep = rec.reproducciones
    anios = resumen.anios_disponibles(rep)
    anio = _anio_valido(request.args.get("anio"), anios)
    canciones = resumen.top_canciones(rep, anio=anio)
    artistas = resumen.top_artistas(rep, anio=anio)

    return render_template(
        "resumen.html",
        usuario=usuario,
        anios=anios,
        anio=anio,
        ind=resumen.indicadores(rep, anio),
        curiosos=resumen.datos_curiosos(rep, anio),
        canciones=canciones,
        artistas=artistas,
        imagenes=portadas.de_canciones([c["spotify_track_uri"] for c in canciones]),
        color=portadas.color_de,
    )


@app.route("/animo")
def pantalla_animo():
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("entrada"))

    rec, _ = preparar(usuario)
    animo = request.args.get("animo")
    momento = _momento_valido(request.args.get("momento", "tarde"))
    mezcla = _mezcla_valida(request.args.get("mezcla", "equilibrada"))
    vuelta = _vuelta_valida(request.args.get("vuelta"))
    if animo not in MAPEO_ANIMO:
        animo = None

    recomendaciones, reparto = [], None
    if animo:
        lista, recomendaciones = _recomendaciones(rec, animo, momento,
                                                  config.RECOMENDACIONES_WEB,
                                                  MEZCLAS[mezcla]["valor"], vuelta)
        reparto = Recomendador.reparto(lista)

    return render_template(
        "animo.html",
        usuario=usuario,
        animos=list(MAPEO_ANIMO),
        animos_ui=ANIMOS_UI,
        animo=animo,
        momentos=MOMENTOS,
        momento=momento,
        mezclas=MEZCLAS,
        mezcla=mezcla,
        vuelta=vuelta,
        recomendaciones=recomendaciones,
        reparto=reparto,
        canciones_playlist=config.CANCIONES_PLAYLIST,
        spotify_disponible=spotify_oauth.hay_configuracion(),
        spotify_conectado=spotify_oauth.hay_sesion(session),
        resultado=session.pop(CLAVE_RESULTADO, None),
        error_playlist=session.pop(CLAVE_ERROR, None),
        imagenes=portadas.de_canciones(
            [r.get("spotify_track_uri") or "" for r in recomendaciones]
        ),
        color=portadas.color_de,
    )


# ---------------------------------------------------------------------------------
# Conexión de la cuenta de Spotify
# ---------------------------------------------------------------------------------
def _volver_a_animo():
    """Vuelve a la pantalla de recomendaciones conservando lo que había elegido."""
    animo = session.pop("animo_pendiente", None)
    momento = session.pop("momento_pendiente", "tarde")
    mezcla = session.pop("mezcla_pendiente", "equilibrada")
    vuelta = session.pop("vuelta_pendiente", 0)
    return redirect(url_for("pantalla_animo", animo=animo, momento=momento,
                            mezcla=mezcla, vuelta=vuelta))


@app.route("/spotify/conectar")
def spotify_conectar():
    if not usuario_actual():
        return redirect(url_for("entrada"))
    # Se recuerda qué estaba mirando para devolverlo al mismo sitio al volver.
    session["animo_pendiente"] = request.args.get("animo")
    session["momento_pendiente"] = _momento_valido(request.args.get("momento", "tarde"))
    session["mezcla_pendiente"] = _mezcla_valida(request.args.get("mezcla"))
    session["vuelta_pendiente"] = _vuelta_valida(request.args.get("vuelta"))
    try:
        return redirect(spotify_oauth.url_autorizacion(session))
    except ErrorSpotify as e:
        registro.warning("No se pudo iniciar la conexión con Spotify: %s", e.detalle or e)
        session[CLAVE_ERROR] = e.mensaje
        return _volver_a_animo()


@app.route("/spotify/callback")
def spotify_callback():
    """Vuelta desde Spotify. Aquí llega el código de un solo uso, o un error."""
    if not usuario_actual():
        return redirect(url_for("entrada"))

    if request.args.get("error"):
        # El caso más normal: la persona ha pulsado "Cancelar" en la pantalla de Spotify.
        session[CLAVE_ERROR] = ("No has autorizado el acceso a tu cuenta de Spotify, "
                                "así que no puedo crear playlists por ti.")
        return _volver_a_animo()

    try:
        spotify_oauth.canjear_codigo(session, request.args.get("code", ""),
                                     request.args.get("state", ""))
    except ErrorSpotify as e:
        registro.warning("Fallo al canjear el código de Spotify: %s", e.detalle or e)
        session[CLAVE_ERROR] = e.mensaje
    return _volver_a_animo()


@app.route("/spotify/desconectar")
def spotify_desconectar():
    spotify_oauth.olvidar(session)
    return redirect(url_for("pantalla_animo", animo=request.args.get("animo"),
                            momento=_momento_valido(request.args.get("momento", "tarde")),
                            mezcla=_mezcla_valida(request.args.get("mezcla")),
                            vuelta=_vuelta_valida(request.args.get("vuelta"))))


# ---------------------------------------------------------------------------------
# Creación de la playlist
# ---------------------------------------------------------------------------------
@app.route("/playlist", methods=["POST"])
def crear_playlist():
    """Crea la playlist. Sólo se ejecuta si la persona pulsa el botón: nunca sola."""
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("entrada"))

    animo = request.form.get("animo")
    momento = _momento_valido(request.form.get("momento", "tarde"))
    mezcla = _mezcla_valida(request.form.get("mezcla"))
    vuelta = _vuelta_valida(request.form.get("vuelta"))
    if animo not in MAPEO_ANIMO:
        session[CLAVE_ERROR] = "Elige antes cómo te sientes para poder crear la playlist."
        return redirect(url_for("pantalla_animo", momento=momento, mezcla=mezcla))

    if not spotify_oauth.hay_sesion(session):
        return redirect(url_for("spotify_conectar", animo=animo, momento=momento,
                                mezcla=mezcla, vuelta=vuelta))

    rec, _ = preparar(usuario)
    try:
        token = spotify_oauth.token_de_acceso(session)
        lista, _filas = _recomendaciones(rec, animo, momento,
                                         config.CANCIONES_PLAYLIST,
                                         MEZCLAS[mezcla]["valor"], vuelta)
        resultado = playlists.crear_desde_recomendaciones(token, lista, animo)
        resultado["pedidas"] = config.CANCIONES_PLAYLIST
        session[CLAVE_RESULTADO] = resultado
    except ErrorSpotify as e:
        registro.warning("No se pudo crear la playlist: %s", e.detalle or e)
        session[CLAVE_ERROR] = e.mensaje
    except Exception as e:                     # noqa: BLE001, cualquier fallo inesperado
        registro.exception("Error inesperado al crear la playlist: %s", e)
        session[CLAVE_ERROR] = ("Ha ocurrido un problema al crear la playlist. "
                                "Inténtalo de nuevo en unos minutos.")

    return redirect(url_for("pantalla_animo", animo=animo, momento=momento,
                            mezcla=mezcla))


# Compatibilidad con enlaces antiguos: la información técnica ya no forma parte de la
# aplicación de usuario. Quien necesite el análisis debe abrir el dashboard (8502).
@app.route("/sistema")
def pantalla_sistema():
    return redirect(url_for("pantalla_inicio"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501, debug=False)
