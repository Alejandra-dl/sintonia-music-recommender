# ============================================================
# Descripción:
# Entrena el modelo de afinidad de un usuario y guarda el modelo
# y sus métricas en su carpeta.
#
# Conviene distinguir esto del notebook 03. Allí se hace el
# estudio: se comparan tres familias de modelos con dos líneas
# base, se buscan los hiperparámetros y se justifica la elección.
# Ese trabajo se hace una vez. Aquí solo se aplica el resultado
# de ese estudio al historial de una persona concreta, que es lo
# que hay que repetir cada vez que entra un usuario nuevo.
#
# Se utiliza en:
# El alta de un usuario, después del ETL y del enriquecimiento.
#
# Entrada:
# El historial limpio del usuario y el catálogo de etiquetas.
#
# Salida:
# dataset_modelado.parquet, modelo_afinidad.pkl y evaluacion.pkl
# en la carpeta del usuario.
#
# Uso:
#   python -m asistente.modelado.entrenar --usuario usuario2
# ============================================================

import argparse
import pickle

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
                             confusion_matrix, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from asistente import config
from asistente.modelado import caracteristicas as ca
from asistente.utilidades import io_datos


def evaluar(y, p, nombre="", repeticiones=200, semilla=config.SEMILLA):
    """Métricas de ranking, deshaciendo los empates al azar.

    Es la misma función que usa el notebook 03. Los empates importan porque las líneas
    base producen muchísimos, y si se deshacen por el orden del fichero, P@k deja de
    medir el modelo.
    """
    y, p = np.asarray(y), np.asarray(p)
    rng = np.random.default_rng(semilla)
    acumulado = {20: [], 50: []}
    for _ in range(repeticiones):
        orden = np.lexsort((rng.random(len(p)), -p))
        for k in acumulado:
            acumulado[k].append(y[orden[:k]].mean())
    return {"Modelo": nombre, "AP": average_precision_score(y, p),
            "AUC": roc_auc_score(y, p),
            "P@20": float(np.mean(acumulado[20])),
            "P@50": float(np.mean(acumulado[50])),
            "Brier": brier_score_loss(y, np.clip(p, 0, 1))}


def metricas_de_clasificacion(y, p, umbral=0.5):
    """Matriz de confusión y métricas de clasificación en un umbral concreto.

    Las métricas de ranking (AP, AUC, P@k) miden cómo ordena el modelo. Estas miden qué
    pasa cuando hay que decidir sí o no, que es otra pregunta. Se incluye la exactitud a
    propósito, aunque no sea la métrica adecuada aquí: con un 15 % de positivos, un modelo
    que dijera siempre que no acertaría el 85 % de las veces y sería inútil. Enseñarla al
    lado de la precisión y la exhaustividad deja claro por qué no se usa para decidir.
    """
    prediccion = (p >= umbral).astype(int)
    vn, fp, fn, vp = confusion_matrix(y, prediccion).ravel()
    return {
        "umbral": umbral,
        "VP": int(vp), "VN": int(vn), "FP": int(fp), "FN": int(fn),
        "exactitud": accuracy_score(y, prediccion),
        "precision": precision_score(y, prediccion, zero_division=0),
        "exhaustividad": recall_score(y, prediccion, zero_division=0),
        "f1": f1_score(y, prediccion, zero_division=0),
    }


def preparar_historial(usuario):
    """Lee el historial del usuario y le pone los nombres de columna del proyecto."""
    rep = io_datos.leer(config.reproducciones(usuario))
    rep["ts_local"] = rep["ts"].dt.tz_convert(config.ZONA_HORARIA)
    rep["artista"] = rep["master_metadata_album_artist_name"]
    rep["cancion"] = rep["master_metadata_track_name"]
    return rep.sort_values("ts_local").reset_index(drop=True)


def entrenar(usuario, usar_contenido=True):
    """Construye el dataset, entrena y guarda. Devuelve la tabla de resultados."""
    rep = preparar_historial(usuario)
    tags = (io_datos.leer(config.TAGS_ARTISTAS)
            if usar_contenido and io_datos.existe(config.TAGS_ARTISTAS) else None)

    X = ca.construir_dataset(rep, tags_artista=tags)
    io_datos.guardar(X, config.dataset_modelado(usuario))
    columnas = ca.columnas_modelo(con_contenido="afinidad_tags" in X.columns)
    entrena, valida, prueba = ca.particion_temporal(
        X, config.CORTE_VALIDACION, config.CORTE_PRUEBA)

    # Se entrena con todo lo anterior al conjunto de prueba: el estudio del notebook 03
    # ya eligió el modelo, así que la validación no vuelve a hacer falta aquí.
    entrenamiento = pd.concat([entrena, valida])
    modelo = Pipeline([
        ("escala", StandardScaler()),
        ("modelo", LogisticRegression(max_iter=3000, class_weight="balanced",
                                      C=config.C_REGULARIZACION,
                                      random_state=config.SEMILLA))])
    modelo.fit(entrenamiento[columnas], entrenamiento.y)
    p_prueba = modelo.predict_proba(prueba[columnas])[:, 1]

    # Las mismas dos líneas base del notebook 03, para poder comparar entre usuarios.
    tabla = pd.DataFrame([
        evaluar(prueba.y, np.full(len(prueba), entrenamiento.y.mean()),
                "Baseline · azar informado"),
        evaluar(prueba.y, prueba.escuchas_previas_artista.values.astype(float),
                "Baseline · familiaridad con el artista"),
        evaluar(prueba.y, p_prueba, "Regresión logística (modelo elegido)"),
    ]).round(4)

    with open(config.modelo_afinidad(usuario), "wb") as fh:
        pickle.dump({"modelo": modelo, "columnas": columnas,
                     "entrenado_hasta": str(entrenamiento.t0.max()),
                     "metricas_prueba": tabla.to_dict("records"),
                     "definicion_objetivo": {"ventana_dias": ca.VENTANA_DIAS,
                                             "min_repeticiones": ca.MIN_REPETICIONES,
                                             "seg_escucha_valida": ca.SEG_ESCUCHA_VALIDA},
                     "semilla": config.SEMILLA}, fh)

    precision, exhaustividad, _ = precision_recall_curve(prueba.y, p_prueba)
    coeficientes = pd.Series(modelo.named_steps["modelo"].coef_[0], index=columnas)

    clasificacion = metricas_de_clasificacion(prueba.y.values, p_prueba)

    # Calibración: se agrupan las predicciones en diez grupos y se compara lo que dijo el
    # modelo con lo que pasó de verdad. La aplicación enseña un porcentaje de afinidad, así
    # que si el número está descalibrado, engaña a quien lo lee.
    diag = prueba.assign(p=p_prueba)
    diag["grupo"] = pd.qcut(diag.p, 10, labels=False, duplicates="drop")
    calibracion = (diag.groupby("grupo")
                       .agg(canciones=("y", "size"), prob_media=("p", "mean"),
                            real=("y", "mean"))
                       .reset_index())
    # Este script no hace selección de modelo: aplica el que eligió el notebook 03. Por eso no
    # existe una validación independiente que enseñar, y las claves de validación se guardan
    # vacías a propósito. Guardar aquí la tabla de prueba bajo el nombre "validación" haría que
    # el cuadro de mando presentara datos de prueba como si fueran de validación.
    with open(config.evaluacion(usuario), "wb") as fh:
        pickle.dump({
            "tabla_validacion": None,
            "tabla_prueba": tabla.to_dict("records"),
            "curvas_pr_validacion": None,
            "curvas_pr_prueba": {"Regresión logística": {
                "precision": precision.tolist(), "exhaustividad": exhaustividad.tolist()}},
            "azar_validacion": None,
            "azar_prueba": float(prueba.y.mean()),
            "origen": "entrenar.py (alta de usuario, sin selección de modelo)",
            "coeficientes": coeficientes.to_dict(),
            "calibracion": calibracion.to_dict("records"),
            "puntuaciones_prueba": p_prueba.tolist(),
            "y_prueba": prueba.y.tolist(),
            # Hiperparámetros heredados del estudio del notebook 03, no buscados aquí.
            "hiperparametros": [{"Modelo": "Regresión logística",
                                 "Mejores hiperparámetros": f"C={config.C_REGULARIZACION} "
                                                            "(heredado del notebook 03)",
                                 "AP en validación cruzada": None, "Segundos": None}],
            "particion": {"entrenamiento": len(entrena), "validacion": len(valida),
                          "prueba": len(prueba),
                          "positivos_entrenamiento": float(entrena.y.mean()),
                          "positivos_validacion": float(valida.y.mean()),
                          "positivos_prueba": float(prueba.y.mean())},
            "variables": columnas,
            "clasificacion": clasificacion,
        }, fh)

    return tabla, len(X), len(columnas), clasificacion


def main():
    ap = argparse.ArgumentParser(description="Entrena el modelo de afinidad de un usuario")
    ap.add_argument("--usuario", default=config.USUARIO)
    ap.add_argument("--sin-contenido", action="store_true",
                    help="entrena solo con variables de comportamiento")
    args = ap.parse_args()

    tabla, filas, n_columnas, clasif = entrenar(
        args.usuario, usar_contenido=not args.sin_contenido)
    print(f"Usuario: {args.usuario}")
    print(f"Dataset: {filas:,} canciones, {n_columnas} variables\n")
    print(tabla.to_string(index=False))
    print(f"\nClasificación en el umbral {clasif['umbral']}:")
    print(f"  VP {clasif['VP']}  VN {clasif['VN']}  FP {clasif['FP']}  FN {clasif['FN']}")
    print(f"  exactitud {clasif['exactitud']:.3f}  precisión {clasif['precision']:.3f}  "
          f"exhaustividad {clasif['exhaustividad']:.3f}  F1 {clasif['f1']:.3f}")
    print(f"\nModelo    → {config.modelo_afinidad(args.usuario)}")
    print(f"Evaluación → {config.evaluacion(args.usuario)}")


if __name__ == "__main__":
    main()
