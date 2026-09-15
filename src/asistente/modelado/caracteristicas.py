# ============================================================
# Descripción:
# Define QUÉ se predice y CON QUÉ variables. Es el único sitio
# del proyecto donde están esas dos definiciones.
#
# La variable objetivo se construye por repetición: una canción
# cuenta como acierto si en los 30 días siguientes a la primera
# escucha se repite al menos dos veces con más de 30 segundos
# reproducidos. El historial de Spotify no trae ningún "me
# gusta", así que la etiqueta hay que construirla, y esta es la
# decisión metodológica central del trabajo.
#
# Se utiliza en:
# El notebook 02, que crea la tabla de entrenamiento; el
# notebook 03, que entrena; y el recomendador, que calcula las
# mismas variables para los candidatos en tiempo real. Que sea
# un módulo y no código dentro de un notebook es lo que
# garantiza que el entrenamiento y la aplicación calculen
# exactamente lo mismo.
#
# Entrada:
# El historial limpio del usuario y, opcionalmente, las
# etiquetas de artista del catálogo.
#
# Salida:
# Una fila por canción con sus variables y la etiqueta y (0/1),
# y las funciones para partir esa tabla en entrenamiento,
# validación y prueba respetando el orden temporal.
#
# La justificación de los umbrales está en el notebook 02 y en
# el apartado 4.2.4 de la memoria.
# ============================================================

import numpy as np
import pandas as pd

# --- Parámetros de la definición (documentados en la memoria) ---------------------
VENTANA_DIAS = 30           # ventana de observación tras la primera escucha
MIN_REPETICIONES = 2        # repeticiones necesarias para considerar "se le quedó"
SEG_ESCUCHA_VALIDA = 30     # una escucha cuenta si supera este tiempo reproducido

COLUMNAS_ARTISTA = [
    "escuchas_previas_artista",
    "canciones_previas_artista",
    "dias_desde_ultima_del_artista",
    "artista_nuevo",
    "tasa_repeticion_previa_artista",
    "tasa_skip_previa_artista",
]
COLUMNAS_CONTEXTO = [
    "hora",
    "es_fin_de_semana",
    "franja_madrugada",
    "shuffle",
    "eleccion_activa",
]
COLUMNAS_ACTIVIDAD = [
    "actividad_30d",              # escuchas en los 30 días previos
    "descubrimientos_30d",        # canciones nuevas probadas en los 30 días previos
    "tasa_descubrimiento_30d",    # proporción de descubrimiento reciente
]

# ---------------------------------------------------------------------------------
# Variable objetivo
# ---------------------------------------------------------------------------------
def construir_objetivo(rep,
                       ventana_dias = VENTANA_DIAS,
                       min_repeticiones = MIN_REPETICIONES,
                       seg_validos = SEG_ESCUCHA_VALIDA):
    """Devuelve una fila por canción con su primera escucha y la etiqueta y."""
    rep = rep.sort_values("ts_local")
    primera = rep.groupby("spotify_track_uri").ts_local.min().rename("t0")
    fin_historial = rep.ts_local.max()

    d = rep.merge(primera, left_on="spotify_track_uri", right_index=True)
    posteriores = d[(d.ts_local > d.t0)
                    & (d.ts_local <= d.t0 + pd.Timedelta(days=ventana_dias))
                    & (d.segundos >= seg_validos)]
    repeticiones = posteriores.groupby("spotify_track_uri").size().rename("repeticiones")

    elegibles = primera[primera <= fin_historial - pd.Timedelta(days=ventana_dias)]
    obj = elegibles.to_frame().join(repeticiones).fillna({"repeticiones": 0})
    obj["y"] = (obj.repeticiones >= min_repeticiones).astype(int)
    return obj.reset_index()

# ---------------------------------------------------------------------------------
# Características
# ---------------------------------------------------------------------------------
def _historial_previo_por_artista(rep):
    """Acumulados por artista calculados en orden temporal, sin mirar al futuro.

    Para cada reproducción se guarda el estado del artista JUSTO ANTES de ella.
    """
    r = rep.sort_values("ts_local").copy()
    g = r.groupby("artista", sort=False)

    r["escuchas_previas_artista"] = g.cumcount()
    r["canciones_previas_artista"] = (
        g.spotify_track_uri.apply(lambda s: (~s.duplicated()).cumsum().shift(fill_value=0))
         .reset_index(level=0, drop=True))
    r["dias_desde_ultima_del_artista"] = (
        (r.ts_local - g.ts_local.shift(1)).dt.total_seconds() / 86400)
    # Comportamiento previo de la usuaria con ese artista (media acumulada, desplazada)
    r["tasa_skip_previa_artista"] = (
        g.es_skip.apply(lambda s: s.shift(fill_value=False).expanding().mean())
         .reset_index(level=0, drop=True))
    escucha_larga = (r.segundos >= SEG_ESCUCHA_VALIDA)
    r["tasa_repeticion_previa_artista"] = (
        escucha_larga.groupby(r.artista)
        .apply(lambda s: s.shift(fill_value=False).expanding().mean())
        .reset_index(level=0, drop=True))
    return r

def construir_dataset(rep, tags_artista = None,
                      **kwargs):
    """Dataset de modelado completo: una fila por canción, con y y características.

    Parameters
    ----------
    rep : historial limpio (salida del ETL) con ts_local, artista, segundos, es_skip…
    tags_artista : opcional, salida de `etl/enriquecer.py`. Si se pasa, añade las
        características de contenido (afinidad de las etiquetas del artista con el
        perfil de la usuaria). Si es None, el dataset se construye solo con señales
        del historial y el modelo sigue siendo entrenable.
    """
    obj = construir_objetivo(rep, **kwargs)
    r = _historial_previo_por_artista(rep)

    # Nos quedamos con la fila de la PRIMERA escucha de cada canción
    primeras = (r.merge(obj[["spotify_track_uri", "t0", "y", "repeticiones"]],
                        on="spotify_track_uri")
                 .query("ts_local == t0")
                 .drop_duplicates(subset="spotify_track_uri", keep="first"))

    X = pd.DataFrame({
        "spotify_track_uri": primeras.spotify_track_uri.values,
        "cancion": primeras.master_metadata_track_name.values,
        "artista": primeras.artista.values,
        "t0": primeras.t0.values,
        "y": primeras.y.values,
        "repeticiones": primeras.repeticiones.values,
        # --- Familia A: artista (transferibles a candidatos no escuchados) ---
        "escuchas_previas_artista": primeras.escuchas_previas_artista.values,
        "canciones_previas_artista": primeras.canciones_previas_artista.values,
        "dias_desde_ultima_del_artista": primeras.dias_desde_ultima_del_artista.fillna(-1).values,
        "artista_nuevo": (primeras.escuchas_previas_artista == 0).astype(int).values,
        "tasa_repeticion_previa_artista": primeras.tasa_repeticion_previa_artista.fillna(0).values,
        "tasa_skip_previa_artista": primeras.tasa_skip_previa_artista.fillna(0).values,
        # --- Familia B: contexto de la escucha ---
        "hora": primeras.hora.values,
        "es_fin_de_semana": (primeras.dia_semana >= 5).astype(int).values,
        "franja_madrugada": primeras.hora.between(3, 6).astype(int).values,
        "shuffle": primeras.shuffle.astype(int).values,
        # playbtn/clickrow = la usuaria eligió; trackdone/appload = se lo puso el sistema
        "eleccion_activa": primeras.reason_start.isin(["playbtn", "clickrow"]).astype(int).values,
    })

    X = agregar_actividad_reciente(X, rep)
    if tags_artista is not None:
        X = agregar_caracteristicas_de_contenido(X, rep, tags_artista)
    return X.sort_values("t0").reset_index(drop=True)

def agregar_actividad_reciente(X, rep,
                              dias = 30):
    """Cuánta música y cuánta música NUEVA venía escuchando en los días previos.

    Se calcula por búsqueda binaria sobre los instantes ordenados: contar cuántas
    reproducciones (y cuántas primeras escuchas) caen en la ventana anterior a t0.
    """
    X = X.copy()
    ts = np.sort(rep.ts_local.values.astype("datetime64[ns]"))
    primeras = np.sort(rep.groupby("spotify_track_uri").ts_local.min()
                       .values.astype("datetime64[ns]"))
    t0 = pd.to_datetime(X.t0).values.astype("datetime64[ns]")
    ini = t0 - np.timedelta64(dias, "D")

    X["actividad_30d"] = np.searchsorted(ts, t0) - np.searchsorted(ts, ini)
    X["descubrimientos_30d"] = np.searchsorted(primeras, t0) - np.searchsorted(primeras, ini)
    X["tasa_descubrimiento_30d"] = X.descubrimientos_30d / X.actividad_30d.clip(lower=1)
    return X

# ---------------------------------------------------------------------------------
# Características de contenido (solo si hay enriquecimiento)
# ---------------------------------------------------------------------------------
def consolidar_tags(tags_artista):
    """Deja una sola fila por artista y etiqueta.

    Un artista puede tener la misma etiqueta desde Last.fm y desde MusicBrainz. Si no se
    unifican, la etiqueta cuenta dos veces en el perfil y pesa el doble de lo que debería.
    Se queda el peso mayor de las dos fuentes, que es el de Last.fm cuando existe, porque
    ahí el peso refleja cuánta gente ha puesto esa etiqueta.
    """
    return tags_artista.groupby(["artista", "tag"], as_index=False).peso.max()

def perfil_de_tags(rep, tags_artista,
                   hasta = None, top = 40):
    """Perfil de la usuaria como vector de etiquetas ponderado por escuchas.

    `tags_artista` debe tener columnas: artista, tag, peso (0-100).
    Si se pasa `hasta`, solo usa escuchas anteriores a esa fecha (evita fuga).
    """
    h = rep if hasta is None else rep[rep.ts_local < hasta]
    escuchas = h.artista.value_counts().rename("escuchas")
    t = consolidar_tags(tags_artista).merge(escuchas, left_on="artista",
                                            right_index=True, how="inner")
    t["aporte"] = t.peso * t.escuchas
    perfil = t.groupby("tag").aporte.sum().sort_values(ascending=False).head(top)
    return perfil / perfil.sum() if len(perfil) else perfil

def afinidad_tags(tags_del_artista, perfil):
    """Similitud entre las etiquetas de un artista y el perfil de la usuaria (0-1)."""
    if not len(tags_del_artista) or not len(perfil):
        return 0.0
    v = tags_del_artista.groupby("tag").peso.max()
    v = v / v.sum()
    comunes = v.index.intersection(perfil.index)
    if not len(comunes):
        return 0.0
    # Similitud del coseno sobre el vocabulario común de etiquetas
    a, b = v.reindex(perfil.index).fillna(0).values, perfil.values
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))

def agregar_caracteristicas_de_contenido(X, rep,
                                        tags_artista):
    """Añade afinidad de etiquetas y nº de etiquetas conocidas del artista.

    La afinidad se calcula con el perfil de la usuaria en el momento t0 de cada fila
    (se recalcula por trimestre para que sea asumible en tiempo de cálculo).
    """
    X = X.copy()
    grupos = dict(tuple(tags_artista.groupby("artista")))
    X["periodo"] = pd.to_datetime(X.t0).dt.to_period("Q")

    afinidades = np.zeros(len(X))
    for periodo, idx in X.groupby("periodo").groups.items():
        # pandas 3 quitó el argumento tz de to_timestamp, hay que localizar después
        corte = periodo.to_timestamp().tz_localize(rep.ts_local.dt.tz)
        perfil = perfil_de_tags(rep, tags_artista, hasta=corte)
        for i in idx:
            art = X.at[i, "artista"]
            afinidades[X.index.get_loc(i)] = afinidad_tags(
                grupos.get(art, pd.DataFrame(columns=["tag", "peso"])), perfil)

    X["afinidad_tags"] = afinidades
    X["n_tags_artista"] = X.artista.map(
        {a: len(g) for a, g in grupos.items()}).fillna(0).astype(int)
    X["artista_sin_tags"] = (X.n_tags_artista == 0).astype(int)
    return X.drop(columns="periodo")

def columnas_modelo(con_contenido):
    cols = COLUMNAS_ARTISTA + COLUMNAS_CONTEXTO + COLUMNAS_ACTIVIDAD
    if con_contenido:
        cols = cols + ["afinidad_tags", "n_tags_artista", "artista_sin_tags"]
    return cols

# ---------------------------------------------------------------------------------
# Partición temporal
# ---------------------------------------------------------------------------------
def particion_temporal(X, corte_val, corte_test):
    """Entrenamiento -> validación -> prueba, siempre hacia adelante en el tiempo.

    Nunca al azar: usar canciones de 2026 para predecir 2021 sería hacer trampa, y
    además no es el escenario real de uso (siempre se predice el futuro).
    """
    t0 = pd.to_datetime(X.t0)
    tz = t0.dt.tz
    cv, ct = pd.Timestamp(corte_val, tz=tz), pd.Timestamp(corte_test, tz=tz)
    return X[t0 < cv].copy(), X[(t0 >= cv) & (t0 < ct)].copy(), X[t0 >= ct].copy()
