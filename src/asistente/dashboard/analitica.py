"""Pequeñas utilidades de lectura para el dashboard analítico."""

import pickle

import pandas as pd

from asistente import config
from asistente.utilidades import io_datos


def leer_pickle(ruta):
    if not ruta.exists():
        return None
    with open(ruta, "rb") as fh:
        return pickle.load(fh)


def evaluacion(usuario):
    return leer_pickle(config.evaluacion(usuario))


def ablacion(usuario):
    return leer_pickle(config.carpeta_usuario(usuario) / "ablacion.pkl")


def dataset_modelado(usuario):
    ruta = config.dataset_modelado(usuario)
    return io_datos.leer(ruta) if io_datos.existe(ruta) else None


def fila_modelo_elegido(evaluacion):
    if not evaluacion or not evaluacion.get("tabla_prueba"):
        return None
    tabla = pd.DataFrame(evaluacion["tabla_prueba"])
    if "Modelo" not in tabla:
        return None
    mask = tabla.Modelo.astype(str).str.contains("elegido|logística", case=False, regex=True)
    return tabla[mask].iloc[0] if mask.any() else tabla.iloc[-1]
