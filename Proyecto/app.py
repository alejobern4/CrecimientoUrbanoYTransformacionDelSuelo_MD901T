import json
import os

from flask import Flask, jsonify, render_template, request, url_for

if __package__:
    from .dw_olap import consulta, pivot
else:
    from dw_olap import consulta, pivot

app = Flask(__name__)
DIRECTORIO = os.path.dirname(os.path.abspath(__file__))

VIDEO_SUSTENTACION_EMBED = None
VIDEO_SUSTENTACION_ENLACE = None
REPO_URL = None

HALLAZGOS = {
    "tema": "Crecimiento urbano y transformación del uso del suelo",
    "fuente": {
        "video": "https://www.youtube.com/watch?v=-5PdZK1WO3s",
        "comentarios": 64,
        "fecha_extraccion": "2026-08-29",
    },
    "supervisado": {
        "pregunta": "¿Se puede predecir si un comentario del video trata sobre el crecimiento urbano y la transformación del uso del suelo?",
        "tipo": "Clasificación supervisada de comentarios utilizando técnicas de procesamiento de lenguaje natural.",
        "objetivo": "Identificar comentarios relacionados con el crecimiento urbano y la transformación del uso del suelo dentro de los comentarios del video.",
        "predictoras": "Contenido textual de los comentarios procesado mediante limpieza de texto, Bag of Words y representación vectorial.",
        "datos": "64 comentarios únicos extraídos del video de YouTube.",
        "validacion": "Validación cruzada estratificada de 5 folds, igual para los tres modelos.",
        "columnas": [
            "Accuracy",
            "F1 promedio",
            "F1 (temático)",
            "Recall (temático)",
            "Temáticos acertados",
        ],
        "modelos": [
            {
                "nombre": "Naive Bayes",
                "valores": ["0.891", "0.000", "0.000", "0.000", "0 / 7"],
                "elegido": False,
            },
            {
                "nombre": "Logistic Regression",
                "valores": ["0.953", "0.727", "0.727", "0.571", "4 / 7"],
                "elegido": True,
            },
            {
                "nombre": "Random Forest",
                "valores": ["0.891", "0.000", "0.000", "0.000", "0 / 7"],
                "elegido": False,
            },
        ],
        "modelo_elegido": "Logistic Regression",
        "justificacion": "La Regresión Logística fue el único modelo capaz de identificar correctamente comentarios de la categoría temática. Detectó 4 de los 7 comentarios relacionados con crecimiento urbano, ordenamiento territorial, POT y recursos naturales, obteniendo un Recall de 0.571 y un F1 de 0.727. En comparación, Naive Bayes y Random Forest no lograron clasificar correctamente ningún comentario temático.",
        "limitaciones": "Solo 7 comentarios tratan directamente el tema frente a 57 comentarios de otras categorías. El tamaño reducido del conjunto de datos y el desbalance entre clases limitan la capacidad de generalización de los modelos y pueden afectar la estabilidad de las métricas.",
    },
    "clustering": {
        "pregunta": "¿Qué perfiles de comentarios aparecen en el video sobre crecimiento urbano y uso del suelo, según su extensión, antigüedad e interacción?",
        "algoritmo": "k-Means (KMeans++, 10 re-ejecuciones), variables estandarizadas (longitud, palabras, año y likes), k = 2 (silhouette 0,591; con k = 3 a 6 quedó entre 0,43 y 0,46).",
        "nota": "Se excluyó un comentario atípico (149 likes) porque formaba un grupo de un solo registro. Los tamaños y medias son aproximados.",
        "grupos": [
            {
                "nombre": "Reacciones breves",
                "desc": "Saludos, emojis, agradecimientos y valoraciones cortas. Son la gran mayoría.",
                "datos": [
                    "Comentarios: ≈ 56",
                    "Palabras (media): ≈ 5",
                    "Caracteres (media): ≈ 27",
                    "Likes (media): ≈ 2,3",
                    "Año (media): ≈ 2021,9",
                ],
            },
            {
                "nombre": "Comentarios extensos",
                "desc": "Opiniones y preguntas más elaboradas. Incluyen varios de los comentarios sobre el POT, el gobierno y los recursos naturales. Son pocos y más antiguos.",
                "datos": [
                    "Comentarios: ≈ 7",
                    "Palabras (media): ≈ 31",
                    "Caracteres (media): ≈ 176",
                    "Likes (media): ≈ 8,9",
                    "Año (media): ≈ 2020,4",
                ],
            },
        ],
        "significancia": "La diferencia en longitud, número de palabras y año es significativa (p ≤ 0,002); la de likes no (p = 0,066).",
    },
    "texto": {
        "resumen": "El análisis de texto de Orange mostró una estructura clara: la mayoría de los comentarios son breves o de tipo escolar, mientras que un conjunto menor refleja intereses sobre el POT, la Ley 388, la propiedad y los recursos naturales. El sentimiento general no es dominante y la evidencia temática está concentrada en unos pocos mensajes más largos y específicos.",
    },
    "conclusiones": {
        "evidencia": [
            "La mayoría de los comentarios son reacciones breves o de tarea escolar, no opiniones sobre el territorio.",
            "Solo 7 de 64 comentarios tratan el crecimiento urbano y el uso del suelo, y se publicaron entre 2020 y 2024.",
        ],
        "hipotesis": [
            "Quienes sí opinan sobre el tema podrían tener un interés real por el POT; requiere más videos y más datos.",
            "El patrón podría cambiar en videos que no sean de uso escolar.",
        ],
    },
}


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/etapa1")
def etapa1():
    return render_template("etapa1.html")

@app.route("/etapa2")
def etapa2():
    return render_template("etapa2.html")

@app.route("/etapa3")
def etapa3():
    return render_template("etapa3.html")

@app.route("/etapa4")
def etapa4():
    return render_template("etapa4.html")


@app.route("/etapa5")
def etapa5():
    ruta_verificaciones = os.path.join(DIRECTORIO, "verificaciones.json")
    try:
        with open(ruta_verificaciones, encoding="utf-8") as archivo:
            verificaciones = json.load(archivo)
    except FileNotFoundError:
        verificaciones = None
    except (OSError, json.JSONDecodeError):
        app.logger.exception("No se pudo leer Proyecto/verificaciones.json.")
        return "No se pudieron leer las verificaciones de Etapa 5.", 500

    if verificaciones is not None and not isinstance(verificaciones, list):
        app.logger.error("verificaciones.json no contiene una lista de comprobaciones.")
        return "El archivo de verificaciones de Etapa 5 no tiene un formato válido.", 500
    return render_template("etapa5.html", verificaciones=verificaciones)


@app.route("/etapa6")
@app.route("/conocimiento-oculto")
def etapa6():
    informe_rel = "docs/informe_tecnico.pdf"
    informe_path = os.path.join(app.static_folder, informe_rel)
    informe_url = url_for("static", filename=informe_rel) if os.path.isfile(informe_path) else None
    return render_template(
        "etapa6.html",
        h=HALLAZGOS,
        informe_url=informe_url,
        video_embed=VIDEO_SUSTENTACION_EMBED,
        video_enlace=VIDEO_SUSTENTACION_ENLACE,
        repo_url=REPO_URL,
    )


def _leer_eje(valor):
    """Interpreta un eje de consulta con el formato dimensión:nivel."""
    partes = valor.split(":")
    if len(partes) != 2 or not all(partes):
        raise ValueError("Cada eje debe tener el formato dimensión:nivel.")
    return partes[0], partes[1]


def _leer_filtro(valor):
    """Interpreta un filtro repetible con el formato dimensión:nivel=valor1,valor2."""
    clave, separador, valores = valor.partition("=")
    if not separador or not valores:
        raise ValueError(
            "Cada filtro debe tener el formato dimensión:nivel=valor1,valor2."
        )
    dimension, nivel = _leer_eje(clave)
    lista_valores = [elemento.strip() for elemento in valores.split(",")]
    if not all(lista_valores):
        raise ValueError(f"El filtro {dimension}:{nivel} contiene un valor vacío.")
    return (dimension, nivel), lista_valores


def _leer_booleano(nombre):
    """Lee un parámetro opcional representado por 1/0 o true/false."""
    valores = request.args.getlist(nombre)
    if len(valores) > 1:
        raise ValueError(f"El parámetro {nombre} no se puede repetir.")
    if not valores:
        return False
    valor = valores[0].casefold()
    if valor in ("1", "true"):
        return True
    if valor in ("0", "false"):
        return False
    raise ValueError(f"El parámetro {nombre} debe ser 1 o 0.")


@app.route("/api/olap", methods=["GET"])
def api_olap():
    try:
        valores_medida = request.args.getlist("medida")
        if len(valores_medida) != 1 or not valores_medida[0]:
            raise ValueError("Se requiere un único parámetro medida.")

        ejes = [_leer_eje(valor) for valor in request.args.getlist("eje")]
        filtros = {}
        for valor in request.args.getlist("filtro"):
            clave, lista_valores = _leer_filtro(valor)
            filtros.setdefault(clave, []).extend(lista_valores)

        solo_cambio = _leer_booleano("solo_cambio")
        usar_pivot = _leer_booleano("pivot")
        resultado = consulta(
            ejes,
            valores_medida[0],
            filtros=filtros,
            solo_cambio=solo_cambio,
        )
        if usar_pivot:
            resultado["pivot"] = pivot(resultado)
        return jsonify(resultado)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        app.logger.exception("Error interno al ejecutar una consulta OLAP.")
        return jsonify({"error": "No fue posible consultar el modelo OLAP."}), 500