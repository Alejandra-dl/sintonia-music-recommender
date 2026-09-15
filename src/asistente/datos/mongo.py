# ============================================================
# Descripción:
# Utilidades de administración de MongoDB y de usuarios. Dos
# órdenes:
#
#   cargar     Sube a MongoDB lo que ya está en los ficheros de
#              un usuario (historial, candidatos) y el catálogo
#              compartido, sin repetir el ETL ni el enriquecimiento.
#              Es lo que se ejecuta después de levantar Docker por
#              primera vez, o si la base se ha vaciado.
#
#   eliminar   Borra POR COMPLETO a un usuario: su carpeta de
#              datos, sus figuras, su informe de cobertura y sus
#              documentos en MongoDB. No toca el catálogo
#              compartido, porque describe artistas y no personas.
#              Es la respuesta práctica al derecho de supresión.
#
# Qué vive en cada sitio:
#   MongoDB, por usuario (user_id):  reproducciones, podcasts, candidatos
#   MongoDB, compartido:             tags_artistas, artistas_info
#   Solo en ficheros, por usuario:   bruto/, dataset_modelado, modelo_afinidad,
#                                    evaluacion, ablacion, informe_calidad
#   Solo en ficheros, compartido:    cache_apis.sqlite, portadas.sqlite,
#                                    catalogo_info.json
# El modelo y su evaluación no se guardan en MongoDB porque son
# objetos de Python serializados, no documentos consultables.
#
# Se utiliza en:
# Puesta en marcha con Docker y administración de usuarios.
#
# Uso:
#   python -m asistente.datos.mongo cargar --usuario usuario1
#   python -m asistente.datos.mongo cargar --todos
#   python -m asistente.datos.mongo estado
#   python -m asistente.datos.mongo eliminar --usuario usuario2 --confirmar
# ============================================================

import argparse
import shutil
import sys

from asistente import config
from asistente.utilidades import io_datos

COLECCIONES_PERSONALES = ("reproducciones", "podcasts", "candidatos")
COLECCIONES_COMPARTIDAS = ("tags_artistas", "artistas_info")


def conectar(uri=config.MONGO_URI, base=config.MONGO_DB, tiempo_espera_ms=3000):
    """Devuelve la base de datos o termina con un mensaje claro si no hay servicio."""
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
    try:
        cliente = MongoClient(uri, serverSelectionTimeoutMS=tiempo_espera_ms)
        cliente.admin.command("ping")
    except PyMongoError as e:
        sys.exit(f"No hay conexión con MongoDB en {uri} ({type(e).__name__}).\n"
                 "Comprueba que el servicio está levantado: docker compose up -d mongo")
    return cliente[base]


def cargar_usuario(db, usuario):
    """Sube el historial y los candidatos de un usuario desde sus ficheros."""
    ruta = config.reproducciones(usuario)
    if not io_datos.existe(ruta):
        print(f"  {usuario}: no tiene reproducciones.parquet, se omite")
        return
    rep = io_datos.leer(ruta).copy()
    rep["ts"] = rep["ts"].astype(str)          # MongoDB no admite fechas con zona horaria de pandas
    db["reproducciones"].delete_many({"user_id": usuario})
    db["reproducciones"].insert_many(rep.assign(user_id=usuario).to_dict("records"))
    db["reproducciones"].create_index([("user_id", 1), ("ts", 1)])
    print(f"  {usuario}: {len(rep):,} reproducciones")

    ruta_c = config.candidatos(usuario)
    db["candidatos"].delete_many({"user_id": usuario})
    if io_datos.existe(ruta_c):
        cand = io_datos.leer(ruta_c)
        if len(cand):
            db["candidatos"].insert_many(cand.assign(user_id=usuario).to_dict("records"))
        db["candidatos"].create_index([("user_id", 1), ("artista", 1)])
        print(f"  {usuario}: {len(cand):,} candidatos")
    else:
        print(f"  {usuario}: sin candidatos (no se ha ejecutado el enriquecimiento)")


def cargar_catalogo(db):
    """Sube el catálogo compartido. Se reescribe entero porque es común a todos."""
    for nombre, ruta in (("tags_artistas", config.TAGS_ARTISTAS),
                         ("artistas_info", config.ARTISTAS_INFO)):
        if not io_datos.existe(ruta):
            print(f"  catálogo: falta {ruta.name}, se omite")
            continue
        df = io_datos.leer(ruta)
        db[nombre].delete_many({})
        if len(df):
            db[nombre].insert_many(df.to_dict("records"))
        print(f"  catálogo: {len(df):,} filas en {nombre}")
    db["tags_artistas"].create_index([("artista", 1)])


def estado(db):
    print(f"Base de datos: {db.name}")
    for nombre in COLECCIONES_COMPARTIDAS:
        print(f"  {nombre:<16} {db[nombre].count_documents({}):>9,} documentos (compartida)")
    for nombre in COLECCIONES_PERSONALES:
        por_usuario = db[nombre].aggregate([{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}])
        partes = ", ".join(f"{d['_id']}: {d['n']:,}" for d in sorted(por_usuario, key=lambda d: str(d["_id"])))
        print(f"  {nombre:<16} {partes or 'vacía'}")


def eliminar_usuario(usuario, con_mongo=True):
    """Borra todo lo que el sistema guarda de una persona. El catálogo se conserva."""
    borrado = []
    carpeta = config.carpeta_usuario(usuario)
    if carpeta.exists():
        shutil.rmtree(carpeta); borrado.append(str(carpeta))
    figuras = config.figuras(usuario)
    if figuras.exists():
        shutil.rmtree(figuras); borrado.append(str(figuras))
    informe = config.informe_cobertura(usuario)
    if informe.exists():
        informe.unlink(); borrado.append(str(informe))

    if con_mongo:
        try:
            db = conectar()
        except SystemExit:
            print("Aviso: MongoDB no disponible. Se han borrado los ficheros; vuelve a ejecutar "
                  "esta orden con el servicio levantado para borrar también sus documentos.")
            db = None
        if db is not None:
            for nombre in COLECCIONES_PERSONALES:
                n = db[nombre].delete_many({"user_id": usuario}).deleted_count
                if n:
                    borrado.append(f"MongoDB {nombre}: {n:,} documentos")
    return borrado


def main():
    ap = argparse.ArgumentParser(description="Administración de MongoDB y de usuarios")
    sub = ap.add_subparsers(dest="orden", required=True)

    c = sub.add_parser("cargar", help="sube a MongoDB los ficheros ya procesados")
    c.add_argument("--usuario", default=None)
    c.add_argument("--todos", action="store_true", help="todos los usuarios con datos")
    c.add_argument("--sin-catalogo", action="store_true")
    c.add_argument("--mongo-uri", default=config.MONGO_URI)
    c.add_argument("--mongo-db", default=config.MONGO_DB)

    e = sub.add_parser("estado", help="qué hay en la base de datos")
    e.add_argument("--mongo-uri", default=config.MONGO_URI)
    e.add_argument("--mongo-db", default=config.MONGO_DB)

    b = sub.add_parser("eliminar", help="borra por completo a un usuario")
    b.add_argument("--usuario", required=True)
    b.add_argument("--confirmar", action="store_true",
                   help="sin esta opción solo se muestra qué se borraría")
    b.add_argument("--sin-mongo", action="store_true")

    args = ap.parse_args()

    if args.orden == "cargar":
        db = conectar(args.mongo_uri, args.mongo_db)
        usuarios = config.usuarios_disponibles() if args.todos else [args.usuario or config.USUARIO]
        if not args.sin_catalogo:
            cargar_catalogo(db)
        for u in usuarios:
            cargar_usuario(db, u)
        print("Listo.")
        estado(db)

    elif args.orden == "estado":
        estado(conectar(args.mongo_uri, args.mongo_db))

    elif args.orden == "eliminar":
        if args.usuario not in config.usuarios_disponibles():
            sys.exit(f"No existe el usuario '{args.usuario}'. "
                     f"Disponibles: {', '.join(config.usuarios_disponibles()) or 'ninguno'}")
        if not args.confirmar:
            print(f"Se borraría TODO lo de '{args.usuario}': su carpeta {config.carpeta_usuario(args.usuario)}, "
                  f"sus figuras, su informe de cobertura y sus documentos en MongoDB "
                  f"({', '.join(COLECCIONES_PERSONALES)}). El catálogo compartido se conserva.\n"
                  "Para hacerlo de verdad, repite la orden con --confirmar.")
            return
        for linea in eliminar_usuario(args.usuario, con_mongo=not args.sin_mongo):
            print("  borrado:", linea)
        print(f"Usuario '{args.usuario}' eliminado.")


if __name__ == "__main__":
    main()
