# ============================================================
# Descripción:
# ETL del historial extendido de Spotify de un usuario. Lee los
# JSON que entrega Spotify, elimina los campos personales que no
# hacen falta, separa la música de los podcasts, limpia
# duplicados y reproducciones vacías, recorta al periodo con
# datos continuos y calcula las columnas derivadas.
#
# Es el mismo proceso para cualquier usuario: lo único que
# cambia es la carpeta de entrada y el identificador. Por eso es
# un script ejecutable y no código dentro de un notebook.
#
# Se utiliza en:
# Primer paso del pipeline, y explicado paso a paso en el
# notebook 00.
#
# Entrada:
# Los ficheros Streaming_History_Audio_*.json del usuario.
#
# Salida:
# reproducciones.parquet e informe_calidad.md en la carpeta del
# usuario, y la colección de MongoDB si se indica --mongo-uri.
#
# Uso:
#   python -m asistente.etl.spotify --usuario usuario1 \
#          --min-date 2019-09-01
# ============================================================

import argparse
import glob
import json
import os

import pandas as pd

from asistente import config
from asistente.utilidades.io_datos import guardar as guardar_tabla

# Campos que NO se conservan (minimización de datos, RGPD art. 5.1.c)
CAMPOS_SENSIBLES = ["ip_addr", "ip_addr_decrypted", "user_agent_decrypted",
                    "username", "offline_timestamp"]

def ingesta(input_dir):
    """Lee y concatena todos los JSON de audio de la carpeta del usuario."""
    patron = os.path.join(input_dir, "Streaming_History_Audio_*.json")
    archivos = sorted(glob.glob(patron))
    if not archivos:
        raise FileNotFoundError(f"No hay Streaming_History_Audio_*.json en {input_dir}")
    registros = []
    for ruta in archivos:
        with open(ruta, encoding="utf-8") as fh:
            registros.extend(json.load(fh))
    return pd.DataFrame(registros), archivos

def minimizacion(df):
    """Elimina campos sensibles presentes. Devuelve df y lista de eliminados."""
    presentes = [c for c in CAMPOS_SENSIBLES if c in df.columns]
    return df.drop(columns=presentes), presentes

def separacion(df):
    """Separa música, podcasts y audiolibros según la URI presente.

    Solo la música sigue adelante. Los podcasts y audiolibros se cuentan para el informe de
    calidad (y los podcasts se cargan aparte en MongoDB si se pide), pero no entran en el
    modelo: la señal de repetición no significa lo mismo en un episodio que en una canción.
    """
    es_musica = df["spotify_track_uri"].notna()
    es_podcast = df.get("spotify_episode_uri")
    es_podcast = es_podcast.notna() if es_podcast is not None else pd.Series(False, index=df.index)
    es_audiolibro = df.get("audiobook_uri")
    es_audiolibro = es_audiolibro.notna() if es_audiolibro is not None else pd.Series(False, index=df.index)
    return df[es_musica].copy(), df[es_podcast].copy(), df[es_audiolibro].copy()

def limpieza(musica):
    """Duplicados exactos y reproducciones de 0 ms."""
    stats = {}
    stats["duplicados_exactos"] = int(musica.duplicated(subset=["ts", "spotify_track_uri"]).sum())
    musica = musica.drop_duplicates(subset=["ts", "spotify_track_uri"], keep="first")
    stats["reproducciones_0ms"] = int((musica["ms_played"] == 0).sum())
    musica = musica[musica["ms_played"] > 0]
    return musica, stats

def filtro_temporal(musica, min_date, max_date):
    stats = {"fuera_de_rango": 0}
    if min_date or max_date:
        antes = len(musica)
        if min_date:
            musica = musica[musica["ts"] >= pd.Timestamp(min_date, tz="UTC")]
        if max_date:
            musica = musica[musica["ts"] <= pd.Timestamp(max_date, tz="UTC")]
        stats["fuera_de_rango"] = antes - len(musica)
    return musica, stats

def derivadas(musica, tz):
    """Campos derivados para EDA y modelado. Hora local del usuario (ts llega en UTC)."""
    ts_local = musica["ts"].dt.tz_convert(tz)
    musica["fecha_local"] = ts_local.dt.date.astype(str)
    musica["anio"] = ts_local.dt.year
    musica["mes"] = ts_local.dt.month
    musica["dia_semana"] = ts_local.dt.dayofweek  # 0 = lunes
    musica["hora"] = ts_local.dt.hour
    musica["segundos"] = (musica["ms_played"] / 1000).round(1)
    # Skip: marcado por Spotify o terminado con el botón de avanzar
    musica["es_skip"] = (musica["skipped"] == True) | (musica["reason_end"] == "fwdbtn")  # noqa: E712
    return musica

def cargar_en_mongo(musica, podcasts, user_id, mongo_uri, mongo_db):
    from pymongo import MongoClient
    cli = MongoClient(mongo_uri)
    db = cli[mongo_db]
    mus = musica.copy()
    mus["ts"] = mus["ts"].astype(str)
    db["reproducciones"].delete_many({"user_id": user_id})
    docs = mus.assign(user_id=user_id).to_dict("records")
    db["reproducciones"].insert_many(docs)
    if len(podcasts):
        pod = podcasts.copy()
        pod["ts"] = pod["ts"].astype(str)
        db["podcasts"].delete_many({"user_id": user_id})
        db["podcasts"].insert_many(pod.assign(user_id=user_id).to_dict("records"))
    db["reproducciones"].create_index([("user_id", 1), ("ts", 1)])
    return len(docs)

def informe(user_id, archivos, n_bruto, campos_borrados, n_mus, n_pod, n_audio,
            stats_limpieza, stats_filtro, musica, ruta_md):
    anios = musica["anio"].value_counts().sort_index()
    filas_anio = "\n".join(f"| {a} | {n:,} |" for a, n in anios.items())
    md = f"""# Informe de calidad de datos. ETL Spotify (usuario: {user_id})


## Ingesta
- Archivos leídos: {len(archivos)}
- Registros brutos: **{n_bruto:,}**

## Minimización (RGPD)
- Campos sensibles eliminados: {', '.join(campos_borrados) if campos_borrados else 'ninguno presente'}

## Separación por tipo de contenido
- Música: {n_mus:,} · Podcasts: {n_pod:,} · Audiolibros: {n_audio:,}

## Limpieza (solo música)
- Duplicados exactos (ts + track_uri) eliminados: {stats_limpieza['duplicados_exactos']:,}
- Reproducciones de 0 ms eliminadas: {stats_limpieza['reproducciones_0ms']:,}
- Registros fuera del rango temporal elegido: {stats_filtro['fuera_de_rango']:,}

## Dataset final
- **Reproducciones: {len(musica):,}**
- Canciones únicas: {musica['spotify_track_uri'].nunique():,}
- Artistas únicos: {musica['master_metadata_album_artist_name'].nunique():,}
- Periodo: {musica['fecha_local'].min()} → {musica['fecha_local'].max()}
- Skips (marcados o botón avanzar): {int(musica['es_skip'].sum()):,} ({musica['es_skip'].mean()*100:.1f}%)

| Año | Reproducciones |
|---|---|
{filas_anio}
"""
    with open(ruta_md, "w", encoding="utf-8") as fh:
        fh.write(md)

def main():
    ap = argparse.ArgumentParser(description="ETL del historial extendido de Spotify")
    ap.add_argument("--usuario", default=config.USUARIO,
                    help="identificador del usuario: usuario1, usuario2...")
    ap.add_argument("--input", default=None,
                    help="carpeta con los JSON. Por defecto, la del usuario")
    ap.add_argument("--min-date", default=None)
    ap.add_argument("--max-date", default=None)
    ap.add_argument("--tz", default=config.ZONA_HORARIA)
    ap.add_argument("--mongo-uri", default=None,
                    help="Si se indica, carga el resultado en MongoDB")
    ap.add_argument("--mongo-db", default=config.MONGO_DB)
    args = ap.parse_args()

    usuario = args.usuario
    config.crear_carpetas(usuario)
    entrada = args.input or str(config.bruto(usuario))

    df, archivos = ingesta(entrada)
    n_bruto = len(df)
    df["ts"] = pd.to_datetime(df["ts"])
    df, campos_borrados = minimizacion(df)
    musica, podcasts, audiolibros = separacion(df)
    n_mus, n_pod, n_audio = len(musica), len(podcasts), len(audiolibros)
    musica, stats_l = limpieza(musica)
    musica, stats_f = filtro_temporal(musica, args.min_date, args.max_date)
    musica = derivadas(musica, args.tz)

    ruta_parquet = guardar_tabla(musica, config.reproducciones(usuario))
    ruta_md = config.informe_calidad(usuario)
    informe(usuario, archivos, n_bruto, campos_borrados, n_mus, n_pod, n_audio,
            stats_l, stats_f, musica, ruta_md)

    print(f"OK · {len(musica):,} reproducciones limpias → {ruta_parquet}")
    print(f"Informe de calidad → {ruta_md}")

    if args.mongo_uri:
        n = cargar_en_mongo(musica, podcasts, usuario, args.mongo_uri, args.mongo_db)
        print(f"MongoDB · {n:,} documentos cargados en '{args.mongo_db}.reproducciones'")

if __name__ == "__main__":
    main()
