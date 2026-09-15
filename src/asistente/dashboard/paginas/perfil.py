"""Análisis del comportamiento de escucha del usuario."""

import plotly.graph_objects as go
import streamlit as st

from asistente.dashboard import estilo
from asistente.dashboard.estado import preparar, usuario_actual

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def mostrar():
    rec, _ = preparar(usuario_actual())
    rep = rec.reproducciones.copy()
    ind = rec.indicadores_perfil()

    estilo.cabecera(
        "Consumo musical",
        "Cómo ha cambiado la escucha a lo largo del tiempo, cuándo se concentra y qué artistas y canciones dominan el historial.",
        "PERFIL DE ESCUCHA",
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reproducciones", estilo.miles(ind["reproducciones"]))
    c2.metric("Horas", estilo.miles(ind["horas"]))
    c3.metric("Tasa de skip", f"{ind['tasa_skip']:.1f} %")
    c4.metric("Canciones de una sola escucha", f"{ind['una_sola_escucha']:.1f} %")

    anual = (rep.groupby("anio")
             .agg(horas=("ms_played", lambda s: s.sum() / 3.6e6),
                  reproducciones=("ts", "size"),
                  artistas=("artista", "nunique"),
                  canciones=("spotify_track_uri", "nunique"),
                  skip=("es_skip", "mean"))
             .reset_index())

    fig = estilo.figura("Evolución anual del tiempo de escucha", alto=350, hovermode="x unified")
    fig.add_trace(go.Scatter(x=anual.anio, y=anual.horas, mode="lines+markers",
                             line=dict(color=estilo.VERDE, width=3), marker=dict(size=7)))
    fig.update_layout(xaxis_title="Año", yaxis_title="Horas")
    estilo.grafica(fig)
    if len(anual) >= 2:
        primero, ultimo = anual.iloc[0], anual.iloc[-1]
        estilo.interpretacion(
            f"El historial permite observar la evolución desde {int(primero.anio)} hasta {int(ultimo.anio)}. "
            f"En el último año disponible se registran {estilo.miles(ultimo.horas)} horas de escucha."
        )

    izq, der = st.columns(2)
    with izq:
        mensual = (rep.assign(mes=rep.ts_local.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp())
                   .groupby("mes")
                   .agg(reproducciones=("ts", "size"),
                        horas=("ms_played", lambda s: s.sum() / 3.6e6))
                   .reset_index())
        fig = estilo.figura("Evolución mensual", alto=330, hovermode="x unified")
        fig.add_trace(go.Scatter(x=mensual.mes, y=mensual.reproducciones, mode="lines",
                                 fill="tozeroy", line=dict(color=estilo.AZUL, width=2),
                                 fillcolor="rgba(79,140,255,.12)"))
        fig.update_layout(xaxis_title="Mes", yaxis_title="Reproducciones")
        estilo.grafica(fig)

    with der:
        matriz = (rep.pivot_table(index="dia_semana", columns="hora", values="ts", aggfunc="size")
                  .reindex(index=range(7), columns=range(24)).fillna(0))
        fig = estilo.figura("Patrón semanal por hora", alto=330)
        fig.add_trace(go.Heatmap(z=matriz.values,
                                 x=[f"{h:02d}:00" for h in matriz.columns],
                                 y=DIAS,
                                 colorscale=estilo.ESCALA_CALOR,
                                 colorbar=dict(title="", outlinewidth=0)))
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(xaxis_title="Hora", yaxis_title="")
        estilo.grafica(fig)

    hora_pico = int(rep.hora.value_counts().idxmax())
    dia_pico = DIAS[int(rep.dia_semana.value_counts().idxmax())]
    estilo.interpretacion(
        f"La mayor concentración de reproducciones aparece a las {hora_pico:02d}:00; "
        f"{dia_pico} es el día con más actividad acumulada."
    )

    izq, der = st.columns(2)
    with izq:
        top_artistas = rep.artista.value_counts().head(12).sort_values()
        fig = estilo.figura("Artistas principales", alto=410)
        fig.add_trace(go.Bar(x=top_artistas.values, y=top_artistas.index, orientation="h",
                             marker_color=estilo.NARANJA))
        fig.update_layout(xaxis_title="Reproducciones", yaxis_title="")
        estilo.grafica(fig)

    with der:
        top_canciones = (rep.groupby(["cancion", "artista"]).size()
                         .sort_values(ascending=False).head(12).sort_values())
        etiquetas = [f"{c} · {a}" for c, a in top_canciones.index]
        fig = estilo.figura("Canciones principales", alto=410)
        fig.add_trace(go.Bar(x=top_canciones.values, y=etiquetas, orientation="h",
                             marker_color=estilo.ROSA))
        fig.update_layout(xaxis_title="Reproducciones", yaxis_title="")
        estilo.grafica(fig)

    st.divider()
    st.subheader("Diversidad y skips")
    izq, der = st.columns(2)
    with izq:
        fig = estilo.figura("Artistas distintos por año", alto=320)
        fig.add_trace(go.Bar(x=anual.anio.astype(str), y=anual.artistas,
                             marker_color=estilo.VIOLETA))
        fig.update_layout(xaxis_title="Año", yaxis_title="Artistas distintos")
        estilo.grafica(fig)

    with der:
        fig = estilo.figura("Evolución de la tasa de skip", alto=320, hovermode="x unified")
        fig.add_trace(go.Scatter(x=anual.anio, y=anual.skip * 100, mode="lines+markers",
                                 line=dict(color=estilo.ROJO, width=2.5)))
        fig.update_layout(xaxis_title="Año", yaxis_title="Skips (%)")
        estilo.grafica(fig)

    if len(anual):
        ultimo = anual.iloc[-1]
        estilo.interpretacion(
            f"En {int(ultimo.anio)} aparecen {estilo.miles(ultimo.artistas)} artistas distintos "
            f"y una tasa de skip del {ultimo.skip * 100:.1f} %."
        )
