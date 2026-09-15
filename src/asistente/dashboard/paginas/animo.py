"""Análisis de cobertura de ánimo y efecto sobre el ranking de recomendaciones."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from asistente.dashboard import estilo
from asistente.dashboard.estado import preparar, usuario_actual
from asistente.recomendacion.animo import MAPEO_ANIMO, TAGS_DE_ANIMO


def mostrar():
    rec, _ = preparar(usuario_actual())

    estilo.cabecera(
        "Ánimo y recomendaciones",
        "Qué cobertura tienen las etiquetas relacionadas con el estado de ánimo y cómo cambia el orden de las canciones al introducir esta señal.",
        "CONTEXTO MUSICAL",
    )

    if rec.tags is None or not len(rec.tags):
        st.info("No hay etiquetas musicales disponibles para analizar el componente de ánimo.")
        return

    tags = rec.tags.copy()
    artistas_total = tags.artista.nunique()
    artistas_con_animo_directo = tags[tags.tag.isin(TAGS_DE_ANIMO)].artista.nunique()
    cobertura_directa = artistas_con_animo_directo / max(artistas_total, 1) * 100

    filas = []
    for nombre, objetivo in MAPEO_ANIMO.items():
        sub = tags[tags.tag.isin(objetivo)]
        filas.append({
            "Ánimo": nombre,
            "Artistas": sub.artista.nunique(),
            "Etiquetas coincidentes": sub.tag.nunique(),
        })
    cobertura = pd.DataFrame(filas).sort_values("Artistas", ascending=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Estados disponibles", str(len(MAPEO_ANIMO)))
    c2.metric("Artistas con etiqueta de ánimo directa", estilo.miles(artistas_con_animo_directo))
    c3.metric("Cobertura directa sobre artistas etiquetados", f"{cobertura_directa:.1f} %")

    izq, der = st.columns([1.2, 1])
    with izq:
        fig = estilo.figura("Artistas cubiertos por cada estado de ánimo", alto=380)
        fig.add_trace(go.Bar(x=cobertura.Artistas, y=cobertura["Ánimo"], orientation="h",
                             marker_color=estilo.VERDE))
        fig.update_layout(xaxis_title="Artistas con alguna etiqueta asociada", yaxis_title="")
        estilo.grafica(fig)

    with der:
        top_mood_tags = (tags[tags.tag.isin(TAGS_DE_ANIMO)]
                         .groupby("tag").artista.nunique()
                         .sort_values(ascending=False).head(12).sort_values())
        if len(top_mood_tags):
            fig = estilo.figura("Etiquetas de ánimo más presentes", alto=380)
            fig.add_trace(go.Bar(x=top_mood_tags.values, y=top_mood_tags.index,
                                 orientation="h", marker_color=estilo.ROSA))
            fig.update_layout(xaxis_title="Artistas", yaxis_title="")
            estilo.grafica(fig)
        else:
            st.info("No hay etiquetas de ánimo directas en el catálogo actual.")

    estilo.interpretacion(
        "El sistema utiliza los seis estados definidos en el proyecto: "
        + ", ".join(MAPEO_ANIMO.keys())
        + ". La cobertura directa de etiquetas de ánimo se muestra separada de la cobertura conseguida mediante etiquetas musicales asociadas."
    )

    st.divider()
    st.subheader("Efecto del estado de ánimo sobre el ranking")
    if not rec.hay_fuentes_externas:
        st.info("No hay candidatos externos disponibles para estudiar cambios en el ranking.")
        return

    f1, f2 = st.columns([1, 1])
    animo = f1.selectbox("Estado de ánimo analizado", list(MAPEO_ANIMO))
    influencia = f2.slider(
        "Influencia del estado de ánimo en el ranking",
        min_value=0,
        max_value=100,
        value=50,
        step=5,
        help="Permite observar analíticamente cómo cambia el orden al dar más o menos peso al contexto de ánimo.",
    )
    peso = influencia / 100

    # mezcla=0 pide sólo descubrimientos. Esta página estudia el efecto del ánimo sobre
    # el ranking de candidatos externos, que es lo que hacía antes de que el recomendador
    # repartiera la lista entre música conocida y descubrimientos. Mezclar los dos grupos
    # aquí cambiaría lo que mide la comparación.
    # diversidad=0 desactiva el sorteo de renovación. Esta página compara dos ordenaciones
    # del mismo catálogo, y con el sorteo activado parte de la diferencia entre ellas sería
    # el azar y no el ánimo, que es justo lo que se quiere medir.
    base = rec.recomendar(n=50, mezcla=0.0, diversidad=0.0)
    contextual = rec.recomendar(n=50, animo=animo, peso_animo=peso, mezcla=0.0,
                                diversidad=0.0)

    # Los candidatos de Last.fm no traen identificador de Spotify, así que las dos listas
    # se cruzan por artista y canción, que es lo que sí tienen siempre.
    clave = ["artista", "cancion"]
    if len(base) and len(contextual):
        cambios = (base[clave + ["posicion"]]
                   .rename(columns={"posicion": "posición sin ánimo"})
                   .merge(contextual[clave + ["posicion", "afinidad_animo"]]
                          .rename(columns={"posicion": "posición con ánimo"}),
                          on=clave, how="inner"))
        cambios["movimiento"] = cambios["posición sin ánimo"] - cambios["posición con ánimo"]
    else:
        cambios = pd.DataFrame()

    c1, c2, c3 = st.columns(3)
    c1.metric("Canciones comparables", estilo.miles(len(cambios)))
    c2.metric("Suben de posición", estilo.miles((cambios.movimiento > 0).sum()) if len(cambios) else "0")
    c3.metric("Bajan de posición", estilo.miles((cambios.movimiento < 0).sum()) if len(cambios) else "0")

    izq, der = st.columns(2)
    with izq:
        disponibles = rec.catalogo_descubrimiento()
        afinidad = rec.afinidad_con_animo(disponibles.artista, animo)
        fig = estilo.figura(f"Afinidad de candidatos con «{animo}»", alto=350)
        fig.add_trace(go.Histogram(x=afinidad, nbinsx=20, marker_color=estilo.NARANJA))
        fig.update_layout(xaxis_title="Afinidad con el estado de ánimo", yaxis_title="Canciones candidatas")
        estilo.grafica(fig)

    with der:
        if len(cambios):
            mover = cambios.reindex(cambios.movimiento.abs().sort_values(ascending=False).index).head(12).copy()
            mover["tema"] = mover.cancion.astype(str) + " · " + mover.artista.astype(str)
            mover = mover.sort_values("movimiento")
            colores = [estilo.ROJO if x < 0 else estilo.VERDE for x in mover.movimiento]
            fig = estilo.figura("Canciones que más cambian de posición", alto=350)
            fig.add_trace(go.Bar(x=mover.movimiento, y=mover.tema, orientation="h",
                                 marker_color=colores))
            fig.update_layout(xaxis_title="Posiciones que sube (+) o baja (−)", yaxis_title="")
            estilo.grafica(fig)
        else:
            st.info("No hay suficientes canciones comunes entre ambos rankings para comparar posiciones.")

    if len(cambios):
        subida = cambios.loc[cambios.movimiento.idxmax()]
        estilo.interpretacion(
            f"Con una influencia del {influencia} %, una de las mayores subidas corresponde a "
            f"{subida.cancion} de {subida.artista}, que gana {int(subida.movimiento)} posiciones entre las canciones comparables."
        )

    st.markdown("**Primeras recomendaciones del ranking contextual**")
    columnas = [c for c in ["posicion", "cancion", "artista", "afinidad_animo"] if c in contextual.columns]
    tabla = contextual[columnas].head(12).copy()
    if "afinidad_animo" in tabla:
        tabla["afinidad_animo"] = tabla["afinidad_animo"].round(3)
        tabla = tabla.rename(columns={"afinidad_animo": "Afinidad con ánimo"})
    tabla = tabla.rename(columns={"posicion": "Posición", "cancion": "Canción", "artista": "Artista"})
    st.dataframe(tabla, width="stretch", hide_index=True)
