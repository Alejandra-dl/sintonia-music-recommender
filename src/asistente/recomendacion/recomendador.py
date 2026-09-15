# ============================================================
# Descripción:
# Motor de recomendación. Construye DOS listas independientes y
# las mezcla al final a partes iguales:
#
#   1. Canciones CONOCIDAS: temas que ya están en el historial
#      del usuario. Se puntúan con su modelo de afinidad y se
#      desempatan por veces escuchadas y por recencia.
#   2. DESCUBRIMIENTOS: canciones de artistas que el usuario no
#      ha escuchado nunca, generadas durante el enriquecimiento
#      a partir de artistas parecidos a los suyos (Last.fm).
#
# De cada ranking se toman las mejores, con una ventana de
# renovación opcional (config.DIVERSIDAD) que sortea entre ellas
# usando la fecha como semilla, para que la lista no sea siempre
# idéntica. Los dos grupos se ordenan por separado y sólo al final
# se toma la mitad de cada uno. Hacerlo así, y no filtrando una lista
# única, es lo que garantiza la proporción: las variables del
# modelo dependen sobre todo del artista, y como las canciones
# conocidas tienen escuchas previas y las nuevas no, un ranking
# único quedaría copado por las conocidas.
#
# Se utiliza en:
# La recomendación por estado de ánimo de la aplicación Flask, la
# creación de playlists en Spotify y los análisis del dashboard.
#
# Entrada:
# El historial del usuario, las etiquetas del catálogo, sus
# canciones candidatas y su modelo entrenado.
#
# Salida:
# Un DataFrame de recomendaciones ordenadas, cada una con su
# posición, su puntuación, su origen ("conocida" o
# "descubrimiento") y su explicación en texto.
# ============================================================

import pickle
import zlib

import numpy as np
import pandas as pd

from asistente import config
from asistente.modelado import caracteristicas as ca
from asistente.recomendacion.animo import MAPEO_ANIMO
from asistente.utilidades import io_datos

# Columnas que devuelven los dos catálogos. Tenerlas iguales permite puntuarlos con el
# mismo código y concatenarlos al final sin sorpresas. Las que no aplican a un grupo van
# vacías: una canción nueva no tiene reproducciones del usuario, y una conocida no tiene
# artista semilla.
COLUMNAS_CATALOGO = ["spotify_track_uri", "cancion", "artista",
                     "reproducciones_usuario", "ultima_escucha",
                     "reproducciones_globales", "artista_semilla", "similitud"]

ORIGEN_CONOCIDA = "conocida"
ORIGEN_DESCUBRIMIENTO = "descubrimiento"


def _texto_normalizado(nombre):
    """Nombre de artista o canción en minúsculas y sin espacios sobrantes.

    Se usa sólo para comparar con el historial. Last.fm aplica autocorrección y puede
    devolver el mismo artista escrito de otra forma, así que comparar el texto tal cual
    dejaría pasar artistas ya escuchados.
    """
    return str(nombre).strip().lower() if nombre is not None else ""


def _semilla(*partes):
    """Semilla reproducible a partir de texto.

    Se usa CRC32 y no la función `hash` de Python porque `hash` cambia entre ejecuciones
    (aleatorización de cadenas), y aquí hace falta lo contrario: que la misma consulta el
    mismo día devuelva siempre la misma lista, para que la aplicación no baraje las
    canciones cada vez que se recarga la página y para que el experimento se pueda repetir.
    """
    return zlib.crc32("|".join(str(x) for x in partes).encode("utf-8"))


class Recomendador:
    """Carga el modelo y los datos una sola vez y responde consultas."""

    def __init__(self, usuario=config.USUARIO,
                 ruta_modelo=None,
                 reproducciones=None,
                 tags=None,
                 candidatos=None):
        """Prepara el recomendador de un usuario concreto.

        Los tres DataFrames se pueden pasar ya cargados, que es lo que hace la aplicación
        cuando los ha leído de MongoDB. Si no se pasan, se leen de los ficheros de ese
        usuario. El modelo es siempre el suyo: está entrenado con su historial y no sirve
        para otra persona.
        """
        self.usuario = usuario
        with open(ruta_modelo or config.modelo_afinidad(usuario), "rb") as fh:
            paquete = pickle.load(fh)
        self.modelo = paquete["modelo"]
        self.columnas = paquete["columnas"]
        self.metricas = paquete.get("metricas_prueba", [])
        self.definicion = paquete.get("definicion_objetivo", {})

        self.reproducciones = (self._normalizar_historial(reproducciones)
                               if reproducciones is not None
                               else self._cargar_reproducciones())
        self.tags = tags if tags is not None else self._cargar_opcional(config.TAGS_ARTISTAS)
        self.candidatos = (candidatos if candidatos is not None
                           else self._cargar_opcional(config.candidatos(usuario)))
        self.info_artistas = self._cargar_opcional(config.ARTISTAS_INFO)

        self.escuchas_por_artista = self.reproducciones.artista.value_counts()
        self.perfil_tags = (ca.perfil_de_tags(self.reproducciones, self.tags)
                            if self.tags is not None else pd.Series(dtype=float))
        self._preparar_caches()

    # -- carga -------------------------------------------------------------------
    @staticmethod
    def _normalizar_historial(rep):
        """Deja el historial con los nombres de columna que usa el resto del código."""
        rep = rep.copy()
        if not pd.api.types.is_datetime64_any_dtype(rep["ts"]):
            rep["ts"] = pd.to_datetime(rep["ts"], utc=True)
        if rep["ts"].dt.tz is None:
            rep["ts"] = rep["ts"].dt.tz_localize("UTC")
        rep["ts_local"] = rep["ts"].dt.tz_convert(config.ZONA_HORARIA)
        rep["artista"] = rep["master_metadata_album_artist_name"]
        rep["cancion"] = rep["master_metadata_track_name"]
        return rep.sort_values("ts_local").reset_index(drop=True)

    def _cargar_reproducciones(self):
        return self._normalizar_historial(io_datos.leer(config.reproducciones(self.usuario)))

    @staticmethod
    def _cargar_opcional(ruta):
        return io_datos.leer(ruta) if io_datos.existe(ruta) else None

    def _preparar_caches(self):
        """Prepara lo que se reutiliza en cada consulta, para no recalcularlo.

        La afinidad de etiquetas depende sólo del artista y del perfil del usuario, que no
        cambian entre consultas. Guardarla evita recalcular un coseno por cada canción del
        historial cada vez que alguien pide una recomendación.
        """
        self._tags_por_artista = (dict(tuple(self.tags.groupby("artista")))
                                  if self.tags is not None and len(self.tags) else {})
        self._sin_tags = pd.DataFrame(columns=["tag", "peso"])
        self._afinidad_cache = {}
        self._animo_cache = {}
        self._conocidas = None                       # catálogo de conocidas, se crea al pedirlo

        # Resumen del historial por artista. No depende del momento en que se pida la
        # recomendación, así que se calcula una vez por usuario en lugar de recorrer las
        # ciento cincuenta mil reproducciones en cada consulta.
        rep = self.reproducciones
        self._historial_artista = rep.groupby("artista").agg(
            escuchas=("ts_local", "size"), canciones=("spotify_track_uri", "nunique"),
            ultima=("ts_local", "max"), skip=("es_skip", "mean"),
            larga=("segundos", lambda s: (s >= ca.SEG_ESCUCHA_VALIDA).mean()))

        # Actividad reciente: las mismas dos cifras para todos los candidatos de una
        # consulta, porque describen al usuario y no a la canción. La ventana se ancla al
        # último dato del historial, no a la fecha de hoy: la descarga de portabilidad es
        # una foto fija y, si se anclara al presente, estas variables valdrían cero en
        # cuanto el fichero tuviera más de un mes.
        fin = rep.ts_local.max()
        inicio = fin - pd.Timedelta(days=30)
        primeras = rep.groupby("spotify_track_uri").ts_local.min()
        self._actividad_30d = int(((rep.ts_local >= inicio) & (rep.ts_local <= fin)).sum())
        self._descubrimientos_30d = int(((primeras >= inicio) & (primeras <= fin)).sum())
        # Conjuntos normalizados para comprobar contra el historial sin depender de
        # mayúsculas ni de espacios.
        self._artistas_historial = {_texto_normalizado(a) for a in self.escuchas_por_artista.index}
        self._canciones_historial = {
            (_texto_normalizado(a), _texto_normalizado(c))
            for a, c in zip(self.reproducciones.artista, self.reproducciones.cancion)}

    @property
    def hay_fuentes_externas(self):
        return self.candidatos is not None and len(self.candidatos) > 0

    def _afinidad_artista(self, artista):
        """Afinidad entre las etiquetas de un artista y el perfil del usuario (0-1)."""
        if artista not in self._afinidad_cache:
            self._afinidad_cache[artista] = ca.afinidad_tags(
                self._tags_por_artista.get(artista, self._sin_tags), self.perfil_tags)
        return self._afinidad_cache[artista]

    def _n_tags(self, artista):
        return len(self._tags_por_artista.get(artista, self._sin_tags))

    # -- los dos catálogos -------------------------------------------------------
    def catalogo_conocido(self):
        """Una fila por canción del historial, con sus datos reales de escucha.

        El historial procesado es la fuente de verdad de lo que el usuario conoce, y trae
        ya el identificador de Spotify de cada canción, de modo que no hay que buscarlas
        después para añadirlas a una playlist.
        """
        if self._conocidas is not None:
            return self._conocidas

        rep = self.reproducciones
        conocidas = (rep.groupby(["spotify_track_uri", "cancion", "artista"], dropna=False)
                        .agg(reproducciones_usuario=("ts_local", "size"),
                             ultima_escucha=("ts_local", "max"))
                        .reset_index())
        # Un mismo identificador puede aparecer con títulos ligeramente distintos si el
        # nombre cambió en el catálogo de Spotify. Se conserva la versión más escuchada.
        conocidas = (conocidas.sort_values("reproducciones_usuario", ascending=False)
                              .drop_duplicates(subset="spotify_track_uri", keep="first"))
        conocidas["reproducciones_globales"] = np.nan
        conocidas["artista_semilla"] = None
        conocidas["similitud"] = np.nan
        self._conocidas = conocidas[COLUMNAS_CATALOGO].reset_index(drop=True)
        return self._conocidas

    def catalogo_descubrimiento(self):
        """Canciones candidatas de artistas que el usuario no ha escuchado nunca.

        Las genera el enriquecimiento a partir de artistas parecidos a los suyos, y ya
        descarta allí a los que están en su historial. Aquí se vuelve a comprobar contra
        el historial actual por tres motivos: el fichero de candidatos puede ser anterior
        a la última ejecución del ETL, la caché de las APIs puede devolver un nombre
        escrito de otra forma, y el usuario puede haber escuchado a ese artista desde que
        se generaron los candidatos.
        """
        vacio = pd.DataFrame(columns=COLUMNAS_CATALOGO)
        if not self.hay_fuentes_externas:
            return vacio

        cand = self.candidatos.copy()
        for columna in ("spotify_track_uri", "reproducciones_usuario", "ultima_escucha"):
            if columna not in cand.columns:
                cand[columna] = pd.NaT if columna == "ultima_escucha" else np.nan
        for columna in ("reproducciones_globales", "artista_semilla", "similitud"):
            if columna not in cand.columns:
                cand[columna] = np.nan

        artista_norm = cand.artista.map(_texto_normalizado)
        cancion_norm = cand.cancion.map(_texto_normalizado)
        conocido = artista_norm.isin(self._artistas_historial)
        repetida = [par in self._canciones_historial
                    for par in zip(artista_norm, cancion_norm)]
        cand = cand[~conocido & ~np.array(repetida, dtype=bool)]

        cand = cand.drop_duplicates(subset=["artista", "cancion"])
        return cand[COLUMNAS_CATALOGO].reset_index(drop=True)

    # -- puntuación --------------------------------------------------------------
    def _variables_de_candidatos(self, candidatos, momento):
        """Traduce cada candidato a la misma tabla de variables del entrenamiento."""
        # El entrenamiento define ``descubrimientos_30d`` como el número de canciones
        # cuya PRIMERA escucha histórica cae en los 30 días previos. La aplicación debe
        # calcular exactamente lo mismo: contar canciones distintas de la ventana incluiría
        # temas conocidos desde hace años y produciría una variable diferente a la usada al
        # entrenar. Las tres cifras están calculadas en _preparar_caches().
        actividad = self._actividad_30d
        descubrimientos = self._descubrimientos_30d
        historial_artista = self._historial_artista

        art = candidatos.artista
        conocidos = art.isin(historial_artista.index)
        X = pd.DataFrame(index=candidatos.index)
        X["escuchas_previas_artista"] = art.map(historial_artista.escuchas).fillna(0)
        X["canciones_previas_artista"] = art.map(historial_artista.canciones).fillna(0)
        dias = (momento - art.map(historial_artista.ultima)).dt.total_seconds() / 86400
        X["dias_desde_ultima_del_artista"] = dias.fillna(-1)
        X["artista_nuevo"] = (~conocidos).astype(int)
        X["tasa_repeticion_previa_artista"] = art.map(historial_artista.larga).fillna(0)
        X["tasa_skip_previa_artista"] = art.map(historial_artista.skip).fillna(0)
        # Contexto: lo aporta el momento en que se pide la recomendación.
        X["hora"] = momento.hour
        X["es_fin_de_semana"] = int(momento.dayofweek >= 5)
        X["franja_madrugada"] = int(3 <= momento.hour <= 6)
        X["shuffle"] = 0
        # La app propone, la usuaria no ha buscado esta canción: elección no activa.
        X["eleccion_activa"] = 0
        X["actividad_30d"] = actividad
        X["descubrimientos_30d"] = descubrimientos
        X["tasa_descubrimiento_30d"] = descubrimientos / max(actividad, 1)

        if "afinidad_tags" in self.columnas:
            if self._tags_por_artista:
                X["afinidad_tags"] = [self._afinidad_artista(a) for a in art]
                X["n_tags_artista"] = [self._n_tags(a) for a in art]
                X["artista_sin_tags"] = (X.n_tags_artista == 0).astype(int)
            else:
                # El modelo se entrenó con contenido pero el catálogo no está disponible:
                # se puntúa como si ningún artista tuviera etiquetas, en vez de fallar.
                X["afinidad_tags"] = 0.0
                X["n_tags_artista"] = 0
                X["artista_sin_tags"] = 1
        return X[self.columnas]

    def puntuar(self, candidatos, momento=None):
        if momento is None:
            momento = pd.Timestamp.now(tz=config.ZONA_HORARIA)
        if not len(candidatos):
            return candidatos.assign(puntuacion=pd.Series(dtype=float))
        candidatos = candidatos.reset_index(drop=True)
        X = self._variables_de_candidatos(candidatos, momento)
        salida = candidatos.copy()
        salida["puntuacion"] = self.modelo.predict_proba(X)[:, 1]
        return salida.sort_values("puntuacion", ascending=False).reset_index(drop=True)

    # -- ánimo -------------------------------------------------------------------
    def afinidad_con_animo(self, artistas, animo):
        """Cuánto encajan las etiquetas de cada artista con el ánimo pedido (0-1)."""
        if self.tags is None or animo not in MAPEO_ANIMO:
            return pd.Series(0.0, index=artistas.index)
        if animo not in self._animo_cache:
            objetivo = set(MAPEO_ANIMO[animo])
            pesos = (self.tags[self.tags.tag.isin(objetivo)]
                     .groupby("artista").peso.sum())
            # Se normaliza por el máximo del catálogo, no por el de la consulta, para que
            # la afinidad de un artista sea siempre la misma y los dos grupos (conocidas y
            # descubrimientos) se puedan comparar entre sí en la misma escala.
            maximo = pesos.max() if len(pesos) else 1
            self._animo_cache[animo] = pesos / (maximo or 1)
        return artistas.map(self._animo_cache[animo]).fillna(0)

    # -- ranking de un grupo -----------------------------------------------------
    def _ranking(self, base, n, animo=None, peso_animo=0.5, momento=None,
                 max_por_artista=2, diversidad=0.0, grupo="", variante=""):
        """Ordena un catálogo y devuelve sus n mejores, con diversidad por artista.

        Es el mismo procedimiento para los dos grupos, y por eso está escrito una sola
        vez: puntuar con el modelo, combinar con el ánimo, desempatar, limitar el número
        de canciones por artista y cortar.
        """
        vacio = base.head(0).assign(puntuacion=pd.Series(dtype=float),
                                    afinidad_animo=pd.Series(dtype=float),
                                    puntuacion_final=pd.Series(dtype=float))
        if n <= 0 or not len(base):
            return vacio

        puntuadas = self.puntuar(base, momento)

        if animo:
            puntuadas["afinidad_animo"] = self.afinidad_con_animo(puntuadas.artista, animo)
            # Combinación lineal: el modelo dice "esto te puede gustar", el ánimo dice
            # "esto encaja con cómo te sientes ahora". Se aplica igual a los dos grupos.
            puntuadas["puntuacion_final"] = ((1 - peso_animo) * puntuadas.puntuacion
                                             + peso_animo * puntuadas.afinidad_animo)
        else:
            puntuadas["afinidad_animo"] = np.nan
            puntuadas["puntuacion_final"] = puntuadas.puntuacion

        # Desempate. Hace falta porque las diecisiete variables del modelo describen al
        # artista y al momento, no a la canción: todas las canciones de un mismo artista
        # reciben exactamente la misma puntuación. Estos criterios NO son variables del
        # modelo y no lo modifican; sólo deciden el orden dentro de un empate.
        criterios, ascendente = ["puntuacion_final"], [False]
        if "reproducciones_usuario" in puntuadas:      # la más escuchada primero
            criterios.append("reproducciones_usuario"); ascendente.append(False)
        if "ultima_escucha" in puntuadas:              # la más reciente primero
            criterios.append("ultima_escucha"); ascendente.append(False)
        if "reproducciones_globales" in puntuadas:     # para las nuevas, la más popular
            criterios.append("reproducciones_globales"); ascendente.append(False)
        puntuadas = puntuadas.sort_values(criterios, ascending=ascendente,
                                          na_position="last", kind="mergesort")

        # Diversidad: como máximo dos canciones por artista, dentro del grupo. Como los
        # artistas de un grupo y de otro nunca coinciden (los conocidos están excluidos de
        # los descubrimientos), el límite se cumple también en la lista final.
        elegidas = puntuadas.groupby("artista", sort=False).head(max_por_artista)
        return self._seleccionar(elegidas, n, diversidad, momento, animo, grupo, variante)

    def _seleccionar(self, ordenadas, n, diversidad, momento, animo, grupo, variante=""):
        """Elige las n definitivas de entre las mejores, con o sin renovación.

        Con `diversidad = 0` se toman las n primeras, que es el comportamiento original.
        Con un valor mayor se abre una ventana de candidatos por encima de n y se sortean
        n de ella con probabilidad proporcional a su puntuación final. La ventana sólo
        contiene canciones que el propio modelo ya ha puesto arriba, así que la elección
        sigue siendo suya: lo que cambia es que deja de ser siempre la misma.

        El sorteo está sembrado con el usuario, el grupo, el ánimo y la FECHA. Eso lo hace
        reproducible dentro del mismo día: recargar la página no baraja la lista, y el
        experimento se puede repetir. Al cambiar el día cambia la semilla y la lista se
        renueva.

        `variante` es la excepción a esa regla: cuando la persona pide otra selección con
        los mismos filtros, ese valor entra también en la semilla y devuelve un sorteo
        distinto sin esperar al día siguiente. Con `variante` vacío, que es el valor por
        defecto, la semilla es exactamente la de antes: así las listas de la memoria y del
        experimento de sesgos siguen reproduciéndose igual.
        """
        if diversidad <= 0 or len(ordenadas) <= n or n <= 0:
            return ordenadas.head(n).reset_index(drop=True)

        # La ventana crece con la diversidad: con 1 se sortea entre cinco veces más
        # canciones de las que se van a enseñar. El límite por artista ya está aplicado
        # sobre `ordenadas`, así que el sorteo no puede romperlo.
        ventana = min(len(ordenadas), int(round(n * (1 + 4 * diversidad))))
        candidatas = ordenadas.head(ventana)

        pesos = candidatas.puntuacion_final.to_numpy(dtype=float)
        pesos = np.clip(pesos, 1e-9, None)
        pesos = pesos / pesos.sum()

        fecha = pd.Timestamp(momento).date() if momento is not None else "sin-momento"
        partes = [self.usuario, grupo, animo or "", fecha]
        if variante:
            partes.append(variante)
        rng = np.random.default_rng(_semilla(*partes))
        posiciones = rng.choice(len(candidatas), size=n, replace=False, p=pesos)

        # Se devuelven ordenadas por puntuación, no por orden de sorteo: la lista se sigue
        # leyendo como un ranking.
        elegidas = candidatas.iloc[sorted(posiciones)]
        return elegidas.reset_index(drop=True)

    # -- recomendación final -----------------------------------------------------
    def recomendar(self, n=10, animo=None, peso_animo=0.5, momento=None,
                   mezcla=0.5, max_por_artista=2, diversidad=None, variante=""):
        """Devuelve n recomendaciones repartidas entre música conocida y descubrimientos.

        `mezcla` es la proporción de canciones conocidas: 0,5 reparte a partes iguales,
        que es lo que usa la aplicación; 0 devuelve sólo descubrimientos y 1 sólo
        conocidas, que es lo que necesita el cuadro de mando para analizar cada grupo por
        separado.

        La proporción se garantiza construyendo dos rankings independientes y tomando de
        cada uno lo que le corresponde. Si un grupo no tiene suficientes canciones no se
        rellena con el otro: la lista sale más corta y quien llame puede contarlo con la
        columna `origen`.

        `diversidad` controla la renovación de la lista. Con 0 se devuelven siempre las
        mejores; por encima de 0 se sortean entre las mejores, con la fecha como semilla.
        Si no se indica, se usa `config.DIVERSIDAD`. El motivo de que exista está medido y
        no supuesto: sin ella, un barrido de 336 consultas del usuario de desarrollo
        producía sólo ocho listas distintas y enseñaba 13 artistas de los 6.120 de su
        historial.

        `variante` sirve para pedir otra selección con los mismos filtros, sin esperar al
        día siguiente. Vacío, que es lo normal, devuelve la lista del día.
        """
        n_conocidas = int(round(n * mezcla))
        n_nuevas = n - n_conocidas
        if diversidad is None:
            diversidad = config.DIVERSIDAD

        conocidas = self._ranking(self.catalogo_conocido(), n_conocidas, animo,
                                  peso_animo, momento, max_por_artista,
                                  diversidad, ORIGEN_CONOCIDA, variante)
        nuevas = self._ranking(self.catalogo_descubrimiento(), n_nuevas, animo,
                               peso_animo, momento, max_por_artista,
                               diversidad, ORIGEN_DESCUBRIMIENTO, variante)
        conocidas = conocidas.assign(origen=ORIGEN_CONOCIDA)
        nuevas = nuevas.assign(origen=ORIGEN_DESCUBRIMIENTO)

        lista = self._intercalar(conocidas, nuevas)
        if not len(lista):
            return lista.assign(posicion=pd.Series(dtype=int),
                                explicacion=pd.Series(dtype=object))
        lista["posicion"] = range(1, len(lista) + 1)
        lista["explicacion"] = [self.explicar(fila, animo) for _, fila in lista.iterrows()]
        return lista.reset_index(drop=True)

    @staticmethod
    def _intercalar(conocidas, nuevas):
        """Alterna conocidas y descubrimientos para que la lista no salga por bloques.

        El orden dentro de cada grupo se respeta; lo único que cambia es cómo se
        entrelazan. Si un grupo se agota, el resto del otro va detrás.
        """
        filas = []
        for i in range(max(len(conocidas), len(nuevas))):
            if i < len(conocidas):
                filas.append(conocidas.iloc[[i]])
            if i < len(nuevas):
                filas.append(nuevas.iloc[[i]])
        if not filas:
            return pd.concat([conocidas, nuevas])
        return pd.concat(filas, ignore_index=True)

    @staticmethod
    def reparto(recomendaciones):
        """Cuántas recomendaciones son conocidas y cuántas descubrimientos."""
        if "origen" not in recomendaciones:
            return {"total": len(recomendaciones), "conocidas": 0, "descubrimientos": 0}
        conteo = recomendaciones.origen.value_counts()
        return {"total": len(recomendaciones),
                "conocidas": int(conteo.get(ORIGEN_CONOCIDA, 0)),
                "descubrimientos": int(conteo.get(ORIGEN_DESCUBRIMIENTO, 0))}

    # -- explicabilidad ----------------------------------------------------------
    def explicar(self, fila, animo=None):
        """Explicación con lo que el sistema sabe de verdad de esa canción.

        Es la versión completa, la que usa el cuadro de mando. La aplicación de usuario
        construye la suya en lenguaje llano a partir de las mismas señales.
        """
        motivos = []
        es_conocida = fila.get("origen") == ORIGEN_CONOCIDA

        if es_conocida:
            escuchas = fila.get("reproducciones_usuario")
            if pd.notna(escuchas):
                motivos.append(f"ya está en tu historial, con {int(escuchas)} escuchas")
            ultima = fila.get("ultima_escucha")
            if pd.notna(ultima):
                motivos.append(f"la última vez que sonó fue el {pd.Timestamp(ultima):%d/%m/%Y}")
        else:
            semilla = fila.get("artista_semilla")
            if isinstance(semilla, str) and semilla:
                similitud = fila.get("similitud")
                extra = (f" ({similitud:.0%} de parecido según Last.fm)"
                         if pd.notna(similitud) else "")
                motivos.append(f"se parece a **{semilla}**, que escuchas mucho{extra}")
            motivos.append("es un artista que no has escuchado nunca")

        if self.tags is not None:
            del_artista = set(self.tags[self.tags.artista == fila.artista].tag)
            comunes = [t for t in self.perfil_tags.index if t in del_artista][:3]
            if comunes:
                motivos.append("comparte etiquetas contigo: " + ", ".join(comunes))
            if animo and animo in MAPEO_ANIMO:
                del_animo = del_artista & set(MAPEO_ANIMO[animo])
                if del_animo:
                    motivos.append(f"encaja con «{animo}» por: " + ", ".join(sorted(del_animo)[:3]))

        if not motivos:
            return "Aparece por su puntuación de afinidad."
        return "Aparece porque " + "; ".join(motivos) + "."

    # -- perfil ------------------------------------------------------------------
    def indicadores_perfil(self):
        rep = self.reproducciones
        repeticiones = rep.groupby("spotify_track_uri").size()
        por_anio = rep.groupby("anio").artista.apply(
            lambda s: s.value_counts().head(10).sum() / len(s) * 100)
        return {
            "reproducciones": len(rep),
            "horas": rep.ms_played.sum() / 3.6e6,
            "canciones": rep.spotify_track_uri.nunique(),
            "artistas": rep.artista.nunique(),
            "desde": str(rep.fecha_local.min()),
            "hasta": str(rep.fecha_local.max()),
            "tasa_skip": rep.es_skip.mean() * 100,
            "una_sola_escucha": (repeticiones == 1).mean() * 100,
            # Peso de los diez artistas más escuchados DEL ÚLTIMO AÑO del historial.
            # No es lo mismo que el peso sobre todo el periodo, que es la medida que da la
            # memoria; llevan nombres distintos a propósito para no confundirlas.
            "concentracion_top10_ultimo_anio": por_anio.iloc[-1] if len(por_anio) else np.nan,
            "artistas_nuevos_ultimo_anio": int(
                rep.groupby("artista").ts_local.min().dt.year.value_counts()
                   .sort_index().iloc[-1]) if len(rep) else 0,
        }
