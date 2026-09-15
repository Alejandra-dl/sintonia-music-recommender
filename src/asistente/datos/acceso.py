# ============================================================
# Descripción:
# Carga los datos que consume la aplicación para un usuario.
# Intenta leerlos de MongoDB y, si el servicio no está
# levantado, cae a los ficheros de la carpeta de ese usuario.
# La aplicación indica en la barra lateral de dónde ha leído.
#
# La doble vía es deliberada: permite enseñar el proyecto sin
# depender de que arranque una base de datos. Está justificada
# en la memoria, apartado 4.2.2.
#
# Se utiliza en:
# El arranque de la aplicación.
#
# Entrada:
# El identificador del usuario y, opcionalmente, la URI de
# MongoDB.
#
# Salida:
# Un diccionario con el historial, las etiquetas, los
# candidatos, y de dónde se ha leído cada cosa.
# ============================================================

import pandas as pd

from asistente import config
from asistente.utilidades import io_datos

URI_POR_DEFECTO = config.MONGO_URI
BASE_POR_DEFECTO = config.MONGO_DB

def _mongo(uri, base, tiempo_espera_ms = 1500):
    from pymongo import MongoClient
    cliente = MongoClient(uri, serverSelectionTimeoutMS=tiempo_espera_ms)
    cliente.admin.command("ping")          # falla rápido si no hay servicio
    return cliente[base]

def cargar(usuario=config.USUARIO, uri=URI_POR_DEFECTO, base=BASE_POR_DEFECTO):
    """Devuelve el historial, las etiquetas y los candidatos, y de dónde salieron.

    Las etiquetas vienen del catálogo compartido; el historial y los candidatos son de
    este usuario.
    """
    try:
        db = _mongo(uri, base)
        reproducciones = pd.DataFrame(list(db["reproducciones"].find(
            {"user_id": usuario}, {"_id": 0})))
        if not len(reproducciones):
            raise RuntimeError("la colección 'reproducciones' está vacía para este usuario")
        tags = pd.DataFrame(list(db["tags_artistas"].find({}, {"_id": 0})))
        candidatos = pd.DataFrame(list(db["candidatos"].find(
            {"user_id": usuario}, {"_id": 0})))
        return {"reproducciones": reproducciones,
                "tags": tags if len(tags) else None,
                "candidatos": candidatos if len(candidatos) else None,
                "origen": "MongoDB",
                "detalle": f"{base} · {len(reproducciones):,} documentos"}
    except Exception as e:                  # noqa: BLE001, cualquier fallo cae a Parquet
        motivo = f"{type(e).__name__}: {str(e)[:80]}"

    reproducciones = io_datos.leer(config.reproducciones(usuario))
    def opcional(ruta):
        return io_datos.leer(ruta) if io_datos.existe(ruta) else None

    return {"reproducciones": reproducciones,
            "tags": opcional(config.TAGS_ARTISTAS),
            "candidatos": opcional(config.candidatos(usuario)),
            "origen": "Parquet",
            "detalle": f"MongoDB no disponible ({motivo})"}
