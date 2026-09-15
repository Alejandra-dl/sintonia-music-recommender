"""Análisis de descubrimiento musical, enriquecimiento y catálogo de candidatos."""

import plotly.graph_objects as go
import streamlit as st

from asistente.dashboard import estilo
from asistente.dashboard.estado import preparar, usuario_actual


def mostrar():
    rec, _ = preparar(usuario_actual())
    rep = rec.reproducciones

    estilo.cabecera(
        "Descubrimiento y enriquecimiento",
        "Cuándo aparecen artistas y canciones nuevas, qué cobertura aportan las fuentes externas y cómo es la reserva de candidatos.",
        "DESCUBRIMIENTO",
    )

    primera_artista = rep.groupby("artista").ts_local.min()
    primera_cancion = rep.groupby("spotify_track_uri").ts_local.min()
    nuevos_artistas = primera_artista.dt.year.value_counts().sort_index()
    nuevas_canciones = primera_cancion.dt.year.value_counts().sort_index()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Artistas descubiertos", estilo.miles(len(primera_artista)))
    c2.metric("Canciones descubiertas", estilo.miles(len(primera_cancion)))
    c3.metric("Candidatos disponibles",
              estilo.miles(len(rec.candidatos)) if rec.hay_fuentes_externas else "0")
    c4.metric("Etiquetas distintas",
              estilo.miles(rec.tags.tag.nunique()) if rec.tags is not None and len(rec.tags) else "0")

    fig = estilo.figura("Nuevos artistas y canciones por año", alto=360, barmode="group")
    fig.add_trace(go.Bar(x=nuevos_artistas.index.astype(str), y=nuevos_artistas.values,
                         name="Artistas nuevos", marker_color=estilo.VERDE))
    fig.add_trace(go.Bar(x=nuevas_canciones.index.astype(str), y=nuevas_canciones.values,
                         name="Canciones nuevas", marker_color=estilo.AZUL))
    fig.update_layout(xaxis_title="Año", yaxis_title="Nuevos descubrimientos")
    estilo.grafica(fig)
    if len(nuevos_artistas):
        anio = int(nuevos_artistas.idxmax())
        estilo.interpretacion(
            f"El mayor número de artistas nuevos se concentra en {anio}, con "
            f"{estilo.miles(nuevos_artistas.max())} incorporaciones al historial."
        )

    st.divider()
    st.subheader("Cobertura del catálogo musical")

    escuchas_por_artista = rep.artista.value_counts()
    if rec.tags is None or not len(rec.tags):
        st.info("No hay etiquetas externas disponibles para calcular la cobertura.")
    else:
        artistas_etiquetados = set(rec.tags.artista)
        cobertura_artistas = escuchas_por_artista.index.isin(artistas_etiquetados).mean() * 100
        cobertura_escuchas = (escuchas_por_artista[escuchas_por_artista.index.isin(artistas_etiquetados)].sum()
                              / escuchas_por_artista.sum() * 100)
        t1, t2, t3 = st.columns(3)
        t1.metric("Cobertura sobre escuchas", f"{cobertura_escuchas:.1f} %")
        t2.metric("Cobertura sobre artistas", f"{cobertura_artistas:.1f} %")
        t3.metric("Artistas con etiquetas", estilo.miles(rec.tags.artista.nunique()))

        izq, der = st.columns(2)
        with izq:
            top_tags = rec.tags.groupby("tag").artista.nunique().sort_values(ascending=False).head(15).sort_values()
            fig = estilo.figura("Etiquetas más extendidas en el catálogo", alto=420)
            fig.add_trace(go.Bar(x=top_tags.values, y=top_tags.index, orientation="h",
                                 marker_color=estilo.NARANJA))
            fig.update_layout(xaxis_title="Artistas etiquetados", yaxis_title="")
            estilo.grafica(fig)

        with der:
            perfil = rec.perfil_tags.head(15).sort_values()
            fig = estilo.figura("Etiquetas con más peso en el perfil del usuario", alto=420)
            fig.add_trace(go.Bar(x=perfil.values * 100, y=perfil.index, orientation="h",
                                 marker_color=estilo.ROSA))
            fig.update_layout(xaxis_title="Peso en el perfil (%)", yaxis_title="")
            estilo.grafica(fig)

        estilo.interpretacion(
            f"Las etiquetas cubren el {cobertura_escuchas:.1f} % de las reproducciones, "
            f"aunque el porcentaje de artistas cubiertos es del {cobertura_artistas:.1f} %. "
            "Esto permite distinguir entre cobertura del catálogo y cobertura efectiva sobre lo que realmente escucha el usuario."
        )

    st.divider()
    st.subheader("Reserva de canciones candidatas")
    if not rec.hay_fuentes_externas:
        st.info("No hay canciones candidatas externas disponibles para este usuario.")
        return

    cand = rec.candidatos.copy()
    izq, der = st.columns(2)
    with izq:
        if "artista_semilla" in cand.columns:
            semillas = cand.artista_semilla.dropna().value_counts().head(12).sort_values()
            fig = estilo.figura("Artistas que más candidatos generan", alto=380)
            fig.add_trace(go.Bar(x=semillas.values, y=semillas.index, orientation="h",
                                 marker_color=estilo.TURQUESA))
            fig.update_layout(xaxis_title="Canciones candidatas", yaxis_title="")
            estilo.grafica(fig)
        else:
            st.info("La tabla de candidatos no contiene información de artista semilla.")

    with der:
        if "similitud" in cand.columns and cand.similitud.notna().any():
            fig = estilo.figura("Distribución de similitud de los candidatos", alto=380)
            fig.add_trace(go.Histogram(x=cand.similitud.dropna(), nbinsx=20,
                                       marker_color=estilo.VIOLETA))
            fig.update_layout(xaxis_title="Similitud", yaxis_title="Canciones")
            estilo.grafica(fig)
        else:
            por_artista = cand.artista.value_counts().head(12).sort_values()
            fig = estilo.figura("Artistas más presentes entre los candidatos", alto=380)
            fig.add_trace(go.Bar(x=por_artista.values, y=por_artista.index, orientation="h",
                                 marker_color=estilo.VIOLETA))
            fig.update_layout(xaxis_title="Canciones candidatas", yaxis_title="")
            estilo.grafica(fig)

    estilo.interpretacion(
        f"La reserva contiene {estilo.miles(len(cand))} canciones que pueden utilizarse como punto de partida para generar recomendaciones."
    )
