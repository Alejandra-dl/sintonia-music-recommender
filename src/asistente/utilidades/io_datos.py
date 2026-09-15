# ============================================================
# Descripción:
# Lee y escribe las tablas del proyecto. Usa Parquet, que pesa
# menos y conserva los tipos de dato, y si en ese equipo no está
# disponible, cae automáticamente a CSV comprimido.
#
# El respaldo no es teórico: Smart App Control de Windows 11
# bloqueaba la librería pyarrow y sin esta alternativa el
# proyecto no arrancaba. Pasar todas las lecturas y escrituras
# por aquí es lo que permitió seguir trabajando.
#
# Se utiliza en:
# El ETL, el enriquecimiento, los notebooks y el acceso a datos
# de la aplicación. Nadie llama a read_parquet directamente.
#
# Entrada:
# Un DataFrame y una ruta, o solo una ruta para leer.
#
# Salida:
# El DataFrame leído, o la ruta realmente escrita, que puede ser
# .parquet o .csv.gz según lo que soporte el equipo.
# ============================================================

from pathlib import Path

import pandas as pd

# Columnas que deben volver a interpretarse como fechas al leer un CSV, porque el
# formato de texto no conserva el tipo.
COLUMNAS_FECHA = ("ts", "ts_local", "t0", "ultima", "inicio")

def hay_parquet():
    """¿Está disponible algún motor de Parquet en este equipo?"""
    for motor in ("pyarrow", "fastparquet"):
        try:
            __import__(motor)
            return True
        except ImportError:
            continue
    return False

def _ruta_csv(ruta):
    return ruta.with_suffix("").with_suffix(".csv.gz") if ruta.suffix == ".parquet"\
        else Path(str(ruta) + ".csv.gz")

def existe(ruta):
    """Comprueba si hay datos en esa ruta, en cualquiera de los dos formatos."""
    ruta = Path(ruta)
    return ruta.exists() or _ruta_csv(ruta).exists()

def leer(ruta):
    """Lee una tabla en Parquet o, si no se puede, en CSV comprimido."""
    ruta = Path(ruta)
    if ruta.exists() and hay_parquet():
        return pd.read_parquet(ruta)

    csv = _ruta_csv(ruta)
    if not csv.exists():
        if ruta.exists():
            raise ImportError(
                f"{ruta.name} está en formato Parquet pero este equipo no puede leerlo "
                "(falta pyarrow o está bloqueado). Vuelve a ejecutar el ETL para generar "
                "la versión .csv.gz.")
        raise FileNotFoundError(f"No encuentro {ruta} ni {csv}")

    df = pd.read_csv(csv)
    for columna in COLUMNAS_FECHA:
        if columna in df.columns:
            df[columna] = pd.to_datetime(df[columna], format="mixed", utc=True)
    return df

def guardar(df, ruta):
    """Guarda en Parquet si se puede y, si no, en CSV comprimido.

    Devuelve la ruta realmente escrita, para poder informar por pantalla.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if hay_parquet():
        df.to_parquet(ruta, index=False)
        return ruta
    csv = _ruta_csv(ruta)
    df.to_csv(csv, index=False, compression="gzip")
    return csv
