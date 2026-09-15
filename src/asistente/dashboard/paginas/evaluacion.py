"""Evaluación analítica del modelo y comparación con líneas base."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from asistente.dashboard import analitica, estilo
from asistente.dashboard.estado import usuario_actual


def _modelo_elegido(tabla):
    if tabla.empty:
        return None
    mask = tabla.Modelo.astype(str).str.contains("elegido|logística", case=False, regex=True)
    return tabla[mask].iloc[0] if mask.any() else tabla.iloc[-1]


def mostrar():
    usuario = usuario_actual()
    ev = analitica.evaluacion(usuario)

    estilo.cabecera(
        "Evaluación del modelo",
        "Rendimiento en prueba, comparación con líneas base, calibración, errores y peso de las variables.",
        "MACHINE LEARNING",
    )

    if not ev:
        st.info("No hay resultados de evaluación guardados para este usuario.")
        return

    tabla = pd.DataFrame(ev.get("tabla_prueba", []))
    if tabla.empty or "Modelo" not in tabla:
        st.info("El archivo de evaluación no contiene una tabla de prueba utilizable.")
        return

    elegido = _modelo_elegido(tabla)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Average Precision", f"{float(elegido.get('AP', np.nan)):.3f}")
    c2.metric("ROC-AUC", f"{float(elegido.get('AUC', np.nan)):.3f}")
    c3.metric("Precision@20", f"{float(elegido.get('P@20', np.nan)):.2f}")
    c4.metric("Precision@50", f"{float(elegido.get('P@50', np.nan)):.2f}")

    particion = ev.get("particion", {})
    if particion:
        st.caption(
            "Conjunto de prueba: "
            f"{estilo.miles(particion.get('prueba', 0))} canciones · "
            f"{particion.get('positivos_prueba', 0) * 100:.1f} % de positivos. "
            "La separación es temporal: el modelo aprende del pasado y se mide sobre datos posteriores."
        )

    st.subheader("Modelo frente a líneas base")
    metricas = [m for m in ["AP", "AUC", "P@20", "P@50"] if m in tabla.columns]
    # Igual que en la visión general: etiquetas partidas para que los nombres
    # completos de los modelos quepan, y el valor escrito sobre cada barra.
    etiquetas = [estilo.envolver(m) for m in tabla.Modelo]
    fig = estilo.figura("Comparación de métricas en prueba", alto=410, barmode="group")
    for i, metrica in enumerate(metricas):
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

    if "AP" in tabla:
        base = tabla[tabla.Modelo.astype(str).str.contains("familiaridad", case=False)]
        if len(base):
            mejora = float(elegido.AP) - float(base.iloc[0].AP)
            estilo.interpretacion(
                f"El modelo elegido obtiene una Average Precision de {float(elegido.AP):.3f}; "
                f"la diferencia frente a la línea base de familiaridad es de {mejora:+.3f}."
            )

    st.divider()
    izq, der = st.columns(2)

    with izq:
        curvas = ev.get("curvas_pr_validacion") or ev.get("curvas_pr_prueba") or {}
        azar = ev.get("azar_validacion")
        if azar is None:
            azar = ev.get("azar_prueba")
        fig = estilo.figura("Curvas Precision-Recall", alto=390,
                            legend=dict(orientation="h", y=-0.23, x=0))
        for i, (nombre, curva) in enumerate(curvas.items()):
            if not curva:
                continue
            x = curva.get("exhaustividad")
            if x is None:
                x = curva.get("recall")
            y = curva.get("precision")
            if x is None or y is None:
                continue
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=nombre,
                                     line=dict(color=estilo.COLORES[i % len(estilo.COLORES)], width=2.5)))
        if azar is not None:
            fig.add_hline(y=float(azar), line=dict(color=estilo.APAGADO, dash="dot", width=1.3))
        fig.update_layout(xaxis_title="Exhaustividad", yaxis_title="Precisión")
        estilo.grafica(fig)

    with der:
        calibracion = pd.DataFrame(ev.get("calibracion", []))
        if not calibracion.empty and {"grupo", "real", "prob_media"}.issubset(calibracion.columns):
            fig = estilo.figura("Calibración: predicho frente a observado", alto=390,
                                legend=dict(orientation="h", y=-0.23, x=0))
            fig.add_trace(go.Bar(x=calibracion.grupo + 1, y=calibracion.real * 100,
                                 name="Observado", marker_color=estilo.VERDE))
            fig.add_trace(go.Scatter(x=calibracion.grupo + 1, y=calibracion.prob_media * 100,
                                     mode="lines+markers", name="Predicho",
                                     line=dict(color=estilo.NARANJA, width=2.5)))
            fig.update_layout(xaxis_title="Grupos de probabilidad", yaxis_title="Positivos (%)")
            estilo.grafica(fig)
        else:
            st.info("No hay información de calibración disponible.")

    estilo.interpretacion(
        "Las curvas Precision-Recall muestran la relación entre precisión y exhaustividad a distintos umbrales. "
        "La calibración comprueba si las probabilidades estimadas se parecen a la frecuencia observada de positivos."
    )

    st.divider()
    st.subheader("Errores de clasificación")
    clas = ev.get("clasificacion")
    y = np.asarray(ev.get("y_prueba", []), dtype=float)
    p = np.asarray(ev.get("puntuaciones_prueba", []), dtype=float)
    if clas:
        matriz = np.array([[clas.get("VN", 0), clas.get("FP", 0)],
                           [clas.get("FN", 0), clas.get("VP", 0)]])
        e1, e2 = st.columns([1, 1.25])
        with e1:
            fig = estilo.figura("Matriz de confusión", alto=350)
            fig.add_trace(go.Heatmap(z=matriz,
                                     x=["Predice no", "Predice sí"],
                                     y=["Real no", "Real sí"],
                                     text=matriz, texttemplate="%{text}",
                                     colorscale=estilo.ESCALA_CALOR,
                                     showscale=False))
            fig.update_yaxes(autorange="reversed")
            estilo.grafica(fig)
        with e2:
            categorias = pd.Series({
                "Verdaderos negativos": clas.get("VN", 0),
                "Falsos positivos": clas.get("FP", 0),
                "Falsos negativos": clas.get("FN", 0),
                "Verdaderos positivos": clas.get("VP", 0),
            })
            fig = estilo.figura("Distribución de aciertos y errores", alto=350)
            fig.add_trace(go.Bar(x=categorias.index, y=categorias.values,
                                 marker_color=[estilo.AZUL, estilo.ROJO, estilo.NARANJA, estilo.VERDE]))
            fig.update_layout(yaxis_title="Canciones", xaxis_title="")
            estilo.grafica(fig)
        estilo.interpretacion(
            f"Con el umbral {clas.get('umbral', 0.5):.2f}, la precisión es "
            f"{clas.get('precision', 0):.3f} y la exhaustividad {clas.get('exhaustividad', 0):.3f}. "
            "Estas métricas describen la decisión binaria; AP, AUC y Precision@k siguen siendo las referencias principales para evaluar el ranking."
        )
    elif len(y) and len(p) and len(y) == len(p):
        pred = (p >= 0.5).astype(int)
        categorias = pd.crosstab(pd.Series(y.astype(int), name="Real"), pd.Series(pred, name="Predicción"))
        st.dataframe(categorias, width="stretch")
    else:
        st.info("No hay datos suficientes para reconstruir el análisis de errores.")

    if len(y) and len(p) and len(y) == len(p):
        df_scores = pd.DataFrame({"Puntuación": p, "Clase": np.where(y == 1, "Se quedó", "No se quedó")})
        fig = estilo.figura("Distribución de puntuaciones por clase real", alto=350, barmode="overlay")
        for clase, color in [("Se quedó", estilo.VERDE), ("No se quedó", estilo.AZUL)]:
            sub = df_scores[df_scores.Clase == clase]
            fig.add_trace(go.Histogram(x=sub["Puntuación"], nbinsx=30, opacity=.62,
                                       name=clase, marker_color=color))
        fig.update_layout(xaxis_title="Puntuación del modelo", yaxis_title="Canciones")
        estilo.grafica(fig)

    st.divider()
    st.subheader("Variables y ablación")
    izq, der = st.columns(2)
    with izq:
        coef = pd.Series(ev.get("coeficientes", {}), dtype=float).sort_values()
        if len(coef):
            fig = estilo.figura("Coeficientes del modelo", alto=max(390, 25 * len(coef)))
            colores = [estilo.ROJO if v < 0 else estilo.VERDE for v in coef.values]
            fig.add_trace(go.Bar(x=coef.values, y=coef.index, orientation="h", marker_color=colores))
            fig.add_vline(x=0, line=dict(color=estilo.APAGADO, width=1))
            fig.update_layout(xaxis_title="Efecto sobre la afinidad", yaxis_title="")
            estilo.grafica(fig)
        else:
            st.info("No hay coeficientes guardados.")

    with der:
        ab = analitica.ablacion(usuario)
        if ab and ab.get("tabla"):
            tabla_ab = pd.DataFrame(ab["tabla"])
            if "AP prueba" in tabla_ab:
                fig = estilo.figura("Ablación por bloques de variables", alto=390)
                fig.add_trace(go.Bar(x=tabla_ab["Conjunto de variables"], y=tabla_ab["AP prueba"],
                                     marker_color=estilo.VIOLETA))
                fig.update_layout(yaxis_title="Average Precision en prueba", xaxis_title="")
                estilo.grafica(fig)
            else:
                st.dataframe(tabla_ab, width="stretch", hide_index=True)
        else:
            st.info("No hay resultados de ablación guardados para este usuario.")

    ds = analitica.dataset_modelado(usuario)
    if ds is not None and "y" in ds.columns:
        st.subheader("Distribución de la variable objetivo")
        dist = ds.y.value_counts().sort_index()
        fig = estilo.figura("Canciones que se quedaron frente a las que no", alto=320)
        etiquetas = ["No se quedó" if int(i) == 0 else "Se quedó" for i in dist.index]
        fig.add_trace(go.Bar(x=etiquetas, y=dist.values, marker_color=[estilo.AZUL, estilo.VERDE][:len(dist)]))
        fig.update_layout(yaxis_title="Canciones", xaxis_title="")
        estilo.grafica(fig)
        positivos = float(ds.y.mean() * 100)
        estilo.interpretacion(
            f"La clase positiva representa el {positivos:.1f} % del dataset de modelado. "
            "El desequilibrio ayuda a entender por qué la evaluación se centra en métricas de ranking y no únicamente en exactitud."
        )
