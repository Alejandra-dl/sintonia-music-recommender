# ============================================================
# Descripción:
# Enriquecimiento con MusicBrainz y Last.fm. Hace dos cosas
# distintas y conviene no confundirlas:
#
#   1. Añade a cada artista sus etiquetas de género. Eso va al
#      catálogo compartido, porque describe artistas y no
#      personas, y lo aprovechan todos los usuarios.
#   2. Genera la reserva de canciones candidatas de UN usuario,
#      a partir de artistas parecidos a los que él escucha y
#      excluyendo los que ya conoce. Eso es personal y va a su
#      carpeta.
#
# Que el catálogo sea compartido es lo que hace viable el
# sistema con varios usuarios: la parte cara solo se paga una
# vez y cada usuario nuevo únicamente obliga a consultar los
# artistas que nadie había pedido antes.
#
# Las dos APIs son gratuitas y limitan las peticiones por
# segundo, así que las respuestas se guardan en una caché
# SQLite y el proceso se puede parar y retomar.
#
# Se utiliza en:
# Segundo paso del pipeline, después del ETL.
#
# Entrada:
# El historial ya procesado del usuario y una clave de Last.fm.
#
# Salida:
# tags_artistas.parquet, artistas_info.parquet, catalogo_info.json e
# informe_cobertura_<usuario>.md en el catálogo compartido, y
# candidatos.parquet en la carpeta del usuario.
#
# Uso:
#   python -m asistente.etl.enriquecimiento --usuario usuario1 \
#          --piloto 200
# ============================================================

import argparse
import json
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

from asistente import config
from asistente.utilidades.io_datos import guardar as guardar_tabla, leer as leer_tabla

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/"
USER_AGENT = "TFM-AsistenteMusical/1.0 (proyecto academico; contacto en la memoria)"

# Etiquetas de Last.fm que describen estado de ánimo o situación, no género.
# Se usan para el mapeo de la pantalla "¿Cómo te sientes hoy?".
TAGS_DE_ANIMO = {
    "happy", "sad", "chill", "chillout", "relax", "relaxing", "party", "energetic",
    "melancholy", "melancholic", "romantic", "love", "dark", "dreamy", "upbeat",
    "mellow", "aggressive", "calm", "feel good", "summer", "nostalgia", "workout",
    "sexy", "sensual", "emotional", "angry", "hopeful", "peaceful",
}

# ---------------------------------------------------------------------------------
# Caché
# ---------------------------------------------------------------------------------
class Cache:
    """Caché en disco de respuestas de API. Hace el proceso reanudable.

    La conexión se abre con `check_same_thread=False` y todas las consultas pasan por un
    cerrojo. El motivo es la aplicación web: sirve cada petición en un hilo distinto,
    mientras que la caché se abre una sola vez y se reutiliza, de modo que con la
    comprobación por defecto de SQLite la segunda petición fallaba con
    ProgrammingError. El cerrojo es lo que permite quitar esa comprobación sin que dos
    hilos escriban a la vez. En el ETL, que es de un solo hilo, no cuesta nada.
    """

    def __init__(self, ruta):
        self.con = sqlite3.connect(ruta, check_same_thread=False)
        self._cerrojo = threading.Lock()
        with self._cerrojo:
            self.con.execute(
                "CREATE TABLE IF NOT EXISTS cache (clave TEXT PRIMARY KEY, valor TEXT)")
            self.con.commit()

    def get(self, clave):
        with self._cerrojo:
            fila = self.con.execute(
                "SELECT valor FROM cache WHERE clave = ?", (clave,)).fetchone()
        return json.loads(fila[0]) if fila else None

    def set(self, clave, valor):
        with self._cerrojo:
            self.con.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)",
                             (clave, json.dumps(valor)))
            self.con.commit()

    def cerrar(self):
        with self._cerrojo:
            self.con.close()

# ---------------------------------------------------------------------------------
# Clientes de las APIs
# ---------------------------------------------------------------------------------
def _peticion(url, intentos = 3, espera = 2.0):
    """GET con reintentos. Devuelve el JSON o None si la petición falla del todo."""
    for intento in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError) as e:
            if intento == intentos - 1:
                print(f"  [fallo] {type(e).__name__} en {url[:70]}…", file=sys.stderr)
                return None
            time.sleep(espera * (intento + 1))
    return None

class ClienteLastfm:
    def __init__(self, api_key, cache, base_url = LASTFM_URL,
                 pausa = 0.22):
        self.api_key, self.cache, self.base_url, self.pausa = api_key, cache, base_url, pausa

    def _llamar(self, metodo, **params):
        clave = f"lastfm:{metodo}:{json.dumps(params, sort_keys=True)}"
        guardado = self.cache.get(clave)
        if guardado is not None:
            return guardado
        params.update(method=metodo, api_key=self.api_key, format="json")
        datos = _peticion(self.base_url + "?" + urllib.parse.urlencode(params)) or {}
        self.cache.set(clave, datos)
        time.sleep(self.pausa)
        return datos

    def etiquetas(self, artista):
        d = self._llamar("artist.getTopTags", artist=artista, autocorrect=1)
        return [{"tag": t["name"].lower().strip(), "peso": int(t.get("count", 0))}
                for t in d.get("toptags", {}).get("tag", []) if int(t.get("count", 0)) > 0]

    def informacion(self, artista):
        d = self._llamar("artist.getInfo", artist=artista, autocorrect=1).get("artist", {})
        est = d.get("stats", {})
        return {"nombre_lastfm": d.get("name"), "mbid_lastfm": d.get("mbid") or None,
                "oyentes": int(est.get("listeners", 0) or 0),
                "reproducciones_globales": int(est.get("playcount", 0) or 0)}

    def similares(self, artista, limite = 20):
        d = self._llamar("artist.getSimilar", artist=artista, autocorrect=1, limit=limite)
        return [{"artista_similar": a["name"], "similitud": float(a.get("match", 0) or 0)}
                for a in d.get("similarartists", {}).get("artist", [])]

    def canciones_top(self, artista, limite = 10):
        d = self._llamar("artist.getTopTracks", artist=artista, autocorrect=1, limit=limite)
        return [{"cancion": t["name"],
                 "reproducciones_globales": int(t.get("playcount", 0) or 0)}
                for t in d.get("toptracks", {}).get("track", [])]

class ClienteMusicBrainz:
    """MusicBrainz limita a 1 petición por segundo: la pausa NO es opcional."""

    def __init__(self, cache, base_url = MUSICBRAINZ_URL, pausa = 1.1):
        self.cache, self.base_url, self.pausa = cache, base_url, pausa

    def buscar_artista(self, artista):
        clave = f"mb:artist:{artista.lower()}"
        guardado = self.cache.get(clave)
        if guardado is not None:
            return guardado
        consulta = urllib.parse.urlencode(
            {"query": f'artist:"{artista}"', "fmt": "json", "limit": 1})
        datos = _peticion(f"{self.base_url}artist/?{consulta}") or {}
        lista = datos.get("artists", [])
        resultado = {}
        if lista:
            a = lista[0]
            resultado = {
                "mbid": a.get("id"),
                "puntuacion": a.get("score", 0),
                "pais": a.get("country"),
                "tags_mb": [t["name"].lower().strip() for t in a.get("tags", [])],
            }
        self.cache.set(clave, resultado)
        time.sleep(self.pausa)
        return resultado

# ---------------------------------------------------------------------------------
# Proceso
# ---------------------------------------------------------------------------------
def artistas_del_historial(ruta_parquet):
    rep = leer_tabla(ruta_parquet)
    col = "master_metadata_album_artist_name"
    return rep[col].value_counts()

def enriquecer_artistas(artistas, lastfm,
                        musicbrainz, verbose = True):
    filas_tags, filas_info = [], []
    total = len(artistas)
    for i, (artista, escuchas) in enumerate(artistas.items(), 1):
        if verbose and (i % 25 == 0 or i == total):
            print(f"  {i}/{total} artistas…", flush=True)
        etiquetas = lastfm.etiquetas(artista)
        for t in etiquetas:
            filas_tags.append({"artista": artista, "tag": t["tag"], "peso": t["peso"],
                               "fuente": "lastfm"})
        mb = musicbrainz.buscar_artista(artista)
        for t in mb.get("tags_mb", []):
            filas_tags.append({"artista": artista, "tag": t, "peso": 50, "fuente": "musicbrainz"})
        info = lastfm.informacion(artista)
        filas_info.append({"artista": artista, "escuchas_usuaria": int(escuchas),
                           "mbid": mb.get("mbid"), "pais": mb.get("pais"),
                           "n_tags_lastfm": len(etiquetas),
                           "n_tags_musicbrainz": len(mb.get("tags_mb", [])), **info})
    return pd.DataFrame(filas_tags), pd.DataFrame(filas_info)

def generar_candidatos(artistas_semilla, escuchados,
                       lastfm, por_artista = 5,
                       similares_por_semilla = 15, verbose = True):
    """Canciones de artistas SIMILARES a los que escucha, que ella no ha escuchado.

    Es la reserva de la pantalla "Descubrir": el modelo puntúa esto, no lo genera.
    """
    filas = []
    for i, semilla in enumerate(artistas_semilla, 1):
        if verbose:
            print(f"  candidatos {i}/{len(artistas_semilla)} · a partir de {semilla}", flush=True)
        for similar in lastfm.similares(semilla, similares_por_semilla):
            nombre = similar["artista_similar"]
            if nombre in escuchados:
                continue                      # ya la escucha: no es un descubrimiento
            for tema in lastfm.canciones_top(nombre, por_artista):
                filas.append({"artista": nombre, "cancion": tema["cancion"],
                              "reproducciones_globales": tema["reproducciones_globales"],
                              "artista_semilla": semilla, "similitud": similar["similitud"]})
    if not filas:
        return pd.DataFrame(columns=["artista", "cancion", "reproducciones_globales",
                                     "artista_semilla", "similitud"])
    cand = pd.DataFrame(filas)
    # Un artista candidato puede salir de varias semillas: nos quedamos con la mejor
    cand = (cand.sort_values("similitud", ascending=False)
                .drop_duplicates(subset=["artista", "cancion"], keep="first"))
    return cand.reset_index(drop=True)

def _bloque_historial(todos, con_etiquetas):
    """Texto con la cobertura medida sobre el historial entero, no solo sobre lo consultado.

    Sin esta distinción los dos números se confunden: se puede tener un 99 % de acierto en
    las consultas y a la vez cubrir la mitad del historial, simplemente porque no se ha
    preguntado por el resto. Son las dos caras y las dos hacen falta.
    """
    if todos is None or not len(todos):
        return "(no disponible: no se ha pasado el historial completo)\n"
    cubiertos = todos.index.isin(con_etiquetas)
    return (f"| Medida | Valor |\n|---|---|\n"
            f"| Artistas del historial | {len(todos):,} |\n"
            f"| Artistas con etiquetas | {cubiertos.sum():,} "
            f"({cubiertos.sum() / len(todos) * 100:.1f} %) |\n"
            f"| Escuchas cubiertas | {todos[cubiertos].sum():,} de {todos.sum():,} "
            f"({todos[cubiertos].sum() / todos.sum() * 100:.1f} %) |\n")

def fundir(nuevo, ruta, claves):
    """Funde lo recién consultado con lo que ya hubiera en el catálogo.

    El catálogo describe artistas, no personas, así que lo comparten todos los usuarios y
    tiene que crecer con cada alta en lugar de reemplazarse. Ante un artista repetido gana
    la consulta más reciente.
    """
    if not ruta.exists():
        return nuevo
    anterior = leer_tabla(ruta)
    if not len(anterior):
        return nuevo
    if not len(nuevo):
        return anterior
    columnas = [c for c in claves if c in anterior.columns and c in nuevo.columns]
    junto = pd.concat([anterior, nuevo], ignore_index=True)
    if columnas:
        junto = junto.drop_duplicates(subset=columnas, keep="last")
    print(f"Catálogo {ruta.name}: {len(anterior):,} filas previas + {len(nuevo):,} "
          f"nuevas → {len(junto):,}")
    return junto.reset_index(drop=True)


def anotar_catalogo(outdir, tags, info, usuario):
    """Deja constancia de cuándo y por qué cambió el catálogo compartido.

    El catálogo entra en las variables de contenido del modelo, y crece con cada alta. Sin
    esta nota no se puede saber con qué estado del catálogo se obtuvo un resultado, que es
    lo que hace falta para explicar por qué dos ejecuciones separadas en el tiempo dan
    cifras ligeramente distintas.
    """
    ruta = outdir / "catalogo_info.json"
    historial = []
    if ruta.exists():
        try:
            historial = json.loads(ruta.read_text(encoding="utf-8")).get("historial", [])
        except (json.JSONDecodeError, AttributeError):
            historial = []
    historial.append({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                      "usuario": usuario,
                      "filas_etiquetas": int(len(tags)),
                      "artistas_con_etiquetas": int(tags.artista.nunique()) if len(tags) else 0,
                      "artistas_info": int(len(info))})
    ruta.write_text(json.dumps({"descripcion": "Estado del catálogo compartido tras cada "
                                               "enriquecimiento. La última entrada es el "
                                               "estado actual.",
                                "historial": historial}, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def informe_cobertura(artistas, tags, info,
                      candidatos, ruta,
                      todos = None):
    escuchas_totales = artistas.sum()
    # Importante: las etiquetas incluyen también artistas candidatos, que no forman
    # parte del historial. La cobertura solo tiene sentido sobre los artistas
    # consultados, así que se limita a ellos. Sin esta intersección los porcentajes
    # pueden superar el 100 %.
    consultados = set(artistas.index)
    con_lastfm = set(tags[tags.fuente == "lastfm"].artista) & consultados
    con_mb = set(tags[tags.fuente == "musicbrainz"].artista) & consultados
    con_alguna = con_lastfm | con_mb
    con_animo = set(tags[tags.tag.isin(TAGS_DE_ANIMO)].artista) & consultados

    def pct_artistas(s): return len(s) / len(artistas) * 100 if len(artistas) else 0
    def pct_escuchas(s): return artistas[artistas.index.isin(s)].sum() / escuchas_totales * 100

    md = f"""# Informe de cobertura de fuentes externas

 Artistas consultados: **{len(artistas):,}**
(que suman {escuchas_totales:,} reproducciones del historial)

La cobertura se mide de dos formas, y la segunda es la que importa: da igual quedarse
sin etiquetas de un artista que escuchó una vez; lo grave es quedarse sin las de los
artistas que copan sus escuchas.

| Fuente | % de artistas | % de escuchas cubiertas |
|---|---|---|
| Last.fm (etiquetas) | {pct_artistas(con_lastfm):.1f} % | {pct_escuchas(con_lastfm):.1f} % |
| MusicBrainz (géneros) | {pct_artistas(con_mb):.1f} % | {pct_escuchas(con_mb):.1f} % |
| **Alguna de las dos** | **{pct_artistas(con_alguna):.1f} %** | **{pct_escuchas(con_alguna):.1f} %** |
| Con etiquetas de estado de ánimo | {pct_artistas(con_animo):.1f} % | {pct_escuchas(con_animo):.1f} % |

## Cobertura sobre el historial completo

La tabla anterior mide si las APIs contestaron a lo que se les preguntó. Esta mide otra
cosa distinta y también necesaria: qué parte del historial entero queda cubierta, contando
también los artistas a los que no se ha preguntado. Es el número que ve la aplicación.

{_bloque_historial(todos, con_alguna)}
## Etiquetas obtenidas
- Filas de etiquetas: {len(tags):,}
- Etiquetas distintas: {tags.tag.nunique():,}
- Artistas con MBID de MusicBrainz: {info.mbid.notna().sum():,} de {len(info):,}

### Las 25 etiquetas más frecuentes
{tags.tag.value_counts().head(25).to_frame('artistas').to_markdown()}

## Reserva de candidatos
- Canciones candidatas generadas: **{len(candidatos):,}**
- Artistas candidatos distintos: {candidatos.artista.nunique() if len(candidatos) else 0:,}

## Etiquetas de estado de ánimo

Las etiquetas de ánimo ("chill", "party", "sad") son mucho menos frecuentes a nivel de
artista que las de género, porque la comunidad de Last.fm etiqueta sobre todo el estilo.
Si la cobertura de ánimo es baja, el mapeo de la pantalla de estado de ánimo debe
construirse sobre géneros, que es la alternativa prevista en la planificación.

## Decisión GO / NO-GO
Criterio fijado en el roadmap antes de ver los datos: si la cobertura sobre las
**escuchas de los artistas consultados** supera el 80 %, las fuentes externas sirven y el
modelo de contenido y el mapeo de ánimo son viables.
Cobertura obtenida: **{pct_escuchas(con_alguna):.1f} %** → {"**GO**" if pct_escuchas(con_alguna) >= 80 else "**revisar**: cobertura insuficiente, simplificar el mapeo de ánimo a género"}

El criterio se evalúa sobre lo consultado a propósito: es lo que decide si las fuentes
externas son utilizables. Que el historial entero quede cubierto depende de a cuántos
artistas se pregunte, y eso se resuelve ejecutando el enriquecimiento completo, no
cambiando de fuente.
"""
    ruta.write_text(md, encoding="utf-8")
    return md

def cargar_en_mongo(uri, base, tags, info, candidatos, usuario):
    """Sube el catálogo compartido y los candidatos de este usuario.

    Las dos colecciones del catálogo se reescriben enteras porque son comunes. Los
    candidatos llevan user_id y solo se borran los de este usuario, para no tirar los de
    los demás.
    """
    from pymongo import MongoClient
    db = MongoClient(uri)[base]

    for nombre, df in [("tags_artistas", tags), ("artistas_info", info)]:
        db[nombre].delete_many({})
        if len(df):
            db[nombre].insert_many(df.to_dict("records"))

    db["candidatos"].delete_many({"user_id": usuario})
    if len(candidatos):
        db["candidatos"].insert_many(candidatos.assign(user_id=usuario).to_dict("records"))

    db["tags_artistas"].create_index([("artista", 1)])
    db["candidatos"].create_index([("user_id", 1), ("artista", 1)])
    return {"tags_artistas": db["tags_artistas"].count_documents({}),
            "artistas_info": db["artistas_info"].count_documents({}),
            "candidatos": db["candidatos"].count_documents({"user_id": usuario})}

def main():
    ap = argparse.ArgumentParser(description="Enriquecimiento con MusicBrainz y Last.fm")
    ap.add_argument("--usuario", default=config.USUARIO,
                    help="identificador del usuario: usuario1, usuario2...")
    ap.add_argument("--input", default=None,
                    help="fichero de reproducciones (por defecto, el del usuario)")
    ap.add_argument("--outdir", default=str(config.CATALOGO))
    ap.add_argument("--api-key", default=config.LASTFM_API_KEY or None,
                    help="clave de Last.fm (o variable de entorno LASTFM_API_KEY)")
    ap.add_argument("--piloto", type=int, default=0,
                    help="solo los N artistas más escuchados (prueba de cobertura rápida)")
    ap.add_argument("--min-escuchas", type=int, default=3,
                    help="ignorar artistas con menos escuchas que esto")
    ap.add_argument("--semillas", type=int, default=40,
                    help="artistas top usados para generar candidatos")
    ap.add_argument("--sin-candidatos", action="store_true")
    ap.add_argument("--mongo-uri", default=None)
    ap.add_argument("--mongo-db", default=config.MONGO_DB)
    ap.add_argument("--lastfm-url", default=LASTFM_URL, help="(para pruebas)")
    ap.add_argument("--musicbrainz-url", default=MUSICBRAINZ_URL, help="(para pruebas)")
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("Falta la clave de Last.fm: --api-key o variable LASTFM_API_KEY.\n"
                 "Se saca gratis en https://www.last.fm/api/account/create")

    usuario = args.usuario
    config.crear_carpetas(usuario)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    cache = Cache(outdir / "cache_apis.sqlite")
    lastfm = ClienteLastfm(args.api_key, cache, args.lastfm_url)
    musicbrainz = ClienteMusicBrainz(cache, args.musicbrainz_url)

    entrada = Path(args.input) if args.input else config.reproducciones(usuario)
    todos = artistas_del_historial(entrada)
    artistas = todos[todos >= args.min_escuchas]
    if args.piloto:
        artistas = artistas.head(args.piloto)
    print(f"Artistas a consultar: {len(artistas):,} de {len(todos):,} del historial")

    tags, info = enriquecer_artistas(artistas, lastfm, musicbrainz)

    candidatos = pd.DataFrame()
    if not args.sin_candidatos:
        print("Generando reserva de candidatos…")
        candidatos = generar_candidatos(list(artistas.head(args.semillas).index),
                                        set(todos.index), lastfm)
        # Los artistas candidatos también necesitan etiquetas: sin ellas, la pantalla
        # de estado de ánimo no puede filtrarlos y el modelo de contenido los ignora.
        nuevos = sorted(set(candidatos.artista) - set(tags.artista)) if len(candidatos) else []
        if nuevos:
            print(f"Etiquetando {len(nuevos):,} artistas candidatos…")
            tags_cand, info_cand = enriquecer_artistas(
                pd.Series(0, index=nuevos), lastfm, musicbrainz)
            tags = pd.concat([tags, tags_cand], ignore_index=True)
            info = pd.concat([info, info_cand.assign(es_candidato=True)], ignore_index=True)

    # El catálogo es compartido y se ACUMULA: lo que se acaba de consultar se funde con
    # lo que ya había. Si se sobrescribiera, dar de alta a un usuario nuevo borraría las
    # etiquetas de los anteriores, y con ellas su modelo de contenido.
    # El informe describe la cobertura del historial de UN usuario y se calcula con lo que
    # se ha consultado para él, ANTES de fundirlo con el catálogo compartido: así los
    # recuentos de etiquetas son los suyos y no los de todo el catálogo. Lleva su nombre
    # para que el de otro usuario no lo pise.
    ruta_informe = (config.informe_cobertura(usuario) if outdir == config.CATALOGO
                    else outdir / config.informe_cobertura(usuario).name)
    informe_cobertura(artistas, tags, info, candidatos, ruta_informe, todos=todos)

    tags = fundir(tags, outdir / "tags_artistas.parquet", ["artista", "tag", "fuente"])
    info = fundir(info, outdir / "artistas_info.parquet", ["artista"])
    guardar_tabla(tags, outdir / "tags_artistas.parquet")
    guardar_tabla(info, outdir / "artistas_info.parquet")
    anotar_catalogo(outdir, tags, info, usuario)
    # Los candidatos son de este usuario, no del catálogo compartido
    if len(candidatos):
        guardar_tabla(candidatos, config.candidatos(usuario))

    print(f"\nOK · catálogo con {len(tags):,} etiquetas de {tags.artista.nunique():,} artistas · "
          f"{len(candidatos):,} candidatos para {usuario}")
    print(f"Informe de cobertura → {ruta_informe}")

    if args.mongo_uri:
        conteos = cargar_en_mongo(args.mongo_uri, args.mongo_db, tags, info,
                                  candidatos, usuario)
        print(f"MongoDB · {conteos}")
    cache.cerrar()

if __name__ == "__main__":
    main()
