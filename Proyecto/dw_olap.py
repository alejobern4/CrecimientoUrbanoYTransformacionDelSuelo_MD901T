"""Consultas OLAP seguras sobre el modelo estrella SQLite."""

import os
import sqlite3
from pathlib import Path


DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
RUTA_BASE = os.path.join(DIRECTORIO, "dw_cobertura.db")
COBERTURA_URBANA = "4.2. Infraestructura urbana"

NIVELES = {
    "territorio": {
        "departamento": "t.departamento",
        "municipio": "t.municipio",
    },
    "tiempo": {
        "decada": "ti.decada",
        "quinquenio": "ti.quinquenio",
        "anio": "ti.anio_fin",
    },
    "origen": {
        "n0": "o.nivel0",
        "n1": "o.nivel1",
        "n2": "o.nivel2",
    },
    "destino": {
        "n0": "d.nivel0",
        "n1": "d.nivel1",
        "n2": "d.nivel2",
    },
}

_SQL_AREA_URBANA = (
    "SUM(CASE WHEN f.es_cambio = 1 "
    f"AND d.nivel2 = '{COBERTURA_URBANA}' THEN f.area_ha ELSE 0 END)"
)
_SQL_PERDIDA_URBANA = (
    "SUM(CASE WHEN f.es_cambio = 1 "
    f"AND o.nivel2 = '{COBERTURA_URBANA}' THEN f.area_ha ELSE 0 END)"
)

MEDIDAS = {
    "area_ha": {
        "nombre": "Área de transición",
        "unidad": "ha",
        "sql": "SUM(f.area_ha)",
        "aditiva": True,
    },
    "area_convertida_ha": {
        "nombre": "Área convertida",
        "unidad": "ha",
        "sql": "SUM(CASE WHEN f.es_cambio = 1 THEN f.area_ha ELSE 0 END)",
        "aditiva": True,
    },
    "ganancia_urbana_ha": {
        "nombre": "Ganancia urbana",
        "unidad": "ha",
        "sql": _SQL_AREA_URBANA,
        "aditiva": True,
    },
    "perdida_urbana_ha": {
        "nombre": "Pérdida urbana",
        "unidad": "ha",
        "sql": _SQL_PERDIDA_URBANA,
        "aditiva": True,
    },
    "ritmo_ganancia_urbana_ha_anio": {
        "nombre": "Ritmo de ganancia urbana",
        "unidad": "ha/año",
        "sql": (
            f"CASE WHEN COUNT(DISTINCT ti.anio_fin) = 0 THEN 0.0 "
            f"ELSE {_SQL_AREA_URBANA} / COUNT(DISTINCT ti.anio_fin) END"
        ),
        "aditiva": False,
    },
    "participacion_ganancia_urbana": {
        "nombre": "Participación en la ganancia urbana",
        "unidad": "%",
        "sql": None,
        "aditiva": False,
    },
    "numero_transiciones": {
        "nombre": "Número de transiciones",
        "unidad": "transiciones",
        "sql": "SUM(CASE WHEN f.es_cambio = 1 THEN 1 ELSE 0 END)",
        "aditiva": True,
    },
    "numero_transiciones_atipicas": {
        "nombre": "Número de transiciones atípicas",
        "unidad": "transiciones",
        "sql": "SUM(CASE WHEN f.es_atipico = 1 THEN 1 ELSE 0 END)",
        "aditiva": True,
    },
    "area_atipica_ha": {
        "nombre": "Área de transiciones atípicas",
        "unidad": "ha",
        "sql": "SUM(CASE WHEN f.es_atipico = 1 THEN f.area_ha ELSE 0 END)",
        "aditiva": True,
    },
    "ganancia_urbana_atipica_ha": {
        "nombre": "Ganancia urbana atípica",
        "unidad": "ha",
        "sql": (
            "SUM(CASE WHEN f.es_cambio = 1 AND f.es_atipico = 1 "
            f"AND d.nivel2 = '{COBERTURA_URBANA}' "
            "THEN f.area_ha ELSE 0 END)"
        ),
        "aditiva": True,
    },
}

_TABLAS = """
    FROM Fact_Transicion_Cobertura AS f
    JOIN Dim_Territorio AS t
        ON t.territorio_key = f.territorio_key
    JOIN Dim_Tiempo AS ti
        ON ti.tiempo_key = f.tiempo_key
    JOIN Dim_CoberturaOrigen AS o
        ON o.origen_key = f.origen_key
    JOIN Dim_CoberturaDestino AS d
        ON d.destino_key = f.destino_key
"""


def _validar_ejes(ejes):
    """Valida ejes y resuelve solo expresiones presentes en la lista blanca."""
    if not isinstance(ejes, (list, tuple)):
        raise ValueError("Los ejes deben ser una lista de pares dimensión:nivel.")
    resultado = []
    vistos = set()
    for eje in ejes:
        if not isinstance(eje, (list, tuple)) or len(eje) != 2:
            raise ValueError("Cada eje debe contener una dimensión y un nivel.")
        dimension, nivel = eje
        if not isinstance(dimension, str) or not isinstance(nivel, str):
            raise ValueError("Dimensión y nivel deben ser texto.")
        if dimension not in NIVELES:
            raise ValueError(f"Dimensión inválida: {dimension!r}.")
        if nivel not in NIVELES[dimension]:
            raise ValueError(
                f"Nivel inválido para {dimension}: {nivel!r}."
            )
        if (dimension, nivel) in vistos:
            raise ValueError(f"El eje {dimension}:{nivel} está repetido.")
        vistos.add((dimension, nivel))
        resultado.append(
            {
                "dimension": dimension,
                "nivel": nivel,
                "expresion": NIVELES[dimension][nivel],
                "alias": f"{dimension}__{nivel}",
            }
        )
    return resultado


def _validar_filtros(filtros):
    """Valida filtros y devuelve sus expresiones y valores parametrizados."""
    if filtros is None:
        filtros = {}
    if not isinstance(filtros, dict):
        raise ValueError("Los filtros deben ser un diccionario.")

    condiciones = []
    parametros = []
    normalizados = []
    for clave, valores in filtros.items():
        if not isinstance(clave, (list, tuple)) or len(clave) != 2:
            raise ValueError("Cada filtro debe usar una clave (dimensión, nivel).")
        dimension, nivel = clave
        if not isinstance(dimension, str) or not isinstance(nivel, str):
            raise ValueError("Dimensión y nivel de filtro deben ser texto.")
        if dimension not in NIVELES:
            raise ValueError(f"Dimensión inválida en filtro: {dimension!r}.")
        if nivel not in NIVELES[dimension]:
            raise ValueError(
                f"Nivel inválido en filtro para {dimension}: {nivel!r}."
            )
        if not isinstance(valores, (list, tuple)) or not valores:
            raise ValueError(
                f"El filtro {dimension}:{nivel} debe incluir al menos un valor."
            )
        if any(not isinstance(valor, (str, int, float)) for valor in valores):
            raise ValueError(f"Valores inválidos para el filtro {dimension}:{nivel}.")

        expresion = NIVELES[dimension][nivel]
        marcadores = ", ".join("?" for _ in valores)
        condiciones.append(f"{expresion} IN ({marcadores})")
        parametros.extend(valores)
        normalizados.append(
            {
                "dimension": dimension,
                "nivel": nivel,
                "valores": list(valores),
            }
        )
    return condiciones, parametros, normalizados


def _uri_solo_lectura(ruta_base):
    """Forma la URI SQLite de solo lectura para la ruta indicada."""
    ruta = Path(ruta_base).resolve()
    return f"{ruta.as_uri()}?mode=ro"


def _abrir_base(ruta_base):
    """Abre la base sin permitir cambios desde las consultas OLAP."""
    if not os.path.isfile(ruta_base):
        raise FileNotFoundError(f"No existe la base SQLite: {ruta_base}")
    conexion = sqlite3.connect(_uri_solo_lectura(ruta_base), uri=True)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA query_only = ON")
    return conexion


def _sql_medida_participacion(ejes):
    """Construye la participación respecto del total del contexto OLAP."""
    particiones = [
        eje["expresion"] for eje in ejes if eje["dimension"] != "origen"
    ]
    particion = (
        f"PARTITION BY {', '.join(particiones)}"
        if particiones
        else ""
    )
    denominador = (
        f"SUM({_SQL_AREA_URBANA}) OVER ({particion})"
    )
    return (
        f"CASE WHEN {denominador} = 0 THEN 0.0 "
        f"ELSE 100.0 * {_SQL_AREA_URBANA} / {denominador} END"
    )


def _consulta_total(conexion, expresion, condiciones, parametros, medida):
    """Calcula el total con una consulta independiente y sin agrupaciones."""
    clausula_where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    if medida == "participacion_ganancia_urbana":
        consulta_sql = (
            f"SELECT CASE WHEN COALESCE({_SQL_AREA_URBANA}, 0) = 0 "
            f"THEN 0.0 ELSE 100.0 END AS valor {_TABLAS} {clausula_where}"
        )
    else:
        consulta_sql = (
            f"SELECT {expresion} AS valor {_TABLAS} {clausula_where}"
        )
    fila = conexion.execute(consulta_sql, parametros).fetchone()
    valor = fila["valor"] if fila is not None else 0
    return 0 if valor is None else valor


def consulta(ejes, medida, filtros=None, solo_cambio=False, total=True):
    """Consulta una medida agregada con filtros validados y valores enlazados."""
    if not isinstance(medida, str):
        raise ValueError("La medida debe ser texto.")
    if medida not in MEDIDAS:
        raise ValueError(f"Medida inválida: {medida!r}.")
    if not isinstance(solo_cambio, bool):
        raise ValueError("solo_cambio debe ser booleano.")
    if not isinstance(total, bool):
        raise ValueError("total debe ser booleano.")

    ejes_validados = _validar_ejes(ejes)
    condiciones, parametros_filtro, filtros_normalizados = _validar_filtros(filtros)
    if solo_cambio:
        condiciones.append("f.es_cambio = 1")
    clausula_where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    expresion = MEDIDAS[medida]["sql"]
    if medida == "participacion_ganancia_urbana":
        expresion = _sql_medida_participacion(ejes_validados)

    selecciones = [
        f'{eje["expresion"]} AS "{eje["alias"]}"'
        for eje in ejes_validados
    ]
    selecciones.append(f"{expresion} AS valor")
    group_by = (
        "GROUP BY " + ", ".join(eje["expresion"] for eje in ejes_validados)
        if ejes_validados
        else ""
    )
    order_by = (
        "ORDER BY " + ", ".join(eje["expresion"] for eje in ejes_validados)
        if ejes_validados
        else ""
    )
    sql = (
        f"SELECT {', '.join(selecciones)} {_TABLAS} "
        f"{clausula_where} {group_by} {order_by}"
    ).strip()
    parametros = list(parametros_filtro)

    conexion = _abrir_base(RUTA_BASE)
    try:
        filas = [
            dict(fila)
            for fila in conexion.execute(sql, parametros).fetchall()
        ]
        valor_total = (
            _consulta_total(
                conexion,
                MEDIDAS[medida]["sql"],
                condiciones,
                parametros_filtro,
                medida,
            )
            if total
            else None
        )
    finally:
        conexion.close()

    return {
        "filas": filas,
        "total": valor_total,
        "sql": sql,
        "parametros": parametros,
        "medida": medida,
        "ejes": [
            {"dimension": eje["dimension"], "nivel": eje["nivel"], "alias": eje["alias"]}
            for eje in ejes_validados
        ],
        "filtros": filtros_normalizados,
        "solo_cambio": solo_cambio,
    }


def pivot(resultado):
    """Presenta dos ejes ya agregados como matriz y consulta sus totales propios."""
    ejes = resultado.get("ejes")
    if not isinstance(ejes, list) or len(ejes) != 2:
        raise ValueError("Pivot requiere exactamente dos ejes agregados.")

    alias_fila = ejes[0]["alias"]
    alias_columna = ejes[1]["alias"]
    filas = resultado["filas"]
    valores_fila = sorted(
        {fila[alias_fila] for fila in filas},
        key=lambda valor: (str(type(valor)), str(valor)),
    )
    valores_columna = sorted(
        {fila[alias_columna] for fila in filas},
        key=lambda valor: (str(type(valor)), str(valor)),
    )
    matriz = {valor_fila: {} for valor_fila in valores_fila}
    for fila in filas:
        matriz[fila[alias_fila]][fila[alias_columna]] = fila["valor"]

    filtros = {
        (filtro["dimension"], filtro["nivel"]): filtro["valores"]
        for filtro in resultado.get("filtros", [])
    }
    medida = resultado["medida"]
    solo_cambio = resultado.get("solo_cambio", False)
    totales_fila = consulta(
        [(ejes[0]["dimension"], ejes[0]["nivel"])],
        medida,
        filtros=filtros,
        solo_cambio=solo_cambio,
    )
    totales_columna = consulta(
        [(ejes[1]["dimension"], ejes[1]["nivel"])],
        medida,
        filtros=filtros,
        solo_cambio=solo_cambio,
    )
    total_general = consulta(
        [],
        medida,
        filtros=filtros,
        solo_cambio=solo_cambio,
    )
    return {
        "filas": valores_fila,
        "columnas": valores_columna,
        "matriz": matriz,
        "total_por_fila": {
            fila[alias_fila]: fila["valor"]
            for fila in totales_fila["filas"]
        },
        "total_por_columna": {
            fila[totales_columna["ejes"][0]["alias"]]: fila["valor"]
            for fila in totales_columna["filas"]
        },
        "total_general": total_general["total"],
    }
