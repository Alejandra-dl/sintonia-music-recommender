"""Visión general del historial y del rendimiento del sistema."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from asistente.dashboard import analitica, estilo
from asistente.dashboard.estado import preparar, usuario_actual


def mostrar():
    rec, _ = preparar(usuario_actual())
    rep = rec.reproducciones
    ind = rec.indicadores_perfil()
    ev = analitica.evaluacion(usuario_actual())
    elegido = analitica.fila_modelo_elegido(ev)

    estilo.cabecera(
        "Visión general",
        "Una lectura rápida del volumen de escucha, la evolución temporal y el rendimiento del recomendador.",
        "RESUMEN ANALÍTICO",
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reproducciones", estilo.miles(ind["reproducciones"]))
    c2.metric("Horas escuchadas", estilo.miles(ind["horas"]))
    c3.metric("Artistas", estilo.miles(ind["artistas"]))
    c4.metric("Canciones", estilo.miles(ind["canciones"]))

    anual = (rep.groupby("anio")
             .agg(reproducciones=("ts", "size"),
                  horas=("ms_played", lambda s: s.sum() / 3.6e6),
                  artistas=("artista", "nunique"))
             .reset_index())

    izq, der = st.columns([1.55, 1])
    with izq:
        fig = estilo.figura("Evolución anual de la escucha", alto=360, hovermode="x unified")
        fig.add_trace(go.Scatter(x=anual.anio, y=anual.horas, mode="lines+markers",
                                 name="Horas", line=dict(color=estilo.VERDE, width=3),
                                 marker=dict(size=7)))
        fig.update_layout(xaxis_title="Año", yaxis_title="Horas")
        estilo.grafica(fig)
        if len(anual):
            pico = anual.loc[anual.horas.idxmax()]
            estilo.interpretacion(
                f"El año con más tiempo de escucha es {int(pico.anio)}, con "
                f"{estilo.miles(pico.horas)} horas registradas."
            )

    with der:
        top = rep.artista.value_counts().head(8).sort_values()
        fig = estilo.figura("Artistas con más reproducciones", alto=360)
        fig.add_trace(go.Bar(x=top.values, y=top.index, orientation="h",
                             marker_color=estilo.AZUL))
        fig.update_layout(xaxis_title="Reproducciones", yaxis_title="")
        estilo.grafica(fig)
        if len(top):
            estilo.interpretacion(
                f"{top.index[-1]} es el artista con mayor presencia en el historial del usuario seleccionado."
            )

    st.divider()
    st.subheader("Rendimiento del modelo")
    if elegido is None:
        st.info("No hay resultados de evaluación disponibles para este usuario.")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Average Precision", f"{float(elegido.get('AP', 0)):.3f}")
    m2.metric("ROC-AUC", f"{float(elegido.get('AUC', 0)):.3f}")
    m3.metric("Precision@20", f"{float(elegido.get('P@20', 0)):.2f}")
    m4.metric("Precision@50", f"{float(elegido.get('P@50', 0)):.2f}")

    tabla = pd.DataFrame(ev.get("tabla_prueba", [])) if ev else pd.DataFrame()
    if not tabla.empty and "Modelo" in tabla:
        columnas = [c for c in ["AP", "AUC", "P@20"] if c in tabla.columns]
        # Los nombres de los modelos son largos: se parten en varias líneas para
        # que quepan bajo el eje. El nombre completo sigue apareciendo al pasar
        # el ratón.
        etiquetas = [estilo.envolver(m) for m in tabla.Modelo]
        fig = estilo.figura("Modelo frente a líneas base", alto=380, barmode="group")
        for i, metrica in enumerate(columnas):
            fig.add_trace(go.Bar(x=etiquetas, y=tabla[metrica], name=metrica,
                                 marker_color=estilo.COLORES[i],
                                 customdata=tabla.Modelo,
                                 text=tabla[metrica].map(lambda v: f"{v:.2f}"),
                                 textposition="outside", cliponaxis=False,
                                 textfont=dict(color=estilo.TINTA_2, size=11),
                                 hovertemplate="%{customdata}<br>" + metrica + ": %{y:.3f}<extra></extra>"))
        fig.update_layout(yaxis_title="Valor", xaxis_title="",
                          yaxis=dict(range=[0, 1.08]))
        estilo.grafica(fig)
        mejor_ap = tabla.loc[tabla.AP.idxmax()] if "AP" in tabla else None
        if mejor_ap is not None:
            estilo.interpretacion(
                f"En el conjunto de prueba, la mayor Average Precision corresponde a "
                f"{mejor_ap.Modelo} ({float(mejor_ap.AP):.3f})."
            )
