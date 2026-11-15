import json
import os

from flask import Flask, jsonify, render_template, request, url_for

if __package__:
    from .dw_olap import consulta, pivot
else:
    from dw_olap import consulta, pivot

app = Flask(__name__)
DIRECTORIO = os.path.dirname(os.path.abspath(__file__))

# Completar con los enlaces públicos cuando estén disponibles.
VIDEO_SUSTENTACION_EMBED = None
VIDEO_SUSTENTACION_ENLACE = None
REPO_URL = None

HALLAZGOS = {
    "tema": "Crecimiento urbano y transformación del uso del suelo",
    "alcance": "200 ciudades del conjunto global y 64 comentarios de un video sobre ordenamiento territorial. Son fuentes diferentes y no representan la misma población.",
    "supervisado": {
        "pregunta": "¿Qué tan bien puede estimarse la superficie urbana construida en T3 a partir de datos de T1 y T2?",
        "tipo": "Regresión con tres algoritmos sobre 200 registros de ciudades.",
        "objetivo": "Urban_Built_up_Area_ha_T3 (hectáreas)",
        "predictoras": "Superficie urbana construida T1/T2; población T1/T2; densidad, apertura, proximidad y cohesión T2.",
        "validacion": "Validación cruzada de 5 particiones; preprocesamiento ajustado durante el entrenamiento de cada partición.",
        "columnas": ["MAE (ha)", "RMSE (ha)", "R²"],
        "modelos": [
            {"nombre": "Linear Regression", "valores": ["10.448,877", "19.825,601", "0,939"], "elegido": True},
            {"nombre": "Random Forest", "valores": ["13.726,024", "31.817,033", "0,842"], "elegido": False},
            {"nombre": "Tree", "valores": ["15.839,307", "38.463,909", "0,769"], "elegido": False},
        ],
        "modelo_elegido": "Linear Regression",
        "justificacion": "Obtuvo el menor MAE y RMSE y el mayor R² bajo la evaluación utilizada. Es la mejor alternativa de las tres para esta muestra, no una garantía de pronóstico futuro.",
        "comparacion": [
            {"nombre": "8 variables", "mae": "10.448,877", "rmse": "19.825,601", "r2": "0,939"},
            {"nombre": "Solo superficies T1 y T2", "mae": "11.858,608", "rmse": "24.304,514", "r2": "0,908"},
        ],
        "hallazgos": [
            "El modelo completo reduce aproximadamente 11,9 % el MAE y 18,4 % el RMSE frente a la variante con solo superficies históricas.",
            "En Rank, la superficie construida T2 destacó en Univariate Regression; población T2 (0,091) y apertura T2 (0,087) encabezaron RReliefF.",
            "Los errores varían por ciudad: en Cairo la regresión lineal estimó 72.698,8 ha frente a 74.782 ha reales, mientras que en Beijing subestimó 35.584 ha.",
            "Se observaron predicciones lineales físicamente imposibles: −4.976,63 ha para Belgaum y −4.408,19 ha para Hong Kong.",
        ],
        "limitaciones": [
            "El MAE del mejor modelo todavía equivale a unas 10.449 hectáreas y algunas predicciones son negativas.",
            "T1, T2 y T3 no corresponden necesariamente a las mismas fechas en todas las ciudades. La validación cruzada entre ciudades no prueba pronósticos temporales futuros.",
            "El R² alto puede reflejar el tamaño urbano histórico; falta comparar con la referencia T3 = T2. No se infieren relaciones causales.",
        ],
    },
    "clustering": {
        "pregunta": "¿Qué perfiles de organización urbana aparecen según densidad, apertura, proximidad, cohesión y saturación en T2?",
        "algoritmo": "K-Means con KMeans++, 10 reinicios, máximo de 5.000 iteraciones y normalización activada. Se compararon K = 2 a 6.",
        "variables": "Densidad de personas en área construida, apertura, proximidad, cohesión y saturación del área construida, todos en T2; sin usar el objetivo supervisado de T3.",
        "comparacion_k": [
            {"k": 2, "silhouette": "0,299", "elegido": True},
            {"k": 3, "silhouette": "0,298", "elegido": False},
            {"k": 4, "silhouette": "0,275", "elegido": False},
            {"k": 5, "silhouette": "0,250", "elegido": False},
            {"k": 6, "silhouette": "0,255", "elegido": False},
        ],
        "grupos": [
            {
                "nombre": "C1 · Perfil relativamente compacto y cohesionado",
                "desc": "Mayor proximidad, cohesión y saturación, con menor índice de apertura que C2. Denominación interpretativa sujeta a la definición oficial de los índices.",
                "datos": ["Proximidad estandarizada: 0,545", "Cohesión: 0,539", "Saturación: 0,514", "Apertura: −0,535", "Densidad: −0,103", "Silhouette del grupo: ≈ 0,403"],
                "ejemplos": "Gorgan, Rovno, Tebessa, Culiacán y Ciudad de México (altos valores silhouette); Bogotá también pertenece a C1.",
            },
            {
                "nombre": "C2 · Perfil relativamente abierto y fragmentado",
                "desc": "Mayor apertura y menores proximidad, cohesión y saturación. Presenta separación interna menos clara.",
                "datos": ["Proximidad estandarizada: −0,707", "Cohesión: −0,700", "Saturación: −0,668", "Apertura: 0,695", "Densidad: 0,134", "Silhouette del grupo: ≈ 0,163"],
                "ejemplos": "Qingdao, Hangzhou, Medan, Kayseri y Yucheng (altos valores silhouette; verificar nombres truncados).",
            },
        ],
        "significancia": "La densidad es menos diferenciadora que los cuatro indicadores espaciales. Las pruebas t sobre variables usadas para formar los clusters son descriptivas, no validaciones independientes.",
        "nota": "Silhouette global de 0,299: separación limitada; K = 3 obtuvo prácticamente el mismo valor (0,298). El conteo exacto por grupo no fue confirmado; no se publican estimaciones como si fueran exactas.",
    },
    "fuente": {
        "video": "https://www.youtube.com/watch?v=-5PdZK1WO3s",
        "comentarios": 64,
        "api": "YouTube Data API v3",
        "fecha_extraccion": None,
        "nota_fecha": "Fecha de extracción pendiente de verificación: se había indicado 29/08/2026, pero el archivo contiene comentarios publicados hasta el 05/10/2026.",
        "calidad": "64 filas, 8 columnas; sin celdas vacías ni textos idénticos duplicados en el CSV recibido. No se ha descartado duplicación semántica.",
    },
    "texto": {
        "pregunta": "¿Qué usos, preguntas y percepciones aparecen en los comentarios del video y cómo complementan el análisis territorial?",
        "categorias": [
            {"nombre": "Ruido", "cantidad": 23, "porcentaje": "35,9 %"},
            {"nombre": "Valoración del video", "cantidad": 21, "porcentaje": "32,8 %"},
            {"nombre": "Tarea escolar", "cantidad": 13, "porcentaje": "20,3 %"},
            {"nombre": "Temático (etiqueta provisional)", "cantidad": 7, "porcentaje": "10,9 %"},
        ],
        "metodo": "Corpus → Preprocess Text → Word Cloud / Corpus Viewer y Bag of Words → Topic Modelling (LDA). Se probaron 10 y 3 temas.",
        "resumen": "Predominan referencias a tareas, profesores, exámenes, agradecimientos y valoraciones. Los asuntos de POT, Ley 388, propiedad y recursos naturales aparecen en pocos textos. LDA con 3 temas sintetizó uso escolar, interacción y valoración, pero no aisló un tema territorial independiente.",
        "hallazgos": [
            "Solo 7 de 64 comentarios (10,9 %) fueron etiquetados como temáticos; algunas etiquetas deben revisarse por ambigüedad.",
            "Los temáticos tienen 22,43 palabras de media, frente a 9,69 de tareas escolares, 6,19 de valoraciones y 4,30 de ruido.",
            "El comentario con más likes (149) se refiere a un trabajo de sociales, no a un debate sobre transformación urbana.",
            "Aparecen preguntas sobre acceso a información del POT y opiniones acerca de propiedad, gobierno y recursos naturales; no constituyen hechos jurídicos o territoriales comprobados.",
        ],
        "limitaciones": [
            "Un solo video y 64 comentaristas/registros no representan a las poblaciones o ciudades estudiadas.",
            "Mensajes breves, errores ortográficos y contenido multilingüe dificultan LDA; diez temas repitieron términos y tres siguieron mezclando asuntos.",
            "Revisar el criterio de etiquetado, la fecha real de extracción y los detalles del script/API antes de publicar.",
        ],
    },
    "conclusiones": {
        "evidencia": [
            "Linear Regression fue el modelo con mejores métricas de regresión entre los tres evaluados, pero presentó errores grandes y algunas áreas negativas.",
            "Las variables demográficas y espaciales mejoraron conjuntamente la estimación de T3 frente al uso exclusivo de las superficies T1 y T2.",
            "K-Means identificó dos perfiles espaciales exploratorios; las diferencias son más claras en apertura, cohesión, proximidad y saturación que en densidad.",
            "En YouTube predominan comentarios escolares y valoraciones; la discusión territorial explícita es minoritaria según las etiquetas actuales.",
        ],
        "hipotesis": [
            "Los indicadores espaciales podrían ayudar a predecir incrementos de superficie, no solo el tamaño final; requiere otro objetivo o línea base.",
            "Los perfiles C1/C2 podrían reflejar procesos distintos de expansión; requiere validar los índices y estudiar la evolución posterior.",
            "Otros videos, con audiencias menos escolares, podrían aportar más opiniones sustantivas sobre ordenamiento territorial.",
        ],
        "limitaciones": "No existe correspondencia directa entre las 200 ciudades globales y las personas que comentaron el video; los comentarios no validan las predicciones ni los clusters.",
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
        "etapa6.html", h=HALLAZGOS, informe_url=informe_url,
        video_embed=VIDEO_SUSTENTACION_EMBED,
        video_enlace=VIDEO_SUSTENTACION_ENLACE, repo_url=REPO_URL,
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
        raise ValueError("Cada filtro debe tener el formato dimensión:nivel=valor1,valor2.")
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
        resultado = consulta(ejes, valores_medida[0], filtros=filtros, solo_cambio=solo_cambio)
        if usar_pivot:
            resultado["pivot"] = pivot(resultado)
        return jsonify(resultado)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        app.logger.exception("Error interno al ejecutar una consulta OLAP.")
        return jsonify({"error": "No fue posible consultar el modelo OLAP."}), 500