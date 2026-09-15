# ============================================================
# Descripción:
# Calcula los datos que se enseñan en la pantalla de resumen:
# los cuatro indicadores grandes, el top de canciones y de
# artistas, y un par de datos curiosos del historial.
#
# No hay nada de modelo aquí: son cuentas sobre el historial ya
# procesado. La parte de recomendación vive en recomendador.py.
#
# Todas las funciones aceptan un periodo: el historial completo
# o un año concreto. El filtro se aplica a los datos de verdad,
# no sólo a lo que se enseña, de modo que los indicadores, los
# rankings y los datos curiosos describen siempre el periodo
# elegido.
#
# Se utiliza en:
# La pantalla de resumen de la web.
#
# Entrada:
# El historial ya limpio del usuario (un DataFrame) y,
# opcionalmente, el año que se quiere mirar.
#
# Salida:
# Un diccionario con los indicadores y dos listas de diccionarios
# con el top de canciones y el de artistas.
# ============================================================

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def _miles(n):
    """Separador de miles a la española, para los textos de la pantalla."""
    return f"{n:,}".replace(",", ".")


def _fecha_larga(fecha):
    """De 2019-09-19 a 'septiembre de 2019'. Se lee mejor en pantalla."""
    partes = str(fecha).split("-")
    return f"{MESES[int(partes[1]) - 1]} de {partes[0]}"


def anios_disponibles(rep):
    """Los años que este usuario tiene de verdad en su historial, del más reciente atrás.

    Se sacan del propio historial y no de un rango fijo: cada persona tiene los suyos, y
    así el selector nunca ofrece un año vacío.
    """
    return sorted((int(a) for a in rep.anio.dropna().unique()), reverse=True)


def filtrar(rep, anio=None):
    """El historial completo, o sólo el del año pedido."""
    if anio is None:
        return rep
    return rep[rep.anio == int(anio)]


def _artistas_descubiertos(rep_completo, anio):
    """Artistas cuya PRIMERA escucha de toda la vida cae en ese año.

    Hay que mirarlo sobre el historial entero, no sobre el del año: un artista que ya
    sonaba en 2020 y vuelve a sonar en 2023 no es un descubrimiento de 2023.
    """
    primera = rep_completo.groupby("artista").ts_local.min().dt.year
    return int((primera == int(anio)).sum())


def indicadores(rep, anio=None, rep_completo=None):
    """Los cuatro números grandes de la cabecera, para el periodo elegido.

    Los tres primeros son siempre los mismos y describen el periodo. El cuarto cambia:
    en la vista global resume el año en curso, y cuando se mira un año concreto dice
    cuántos artistas se descubrieron ese año, que es lo que aporta información nueva.
    """
    completo = rep_completo if rep_completo is not None else rep
    del_periodo = filtrar(rep, anio)
    horas = del_periodo.ms_played.sum() / 3.6e6
    datos = {
        "anio": int(anio) if anio is not None else None,
        "horas": horas,
        "dias_equivalentes": horas / 24,
        "canciones": del_periodo.spotify_track_uri.nunique(),
        "artistas": del_periodo.artista.nunique(),
        "reproducciones": len(del_periodo),
        "desde": str(del_periodo.fecha_local.min()),
        "hasta": str(del_periodo.fecha_local.max()),
        "desde_texto": _fecha_larga(del_periodo.fecha_local.min()),
        "hasta_texto": _fecha_larga(del_periodo.fecha_local.max()),
    }
    if anio is None:
        ultimo_anio = int(rep.anio.max())
        del_anio = rep[rep.anio == ultimo_anio]
        datos.update({
            "destacado_valor": del_anio.ms_played.sum() / 60000,
            "destacado_etiqueta": f"minutos en {ultimo_anio}",
            "destacado_matiz": f"{_miles(del_anio.spotify_track_uri.nunique())} canciones ese año",
        })
    else:
        nuevos = _artistas_descubiertos(completo, anio)
        datos.update({
            "destacado_valor": nuevos,
            "destacado_etiqueta": f"artistas descubiertos en {anio}",
            "destacado_matiz": "los escuchaste por primera vez ese año",
        })
    return datos


def top_canciones(rep, n=10, anio=None):
    """Las canciones más reproducidas del periodo, con su artista."""
    rep = filtrar(rep, anio)
    columnas = ["cancion", "artista", "spotify_track_uri"]
    top = (rep.groupby(columnas, dropna=False).size()
              .rename("reproducciones").reset_index()
              .sort_values("reproducciones", ascending=False).head(n))
    top["posicion"] = range(1, len(top) + 1)
    return top.to_dict("records")


def top_artistas(rep, n=10, anio=None):
    """Los artistas más escuchados del periodo, con sus horas y sus canciones distintas."""
    rep = filtrar(rep, anio)
    top = (rep.groupby("artista")
              .agg(reproducciones=("ts", "size"),
                   horas=("ms_played", lambda s: s.sum() / 3.6e6),
                   canciones=("spotify_track_uri", "nunique"))
              .sort_values("reproducciones", ascending=False).head(n).reset_index())
    top["posicion"] = range(1, len(top) + 1)
    top["horas"] = top.horas.round(0).astype(int)
    return top.to_dict("records")


def datos_curiosos(rep, anio=None, rep_completo=None):
    """Tres observaciones del periodo, todas calculadas, ninguna inventada.

    La primera es la que se enseña en grande: dice algo sobre cómo escucha la
    persona, no solo cuánto.
    """
    completo = rep_completo if rep_completo is not None else rep
    del_periodo = filtrar(rep, anio)
    repeticiones = del_periodo.groupby("spotify_track_uri").size()
    hora_punta = int(del_periodo.hora.value_counts().idxmax())
    dia_punta = int(del_periodo.dia_semana.value_counts().idxmax())

    if anio is None:
        primera = completo.groupby("artista").ts_local.min().dt.year
        ultimo = int(rep.anio.max())
        descubrimientos = (f"Este año has descubierto {_miles(int((primera == ultimo).sum()))} "
                           "artistas nuevos")
        cuando = "que has escuchado"
    else:
        descubrimientos = (f"En {anio} descubriste "
                           f"{_miles(_artistas_descubiertos(completo, anio))} artistas nuevos")
        cuando = f"que escuchaste en {anio}"

    return {
        "principal": (f"El {(repeticiones == 1).mean() * 100:.0f} % de las canciones "
                      f"{cuando} solo las pusiste una vez"),
        "secundarios": [
            f"Tu hora punta es las {hora_punta:02d}:00",
            f"El día que más escuchas es el {DIAS[dia_punta]}",
            descubrimientos,
        ],
    }
