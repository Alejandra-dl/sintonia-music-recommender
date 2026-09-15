"""Comparación descriptiva entre los usuarios del estudio."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from asistente import config
from asistente.dashboard import analitica, estado, estilo


def mostrar():
    # Los del estudio, no todos los que haya dados de alta: esta pantalla reproduce la
    # réplica de la memoria y no cambia porque después se añada otra persona.
    usuarios = config.usuarios_estudio()
    estilo.cabecera(
        "Comparación de usuarios",
        "Una comprobación adicional de cómo cambian los patrones de escucha y el rendimiento cuando el sistema se aplica a historiales distintos.",
        "RÉPLICA",
    )

    if len(usuarios) < 2:
        st.info("Se necesitan al menos dos usuarios del estudio con datos para realizar "
                "esta comparación.")
        return

    st.info(
        "El segundo usuario se utiliza como réplica o comprobación adicional del sistema. "
        "No se interpreta como una segunda validación independiente del modelo principal."
    )

    filas = []
    series_anuales = []
    for usuario in usuarios:
        rec, _ = estado.preparar(usuario)
        ind = rec.indicadores_perfil()
        ev = analitica.evaluacion(usuario)
        mod = analitica.fila_modelo_elegido(ev)
        filas.append({
            "Usuario": usuario,
            "Reproducciones": ind["reproducciones"],
            "Horas": ind["horas"],
            "Artistas": ind["artistas"],
            "Canciones": ind["canciones"],
            "AP": float(mod.get("AP")) if mod is not None and pd.notna(mod.get("AP")) else None,
            "AUC": float(mod.get("AUC")) if mod is not None and pd.notna(mod.get("AUC")) else None,
            "P@20": float(mod.get("P@20")) if mod is not None and pd.notna(mod.get("P@20")) else None,
        })
        anual = (rec.reproducciones.groupby("anio")
                 .agg(horas=("ms_played", lambda s: s.sum() / 3.6e6))
                 .reset_index())
        anual["Usuario"] = usuario
        series_anuales.append(anual)

    tabla = pd.DataFrame(filas)
    st.dataframe(tabla.round({"Horas": 0, "AP": 3, "AUC": 3, "P@20": 2}),
                 width="stretch", hide_index=True)

    izq, der = st.columns(2)
    with izq:
        fig = estilo.figura("Volumen de escucha por usuario", alto=360, barmode="group")
        fig.add_trace(go.Bar(x=tabla.Usuario, y=tabla.Reproducciones,
                             name="Reproducciones", marker_color=estilo.AZUL))
        fig.add_trace(go.Bar(x=tabla.Usuario, y=tabla.Canciones,
                             name="Canciones distintas", marker_color=estilo.VERDE))
        fig.update_layout(yaxis_title="Número de registros", xaxis_title="")
        estilo.grafica(fig)

    with der:
        metricas = [m for m in ["AP", "AUC", "P@20"] if tabla[m].notna().any()]
        fig = estilo.figura("Rendimiento por usuario", alto=360, barmode="group")
        for i, metrica in enumerate(metricas):
            fig.add_trace(go.Bar(x=tabla.Usuario, y=tabla[metrica], name=metrica,
                                 marker_color=estilo.COLORES[i]))
        fig.update_layout(yaxis_title="Valor", xaxis_title="")
        estilo.grafica(fig)

    anual_todo = pd.concat(series_anuales, ignore_index=True)
    fig = estilo.figura("Evolución anual de horas de escucha", alto=380, hovermode="x unified")
    for i, usuario in enumerate(usuarios):
        sub = anual_todo[anual_todo.Usuario == usuario]
        fig.add_trace(go.Scatter(x=sub.anio, y=sub.horas, mode="lines+markers", name=usuario,
                                 line=dict(color=estilo.COLORES[i % len(estilo.COLORES)], width=2.5)))
    fig.update_layout(xaxis_title="Año", yaxis_title="Horas")
    estilo.grafica(fig)

    if len(tabla) >= 2 and tabla.AP.notna().sum() >= 2:
        mejor = tabla.loc[tabla.AP.idxmax()]
        peor = tabla.loc[tabla.AP.idxmin()]
        estilo.interpretacion(
            f"La Average Precision varía entre usuarios: {mejor.Usuario} alcanza {mejor.AP:.3f} "
            f"frente a {peor.AP:.3f} en {peor.Usuario}. La comparación muestra que el rendimiento depende del historial al que se aplica el sistema."
        )
