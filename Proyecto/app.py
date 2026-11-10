import json
import os

from flask import Flask, jsonify, render_template, request

if __package__:
    from .dw_olap import consulta, pivot
else:
    from dw_olap import consulta, pivot

app = Flask(__name__)
DIRECTORIO = os.path.dirname(os.path.abspath(__file__))

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