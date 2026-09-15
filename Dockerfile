# ============================================================
# Descripción:
# Imagen del proyecto. Lleva Python y las librerías, y nada más.
#
# El código NO se copia dentro de la imagen: el docker-compose
# monta la carpeta del proyecto en /proyecto. Así se puede
# cambiar el código sin reconstruir nada, y los datos que se
# generan quedan en el disco del ordenador y no dentro del
# contenedor.
#
# Se utiliza en:
# Los servicios "web" (Flask, 8501), "dashboard" (Streamlit,
# 8502) y "jupyter" (8888) del docker-compose. Los tres
# comparten esta misma imagen y solo cambian el comando.
#
# Entrada:
# requirements.txt
#
# Salida:
# Una imagen con el entorno listo para ejecutar la aplicación,
# el cuadro de mando, los notebooks y los scripts del proyecto.
# ============================================================

FROM python:3.12-slim

WORKDIR /proyecto

# Las dependencias primero: mientras requirements.txt no cambie, Docker
# reutiliza esta capa y reconstruir tarda segundos en vez de minutos.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Dónde están los módulos del proyecto, para poder escribir
# "from asistente.etl import spotify" desde cualquier carpeta.
ENV PYTHONPATH=/proyecto/src
# Dónde está la raíz, que es de donde config.py deduce todas las rutas.
ENV TFM_RAIZ=/proyecto
# Para que los print aparezcan en el momento y no al terminar.
ENV PYTHONUNBUFFERED=1

EXPOSE 8501 8502 8888

# Comando por defecto si se arranca la imagen sin docker-compose: la aplicación
# que se enseña. El compose sobrescribe este comando en cada servicio.
CMD ["flask", "--app", "asistente.web.inicio", "run", "--host", "0.0.0.0", "--port", "8501"]
