"""Compara de forma independiente el Excel tratado con el modelo SQLite."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd


DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
RUTA_BASE = os.path.join(DIRECTORIO, "dw_cobertura.db")
RUTA_RESULTADOS = os.path.join(DIRECTORIO, "verificaciones.json")
HOJA_ORIGEN = "Regional_SabanaCentro_Anual"
TOLERANCIA_HA = 0.05
AREA_URBANA = "4.2. Infraestructura urbana"
COLUMNAS_ORIGEN = (
    "municipio",
    "departamento",
    "pais",
    "class_level_0_from",
    "class_level_1_from",
    "class_level_2_from",
    "class_level_0_to",
    "class_level_1_to",
    "class_level_2_to",
    "class_from",
    "class_to",
    "periodo",
    "anio_inicio",
    "anio_fin",
    "area_ha",
    "es_atipico_tukey",
)

CONTROL_DECADAS = {
    "1980-1989": 217.3,
    "1990-1999": 1029.5,
    "2000-2009": 1693.9,
    "2010-2019": 1918.7,
    "2020-2029": 1220.8,
}


def numero(valor):
    """Redondea cifras para su representación reproducible en JSON."""
    return round(float(valor), 6)


def json_nativo(valor):
    """Convierte valores de pandas/numpy en valores serializables por JSON."""
    if isinstance(valor, dict):
        return {str(clave): json_nativo(contenido) for clave, contenido in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [json_nativo(contenido) for contenido in valor]
    if pd.isna(valor):
        return None
    if isinstance(valor, (int, float)):
        return numero(valor) if isinstance(valor, float) else int(valor)
    if hasattr(valor, "item"):
        return json_nativo(valor.item())
    return valor


def texto(valor):
    """Normaliza categorías para comparar el Excel con las dimensiones."""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def etiqueta_quinquenio(anio_fin):
    """Deriva la etiqueta de quinquenio definida para la dimensión de tiempo."""
    if pd.isna(anio_fin) or not float(anio_fin).is_integer():
        return None
    base = (int(anio_fin) // 5) * 5
    return f"{base}-{base + 4}"


def etiqueta_decada(anio_fin):
    """Deriva la etiqueta de década definida para la dimensión de tiempo."""
    if pd.isna(anio_fin) or not float(anio_fin).is_integer():
        return None
    base = (int(anio_fin) // 10) * 10
    return f"{base}-{base + 9}"


def leer_excel(ruta_origen):
    """Carga las columnas necesarias y devuelve su representación normalizada."""
    if not os.path.isfile(ruta_origen):
        raise FileNotFoundError(f"No existe el archivo de origen: {ruta_origen}")
    datos = pd.read_excel(
        ruta_origen,
        sheet_name=HOJA_ORIGEN,
        engine="openpyxl",
    )
    faltantes = [columna for columna in COLUMNAS_ORIGEN if columna not in datos]
    if faltantes:
        raise ValueError(
            "Faltan columnas requeridas en la hoja "
            f"{HOJA_ORIGEN}: {', '.join(faltantes)}."
        )

    datos = datos.loc[:, COLUMNAS_ORIGEN].copy()
    columnas_texto = (
        "municipio",
        "departamento",
        "pais",
        "class_level_0_from",
        "class_level_1_from",
        "class_level_2_from",
        "class_level_0_to",
        "class_level_1_to",
        "class_level_2_to",
        "class_from",
        "class_to",
        "periodo",
    )
    nulos_origen = int(datos.isna().sum().sum())
    nulos_origen += sum(
        int(datos[columna].map(lambda valor: isinstance(valor, str) and not valor.strip()).sum())
        for columna in columnas_texto
    )
    for columna in columnas_texto:
        datos[columna] = datos[columna].map(texto)
    for columna in ("area_ha", "anio_inicio", "anio_fin", "es_atipico_tukey"):
        original = datos[columna]
        convertido = pd.to_numeric(original, errors="coerce")
        nulos_origen += int((convertido.isna() & original.notna()).sum())
        datos[columna] = convertido
    nulos_origen += int(
        (
            datos["es_atipico_tukey"].notna()
            & ~datos["es_atipico_tukey"].isin((0, 1))
        ).sum()
    )
    for columna in ("anio_inicio", "anio_fin"):
        nulos_origen += int(
            (
                datos[columna].notna()
                & (datos[columna] % 1 != 0)
            ).sum()
        )
    datos["quinquenio"] = datos["anio_fin"].map(etiqueta_quinquenio)
    datos["decada"] = datos["anio_fin"].map(etiqueta_decada)
    datos = datos.rename(
        columns={
            "class_from": "codigo_origen",
            "class_to": "codigo_destino",
            "class_level_2_from": "nivel2_origen",
            "class_level_1_from": "nivel1_origen",
            "class_level_0_from": "nivel0_origen",
            "class_level_2_to": "nivel2_destino",
            "class_level_1_to": "nivel1_destino",
            "class_level_0_to": "nivel0_destino",
        }
    )
    datos.attrs["nulos_origen"] = nulos_origen
    return datos


def abrir_base_solo_lectura(ruta_base):
    """Abre la base en modo de solo lectura y valida que esté disponible."""
    if not os.path.isfile(ruta_base):
        raise FileNotFoundError(f"No existe la base SQLite: {ruta_base}")
    uri = f"{Path(ruta_base).resolve().as_uri()}?mode=ro"
    conexion = sqlite3.connect(uri, uri=True)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA query_only = ON")
    return conexion


def leer_modelo(conexion):
    """Obtiene los hechos con sus cuatro dimensiones para calcular controles."""
    consulta = """
        SELECT
            t.municipio,
            t.departamento,
            t.pais,
            ti.periodo,
            ti.anio_inicio,
            ti.anio_fin,
            ti.quinquenio,
            ti.decada,
            o.codigo AS codigo_origen,
            o.nivel2 AS nivel2_origen,
            o.nivel1 AS nivel1_origen,
            o.nivel0 AS nivel0_origen,
            d.codigo AS codigo_destino,
            d.nivel2 AS nivel2_destino,
            d.nivel1 AS nivel1_destino,
            d.nivel0 AS nivel0_destino,
            f.area_ha,
            f.es_cambio,
            f.es_atipico
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
    modelo = pd.read_sql_query(consulta, conexion)
    for columna in (
        "municipio",
        "departamento",
        "pais",
        "periodo",
        "codigo_origen",
        "nivel2_origen",
        "nivel1_origen",
        "nivel0_origen",
        "codigo_destino",
        "nivel2_destino",
        "nivel1_destino",
        "nivel0_destino",
    ):
        modelo[columna] = modelo[columna].map(texto)
    return modelo


def contar(conexion, consulta, parametros=()):
    """Ejecuta una consulta escalar y devuelve un entero."""
    return int(conexion.execute(consulta, parametros).fetchone()[0])


def conteos_tablas(conexion):
    """Devuelve los conteos de filas de las cinco tablas del modelo."""
    tablas = (
        "Fact_Transicion_Cobertura",
        "Dim_Territorio",
        "Dim_Tiempo",
        "Dim_CoberturaOrigen",
        "Dim_CoberturaDestino",
    )
    return {
        tabla: contar(conexion, f"SELECT COUNT(*) FROM {tabla}")
        for tabla in tablas
    }


def nulos_modelo(conexion):
    """Cuenta nulos y hechos que no tienen correspondencia en sus dimensiones."""
    consultas = (
        """
        SELECT COUNT(*) FROM Fact_Transicion_Cobertura
        WHERE territorio_key IS NULL OR tiempo_key IS NULL
           OR origen_key IS NULL OR destino_key IS NULL
           OR area_ha IS NULL OR es_cambio IS NULL OR es_atipico IS NULL
        """,
        """
        SELECT COUNT(*) FROM Fact_Transicion_Cobertura AS f
        LEFT JOIN Dim_Territorio AS t ON t.territorio_key = f.territorio_key
        LEFT JOIN Dim_Tiempo AS ti ON ti.tiempo_key = f.tiempo_key
        LEFT JOIN Dim_CoberturaOrigen AS o ON o.origen_key = f.origen_key
        LEFT JOIN Dim_CoberturaDestino AS d ON d.destino_key = f.destino_key
        WHERE t.territorio_key IS NULL OR ti.tiempo_key IS NULL
           OR o.origen_key IS NULL OR d.destino_key IS NULL
        """,
        """
        SELECT COUNT(*) FROM Dim_Territorio
        WHERE municipio IS NULL OR departamento IS NULL OR pais IS NULL
        """,
        """
        SELECT COUNT(*) FROM Dim_Tiempo
        WHERE periodo IS NULL OR anio_inicio IS NULL OR anio_fin IS NULL
           OR quinquenio IS NULL OR decada IS NULL
        """,
        """
        SELECT COUNT(*) FROM Dim_CoberturaOrigen
        WHERE codigo IS NULL OR nivel2 IS NULL OR nivel1 IS NULL OR nivel0 IS NULL
        """,
        """
        SELECT COUNT(*) FROM Dim_CoberturaDestino
        WHERE codigo IS NULL OR nivel2 IS NULL OR nivel1 IS NULL OR nivel0 IS NULL
        """,
    )
    return sum(contar(conexion, consulta) for consulta in consultas)


def valores_faltantes_excel(datos):
    """Cuenta celdas vacías y códigos cuya leyenda no es unívoca."""
    faltantes = int(datos.attrs.get("nulos_origen", 0))
    inconsistencias = 0
    for codigo, nivel2, nivel1, nivel0 in (
        ("codigo_origen", "nivel2_origen", "nivel1_origen", "nivel0_origen"),
        ("codigo_destino", "nivel2_destino", "nivel1_destino", "nivel0_destino"),
    ):
        leyendas = datos[[codigo, nivel2, nivel1, nivel0]].drop_duplicates()
        inconsistencias += int(
            leyendas.groupby(codigo, dropna=False).size().gt(1).sum()
        )
    return faltantes + inconsistencias


def suma(datos, condicion=None):
    """Suma area_ha sobre todos los registros o una selección dada."""
    seleccion = datos if condicion is None else datos.loc[condicion]
    return float(seleccion["area_ha"].sum())


def agrupacion(datos, columna, condicion):
    """Calcula área agrupada después de aplicar una condición de transición."""
    seleccion = datos.loc[condicion]
    resultado = seleccion.groupby(columna, sort=True)["area_ha"].sum()
    return {str(clave): float(valor) for clave, valor in resultado.items()}


def comparar(esperado, obtenido, tolerancia=TOLERANCIA_HA):
    """Compara valores escalares o mapas y devuelve diferencia y resultado."""
    if isinstance(esperado, dict) and isinstance(obtenido, dict):
        claves = sorted(set(esperado) | set(obtenido))
        diferencias = {}
        coincide = set(esperado) == set(obtenido)
        for clave in claves:
            if clave not in esperado or clave not in obtenido:
                diferencias[clave] = None
                coincide = False
                continue
            diferencias[clave], valores_coinciden = comparar(
                esperado[clave],
                obtenido[clave],
                tolerancia,
            )
            coincide = coincide and valores_coinciden
        return diferencias, coincide
    diferencia = numero(float(obtenido) - float(esperado))
    return diferencia, abs(diferencia) <= tolerancia


def registrar(
    verificaciones,
    identificador,
    nombre,
    categoria,
    esperado,
    obtenido,
    explicacion,
    control=None,
):
    """Añade un resultado, sin ocultar diferencias respecto del Excel o control."""
    diferencia, coincide = comparar(esperado, obtenido)
    control_correcto = True
    nota_control = ""
    if control is not None:
        _, control_correcto = comparar(control, esperado)
        if not control_correcto:
            nota_control = (
                f" El valor del Excel también difiere del control documentado "
                f"({json_nativo(control)})."
            )

    aprobado = coincide and control_correcto
    detalle = explicacion
    if not aprobado:
        detalle += (
            " Posible causa: otro archivo de origen, una carga desactualizada "
            "o una diferencia en la transformación/agrupación; revisar los "
            "valores y el grano antes de aceptar el resultado."
        )
    detalle += nota_control
    verificaciones.append(
        {
            "id": identificador,
            "nombre": nombre,
            "categoria": categoria,
            "esperado": json_nativo(esperado),
            "obtenido": json_nativo(obtenido),
            "diferencia": json_nativo(diferencia),
            "resultado": "OK" if aprobado else "FALLO",
            "explicacion": detalle,
        }
    )


def duplicados_dimensiones(conexion):
    """Cuenta claves de dimensión duplicadas en las cuatro dimensiones."""
    consultas = (
        ("Dim_Territorio", "territorio_key"),
        ("Dim_Tiempo", "tiempo_key"),
        ("Dim_CoberturaOrigen", "origen_key"),
        ("Dim_CoberturaDestino", "destino_key"),
    )
    duplicados = {}
    for tabla, clave in consultas:
        cantidad = contar(
            conexion,
            f"SELECT COUNT(*) - COUNT(DISTINCT {clave}) FROM {tabla}",
        )
        duplicados[tabla] = cantidad
    return duplicados


def huerfanos_dimensiones(conexion):
    """Cuenta relaciones sin correspondencia para cada clave foránea."""
    consultas = {
        "Dim_Territorio": """
            SELECT COUNT(*) FROM Fact_Transicion_Cobertura AS f
            LEFT JOIN Dim_Territorio AS d ON d.territorio_key = f.territorio_key
            WHERE d.territorio_key IS NULL
        """,
        "Dim_Tiempo": """
            SELECT COUNT(*) FROM Fact_Transicion_Cobertura AS f
            LEFT JOIN Dim_Tiempo AS d ON d.tiempo_key = f.tiempo_key
            WHERE d.tiempo_key IS NULL
        """,
        "Dim_CoberturaOrigen": """
            SELECT COUNT(*) FROM Fact_Transicion_Cobertura AS f
            LEFT JOIN Dim_CoberturaOrigen AS d ON d.origen_key = f.origen_key
            WHERE d.origen_key IS NULL
        """,
        "Dim_CoberturaDestino": """
            SELECT COUNT(*) FROM Fact_Transicion_Cobertura AS f
            LEFT JOIN Dim_CoberturaDestino AS d ON d.destino_key = f.destino_key
            WHERE d.destino_key IS NULL
        """,
    }
    return {tabla: contar(conexion, consulta) for tabla, consulta in consultas.items()}


def duplicados_grano(conexion):
    """Cuenta filas repetidas en la clave compuesta de la tabla de hechos."""
    return contar(
        conexion,
        """
        SELECT COALESCE(SUM(repeticiones - 1), 0)
        FROM (
            SELECT COUNT(*) AS repeticiones
            FROM Fact_Transicion_Cobertura
            GROUP BY territorio_key, tiempo_key, origen_key, destino_key
            HAVING COUNT(*) > 1
        )
        """,
    )


def verificar(datos, conexion, modelo):
    """Ejecuta las verificaciones estructurales y de resultados analíticos."""
    verificaciones = []
    duplicados = duplicados_dimensiones(conexion)
    total_duplicados = sum(duplicados.values())
    registrar(
        verificaciones,
        "claves_dimensiones",
        "Unicidad de claves en las cuatro dimensiones",
        "estructura",
        0,
        total_duplicados,
        f"Duplicados por dimensión: {duplicados}.",
    )

    huerfanos = huerfanos_dimensiones(conexion)
    registrar(
        verificaciones,
        "claves_foraneas",
        "Claves foráneas sin huérfanos",
        "estructura",
        0,
        sum(huerfanos.values()),
        f"Huérfanos por dimensión: {huerfanos}.",
    )

    duplicados_excel = int(
        datos.duplicated(
            subset=["municipio", "periodo", "codigo_origen", "codigo_destino"],
            keep=False,
        ).sum()
    )
    duplicados_sqlite = duplicados_grano(conexion)
    registrar(
        verificaciones,
        "grano_sin_duplicados",
        "Ausencia de duplicados en el grano",
        "estructura",
        duplicados_excel,
        duplicados_sqlite,
        "Se contrastan municipio, periodo, cobertura de origen y cobertura de destino.",
    )
    if duplicados_excel or duplicados_sqlite:
        verificaciones[-1]["resultado"] = "FALLO"

    faltantes_excel = valores_faltantes_excel(datos)
    faltantes_sqlite = nulos_modelo(conexion)
    registrar(
        verificaciones,
        "faltantes_y_categorias",
        "Valores faltantes y categorías sin correspondencia",
        "calidad",
        faltantes_excel,
        faltantes_sqlite,
        "Incluye celdas vacías y códigos de clase con leyendas inconsistentes "
        "en el Excel, y nulos o hechos sin dimensión en SQLite.",
    )
    if faltantes_excel or faltantes_sqlite:
        verificaciones[-1]["resultado"] = "FALLO"

    conteos_excel = {
        "Fact_Transicion_Cobertura": len(datos),
        "hechos_area_mayor_0": int((datos["area_ha"] > 0).sum()),
        "hechos_area_igual_0": int((datos["area_ha"] == 0).sum()),
        "Dim_Territorio": len(datos[["municipio", "departamento", "pais"]].drop_duplicates()),
        "Dim_Tiempo": len(datos[["periodo", "anio_inicio", "anio_fin"]].drop_duplicates()),
        "Dim_CoberturaOrigen": len(
            datos[["codigo_origen", "nivel2_origen", "nivel1_origen", "nivel0_origen"]]
            .drop_duplicates()
        ),
        "Dim_CoberturaDestino": len(
            datos[
                [
                    "codigo_destino",
                    "nivel2_destino",
                    "nivel1_destino",
                    "nivel0_destino",
                ]
            ].drop_duplicates()
        ),
    }
    conteos_sqlite = conteos_tablas(conexion)
    conteos_sqlite.update(
        {
            "hechos_area_mayor_0": contar(
                conexion,
                "SELECT COUNT(*) FROM Fact_Transicion_Cobertura WHERE area_ha > 0",
            ),
            "hechos_area_igual_0": contar(
                conexion,
                "SELECT COUNT(*) FROM Fact_Transicion_Cobertura WHERE area_ha = 0",
            ),
        }
    )
    control_conteos = {
        "Fact_Transicion_Cobertura": 27144,
        "hechos_area_mayor_0": 18623,
        "hechos_area_igual_0": 8521,
        "Dim_Territorio": 11,
        "Dim_Tiempo": 39,
        "Dim_CoberturaOrigen": 10,
        "Dim_CoberturaDestino": 10,
    }
    registrar(
        verificaciones,
        "conteos",
        "Conteos del hecho y las dimensiones",
        "estructura",
        conteos_excel,
        conteos_sqlite,
        "Se conservan también las 8.521 transiciones cuyo area_ha es cero.",
        control=control_conteos,
    )

    total_excel = suma(datos)
    total_modelo = suma(modelo)
    registrar(
        verificaciones,
        "area_total",
        "Suma total de area_ha",
        "comparacion",
        total_excel,
        total_modelo,
        f"Tolerancia de comparación: {TOLERANCIA_HA} ha.",
    )

    area_municipio_excel = agrupacion(datos, "municipio", pd.Series(True, index=datos.index))
    area_municipio_modelo = agrupacion(
        modelo,
        "municipio",
        pd.Series(True, index=modelo.index),
    )
    diferencia_municipios, coincide_municipios = comparar(
        area_municipio_excel,
        area_municipio_modelo,
    )
    mayor_diferencia = max(
        (abs(valor) for valor in diferencia_municipios.values() if valor is not None),
        default=0.0,
    )
    registrar(
        verificaciones,
        "area_por_municipio",
        "Área total por municipio",
        "comparacion",
        area_municipio_excel,
        area_municipio_modelo,
        f"Se reportan los 11 municipios; la mayor diferencia absoluta es "
        f"{mayor_diferencia:.6f} ha (tolerancia {TOLERANCIA_HA} ha).",
    )
    if not coincide_municipios:
        verificaciones[-1]["resultado"] = "FALLO"

    periodos_excel = datos.groupby("periodo")["area_ha"].sum().to_dict()
    periodos_modelo = modelo.groupby("periodo")["area_ha"].sum().to_dict()
    areas_inicio_fin_excel = {
        "p1985_1986": float(periodos_excel.get("p1985_1986", 0.0)),
        "p2023_2024": float(periodos_excel.get("p2023_2024", 0.0)),
    }
    areas_inicio_fin_modelo = {
        "p1985_1986": float(periodos_modelo.get("p1985_1986", 0.0)),
        "p2023_2024": float(periodos_modelo.get("p2023_2024", 0.0)),
    }
    registrar(
        verificaciones,
        "area_base_y_cierre",
        "Área base y área de cierre",
        "comparacion",
        areas_inicio_fin_excel,
        areas_inicio_fin_modelo,
        "Control: 102.755,1 ha en p1985_1986 y p2023_2024.",
        control={"p1985_1986": 102755.1, "p2023_2024": 102755.1},
    )

    cambio_excel = datos["codigo_origen"] != datos["codigo_destino"]
    cambio_modelo = modelo["codigo_origen"] != modelo["codigo_destino"]
    ganancia_excel = cambio_excel & datos["nivel2_destino"].eq(AREA_URBANA)
    perdida_excel = cambio_excel & datos["nivel2_origen"].eq(AREA_URBANA)
    ganancia_modelo = cambio_modelo & modelo["nivel2_destino"].eq(AREA_URBANA)
    perdida_modelo = cambio_modelo & modelo["nivel2_origen"].eq(AREA_URBANA)
    valores_urbanos_excel = {
        "ganancia_ha": suma(datos, ganancia_excel),
        "perdida_ha": suma(datos, perdida_excel),
        "ritmo_ha_anio": suma(datos, ganancia_excel)
        / max(int(datos["anio_fin"].nunique()), 1),
    }
    valores_urbanos_modelo = {
        "ganancia_ha": suma(modelo, ganancia_modelo),
        "perdida_ha": suma(modelo, perdida_modelo),
        "ritmo_ha_anio": suma(modelo, ganancia_modelo)
        / max(int(modelo["anio_fin"].nunique()), 1),
    }
    registrar(
        verificaciones,
        "ganancia_perdida_ritmo_urbano",
        "Ganancia, pérdida y ritmo anual urbano",
        "comparacion",
        valores_urbanos_excel,
        valores_urbanos_modelo,
        "Ganancia y pérdida excluyen permanencias; el ritmo divide la ganancia "
        "entre los años finales distintos.",
        control={
            "ganancia_ha": 6080.2,
            "perdida_ha": 40.0,
            "ritmo_ha_anio": 155.9,
        },
    )

    urbana_inicio_excel = suma(
        datos,
        datos["periodo"].eq("p1985_1986")
        & datos["nivel2_origen"].eq(AREA_URBANA),
    )
    urbana_cierre_excel = suma(
        datos,
        datos["periodo"].eq("p2023_2024")
        & datos["nivel2_destino"].eq(AREA_URBANA),
    )
    urbana_inicio_modelo = suma(
        modelo,
        modelo["periodo"].eq("p1985_1986")
        & modelo["nivel2_origen"].eq(AREA_URBANA),
    )
    urbana_cierre_modelo = suma(
        modelo,
        modelo["periodo"].eq("p2023_2024")
        & modelo["nivel2_destino"].eq(AREA_URBANA),
    )
    registrar(
        verificaciones,
        "cobertura_urbana_inicio_fin",
        "Cobertura urbana inicial y final",
        "comparacion",
        {
            "inicial_ha": urbana_inicio_excel,
            "final_ha": urbana_cierre_excel,
        },
        {
            "inicial_ha": urbana_inicio_modelo,
            "final_ha": urbana_cierre_modelo,
        },
        "La cobertura inicial se mide desde origen y la de cierre desde destino.",
        control={"inicial_ha": 549.9, "final_ha": 6590.0},
    )

    atipicas_excel = (
        (datos["es_atipico_tukey"] == 1)
        & datos["nivel2_destino"].eq(AREA_URBANA)
        & datos["codigo_origen"].ne(datos["codigo_destino"])
    )
    atipicas_modelo = (
        (modelo["es_atipico"] == 1)
        & modelo["nivel2_destino"].eq(AREA_URBANA)
        & modelo["es_cambio"].eq(1)
    )
    valores_atipicos_excel = {
        "transiciones": int(atipicas_excel.sum()),
        "area_ha": suma(datos, atipicas_excel),
    }
    valores_atipicos_modelo = {
        "transiciones": int(atipicas_modelo.sum()),
        "area_ha": suma(modelo, atipicas_modelo),
    }
    registrar(
        verificaciones,
        "atipicas_hacia_urbano",
        "Transiciones atípicas con destino urbano",
        "comparacion",
        valores_atipicos_excel,
        valores_atipicos_modelo,
        "Una transición atípica es una alerta de magnitud, no un error confirmado.",
        control={"transiciones": 36, "area_ha": 1625.1},
    )

    ganancia_por_decada_excel = agrupacion(datos, "decada", ganancia_excel)
    ganancia_por_decada_modelo = agrupacion(modelo, "decada", ganancia_modelo)
    ganancia_por_municipio_excel = agrupacion(datos, "municipio", ganancia_excel)
    ganancia_por_municipio_modelo = agrupacion(modelo, "municipio", ganancia_modelo)
    ganancia_por_quinquenio_excel = agrupacion(datos, "quinquenio", ganancia_excel)
    ganancia_por_quinquenio_modelo = agrupacion(modelo, "quinquenio", ganancia_modelo)
    aditividad_excel = {
        "decada": ganancia_por_decada_excel,
        "municipio": ganancia_por_municipio_excel,
        "quinquenio": ganancia_por_quinquenio_excel,
    }
    aditividad_modelo = {
        "decada": ganancia_por_decada_modelo,
        "municipio": ganancia_por_municipio_modelo,
        "quinquenio": ganancia_por_quinquenio_modelo,
    }
    diferencia_aditividad, coincide_aditividad = comparar(
        aditividad_excel,
        aditividad_modelo,
    )
    controles_decada, coincide_control_decada = comparar(
        CONTROL_DECADAS,
        ganancia_por_decada_excel,
    )
    sumas_excel = {
        dimension: sum(valores.values())
        for dimension, valores in aditividad_excel.items()
    }
    sumas_modelo = {
        dimension: sum(valores.values())
        for dimension, valores in aditividad_modelo.items()
    }
    sumas_aditivas, coincide_sumas = comparar(sumas_excel, sumas_modelo)
    registrar(
        verificaciones,
        "aditividad",
        "Aditividad por década, municipio y quinquenio",
        "comparacion",
        aditividad_excel,
        aditividad_modelo,
        "Se comparan las agrupaciones completas y sus sumas; las cinco cifras "
        f"de década deben coincidir con los controles documentados. Diferencias "
        f"en sumas: {json_nativo(sumas_aditivas)}; diferencia respecto de los "
        f"controles de década: {json_nativo(controles_decada)}.",
    )
    if not coincide_aditividad or not coincide_sumas or not coincide_control_decada:
        verificaciones[-1]["resultado"] = "FALLO"
    return verificaciones


def ejecutar(ruta_origen):
    """Genera verificaciones.json y devuelve cuántas verificaciones fallaron."""
    datos = leer_excel(ruta_origen)
    with abrir_base_solo_lectura(RUTA_BASE) as conexion:
        modelo = leer_modelo(conexion)
        verificaciones = verificar(datos, conexion, modelo)

    with open(RUTA_RESULTADOS, "w", encoding="utf-8") as archivo:
        json.dump(verificaciones, archivo, ensure_ascii=False, indent=2)
        archivo.write("\n")

    fallidas = [fila for fila in verificaciones if fila["resultado"] != "OK"]
    print(
        f"Verificaciones: {len(verificaciones) - len(fallidas)} OK; "
        f"{len(fallidas)} FALLO."
    )
    print(f"Resultados: {RUTA_RESULTADOS}")
    for fila in verificaciones:
        print(f"{fila['resultado']}: {fila['nombre']}")
    return 1 if fallidas else 0


def main():
    """Procesa los argumentos y comunica fallos de lectura o comparación."""
    analizador = argparse.ArgumentParser(
        description="Compara los datos tratados con el modelo SQLite."
    )
    analizador.add_argument(
        "--origen",
        required=True,
        help="Ruta local al archivo DatosTratados1.xlsx.",
    )
    argumentos = analizador.parse_args()
    try:
        return ejecutar(os.path.abspath(argumentos.origen))
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        sqlite3.Error,
        pd.errors.EmptyDataError,
    ) as error:
        print(f"Error al verificar el modelo: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
