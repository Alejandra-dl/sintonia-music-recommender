# ============================================================
# Descripción:
# Traduce un estado de ánimo ("Fiesta", "Tranquila"...) a las
# etiquetas musicales que hay que buscar. Es una decisión de
# diseño documentada, no un resultado del modelo, y por eso está
# en un fichero aparte y a la vista.
#
# El mapeo se apoya en etiquetas de género y no en etiquetas de
# ánimo directas. El motivo está medido: en el catálogo obtenido,
# las etiquetas de ánimo cubren un 5 % de las escuchas frente a
# más del 95 % de las de género, porque la comunidad de Last.fm
# etiqueta sobre todo el estilo del artista.
#
# Se utiliza en:
# El recomendador, al reordenar por ánimo, y la pantalla "¿Cómo
# te sientes hoy?".
#
# Entrada:
# El nombre de un estado de ánimo.
#
# Salida:
# La lista de etiquetas asociadas a ese estado.
#
# Limitación, dicha con claridad: un género no es un estado de
# ánimo. Está recogido como tal en la memoria.
# ============================================================

# Cada estado se asocia a las etiquetas de Last.fm que lo representan en este catálogo.
# Entre paréntesis, el número de artistas del piloto que tenían cada etiqueta.
MAPEO_ANIMO = {
    # reggaeton (70), latin urban (27), dancehall (14), latin trap (10), trap latino (31)
    "Fiesta": ["reggaeton", "latin urban", "dancehall", "latin trap", "trap latino",
               "dembow", "party", "club"],

    # trap (95), rap (117), hip hop (121), pop rap (52), southern hip hop (16)
    "Con energía": ["trap", "rap", "hip hop", "hip-hop", "pop rap", "southern hip hop",
                    "drill"],

    # dance (45), dance-pop (33), electronic (44), electropop (33), house (22)
    "Para bailar": ["dance", "dance-pop", "house", "electronic", "electropop", "disco"],

    # rnb (88), contemporary r&b (38), alternative r&b (22), soul (34), indie (19)
    "Tranquila": ["rnb", "r&b", "contemporary r&b", "alternative r&b", "alternative rnb",
                  "soul", "indie", "acoustic", "chill"],

    # latin pop (20), soul (34), singer-songwriter (21), ballad (1)
    "Romántica": ["latin pop", "bachata", "soul", "singer-songwriter", "ballad",
                  "romantic", "sensual"],

    # 90s (5), oldies (1), pop rock (21), rock (25), disco (7), 2010s (19)
    "Nostálgica": ["90s", "00s", "80s", "2010s", "oldies", "classic", "pop rock", "rock",
                   "disco"],
}

# Etiquetas que describen ánimo o contexto y no estilo. Se usan en el informe de cobertura
# para medir qué parte del catálogo tiene información de ánimo propiamente dicha.
TAGS_DE_ANIMO = {
    "happy", "sad", "chill", "chillout", "relax", "relaxing", "party", "energetic",
    "melancholy", "melancholic", "romantic", "love", "dark", "dreamy", "upbeat",
    "mellow", "aggressive", "calm", "feel good", "summer", "nostalgia", "workout",
    "sexy", "sensual", "emotional", "angry", "hopeful", "peaceful",
}
