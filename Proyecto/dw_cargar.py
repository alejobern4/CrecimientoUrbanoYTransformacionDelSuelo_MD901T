"""Construye localmente el modelo estrella desde los datos tratados."""

import argparse
import math
import os
import re
import sqlite3
import sys

import pandas as pd


DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
RUTA_BASE = os.path.join(DIRECTORIO, "dw_cobertura.db")
HOJA_ORIGEN = "Regional_SabanaCentro_Anual"
FILAS_ESPERADAS = 27144

COLUMNAS_REQUERIDAS = (
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


class ErrorCarga(ValueError):
    """Error de validación que impide construir un modelo confiable."""


def clave_natural(valor):
    """Ordena valores de texto de forma estable y natural."""
    partes = re.split(r"(\d+)", str(valor).casefold())
    return tuple(
        (1, int(parte)) if parte.isdigit() else (0, parte)
        for parte in partes
    )


def texto(valor, columna):
    """Devuelve el contenido como texto sin convertir enteros en valores decimales."""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    resultado = str(valor).strip()
    if not resultado:
        raise ErrorCarga(f"La columna {columna} contiene una categoría vacía.")
    return resultado


def entero(valor, columna):
    """Valida un valor entero requerido por el modelo."""
    try:
        numero = float(valor)
    except (TypeError, ValueError) as error:
        raise ErrorCarga(f"Valor no entero en {columna}: {valor!r}.") from error
    if not math.isfinite(numero) or not numero.is_integer():
        raise ErrorCarga(f"Valor no entero en {columna}: {valor!r}.")
    return int(numero)


def indicador(valor, columna):
    """Valida un indicador binario y devuelve su representación entera."""
    resultado = entero(valor, columna)
    if resultado not in (0, 1):
        raise ErrorCarga(f"{columna} solo admite 0 o 1; se encontró {valor!r}.")
    return resultado


def leer_origen(ruta_origen):
    """Lee y valida la hoja regional tratada antes de cargarla."""
    if not os.path.isfile(ruta_origen):
        raise FileNotFoundError(f"No existe el archivo de origen: {ruta_origen}")

    datos = pd.read_excel(
        ruta_origen,
        sheet_name=HOJA_ORIGEN,
        engine="openpyxl",
    )
    faltantes = [columna for columna in COLUMNAS_REQUERIDAS if columna not in datos]
    if faltantes:
        raise ErrorCarga(
            "Faltan columnas requeridas en la hoja "
            f"{HOJA_ORIGEN}: {', '.join(faltantes)}."
        )

    nulos = datos.loc[:, COLUMNAS_REQUERIDAS].isna().sum()
    columnas_con_nulos = nulos[nulos > 0]
    if not columnas_con_nulos.empty:
        detalle = ", ".join(
            f"{columna}: {cantidad}"
            for columna, cantidad in columnas_con_nulos.items()
        )
        raise ErrorCarga(f"Se encontraron valores faltantes: {detalle}.")

    if len(datos) != FILAS_ESPERADAS:
        raise ErrorCarga(
            f"Se esperaban {FILAS_ESPERADAS:,} filas y se encontraron "
            f"{len(datos):,}."
        )

    columnas_grano = ["municipio", "periodo", "class_from", "class_to"]
    claves_grano = pd.DataFrame(
        {
            columna: datos[columna].map(lambda valor: texto(valor, columna))
            for columna in columnas_grano
        }
    )
    duplicados = claves_grano.duplicated(keep=False)
    if duplicados.any():
        raise ErrorCarga(
            "Hay "
            f"{int(duplicados.sum()):,} filas duplicadas en el grano "
            "(municipio, periodo, class_from, class_to)."
        )

    datos = datos.loc[:, COLUMNAS_REQUERIDAS].copy()
    datos["area_ha"] = pd.to_numeric(datos["area_ha"], errors="coerce")
    if datos["area_ha"].isna().any() or not datos["area_ha"].map(
        lambda valor: math.isfinite(float(valor))
    ).all():
        raise ErrorCarga("La columna area_ha contiene valores no numéricos o no finitos.")

    return datos


def crear_dimensiones(datos):
    """Construye las cuatro dimensiones y los mapas de sus claves sustitutas."""
    territorios = {
        (
            texto(fila.municipio, "municipio"),
            texto(fila.departamento, "departamento"),
            texto(fila.pais, "pais"),
        )
        for fila in datos.itertuples(index=False)
    }
    territorios = sorted(territorios, key=lambda fila: tuple(map(clave_natural, fila)))
    if len(territorios) != 11:
        raise ErrorCarga(f"Se esperaban 11 territorios; se encontraron {len(territorios)}.")
    mapa_territorio = {
        territorio: indice for indice, territorio in enumerate(territorios, start=1)
    }

    tiempos = {}
    for fila in datos.itertuples(index=False):
        periodo = texto(fila.periodo, "periodo")
        anio_inicio = entero(fila.anio_inicio, "anio_inicio")
        anio_fin = entero(fila.anio_fin, "anio_fin")
        registro = (periodo, anio_inicio, anio_fin)
        if periodo in tiempos and tiempos[periodo] != registro:
            raise ErrorCarga(f"El periodo {periodo!r} tiene años inconsistentes.")
        tiempos[periodo] = registro
    registros_tiempo = sorted(
        tiempos.values(),
        key=lambda fila: (fila[2], fila[0]),
    )
    if len(registros_tiempo) != 39:
        raise ErrorCarga(
            f"Se esperaban 39 periodos; se encontraron {len(registros_tiempo)}."
        )
    dimensiones_tiempo = []
    mapa_tiempo = {}
    for indice, (periodo, anio_inicio, anio_fin) in enumerate(
        registros_tiempo, start=1
    ):
        base_quinquenio = (anio_fin // 5) * 5
        base_decada = (anio_fin // 10) * 10
        quinquenio = f"{base_quinquenio}-{base_quinquenio + 4}"
        decada = f"{base_decada}-{base_decada + 9}"
        dimensiones_tiempo.append(
            (indice, periodo, anio_inicio, anio_fin, quinquenio, decada)
        )
        mapa_tiempo[periodo] = indice

    mapa_clase = {}
    dimensiones_origen = []
    dimensiones_destino = []
    for sufijo, nombre, salida in (
        ("from", "origen", dimensiones_origen),
        ("to", "destino", dimensiones_destino),
    ):
        codigos = {}
        for fila in datos.itertuples(index=False):
            codigo = texto(getattr(fila, f"class_{sufijo}"), f"class_{sufijo}")
            niveles = (
                texto(
                    getattr(fila, f"class_level_2_{sufijo}"),
                    f"class_level_2_{sufijo}",
                ),
                texto(
                    getattr(fila, f"class_level_1_{sufijo}"),
                    f"class_level_1_{sufijo}",
                ),
                texto(
                    getattr(fila, f"class_level_0_{sufijo}"),
                    f"class_level_0_{sufijo}",
                ),
            )
            if codigo in codigos and codigos[codigo] != niveles:
                raise ErrorCarga(
                    f"El código de {nombre} {codigo!r} no tiene una leyenda única."
                )
            codigos[codigo] = niveles

        niveles_por_codigo = sorted(
            codigos.items(),
            key=lambda elemento: clave_natural(elemento[0]),
        )
        if len(niveles_por_codigo) != 10:
            raise ErrorCarga(
                f"Se esperaban 10 códigos de {nombre}; "
                f"se encontraron {len(niveles_por_codigo)}."
            )
        if len({niveles[0] for _, niveles in niveles_por_codigo}) != 10:
            raise ErrorCarga(
                f"Los códigos de {nombre} no tienen relación 1:1 con nivel2."
            )

        mapa_clase[nombre] = {}
        for indice, (codigo, niveles) in enumerate(niveles_por_codigo, start=1):
            salida.append((indice, codigo, niveles[0], niveles[1], niveles[2]))
            mapa_clase[nombre][codigo] = indice

    return (
        territorios,
        dimensiones_tiempo,
        dimensiones_origen,
        dimensiones_destino,
        mapa_territorio,
        mapa_tiempo,
        mapa_clase,
    )


def crear_hechos(datos, mapa_territorio, mapa_tiempo, mapa_clase):
    """Construye el hecho con una fila por combinación del grano definido."""
    hechos = []
    for fila in datos.itertuples(index=False):
        municipio = texto(fila.municipio, "municipio")
        departamento = texto(fila.departamento, "departamento")
        pais = texto(fila.pais, "pais")
        territorio = (municipio, departamento, pais)
        periodo = texto(fila.periodo, "periodo")
        codigo_origen = texto(fila.class_from, "class_from")
        codigo_destino = texto(fila.class_to, "class_to")

        try:
            territorio_key = mapa_territorio[territorio]
            tiempo_key = mapa_tiempo[periodo]
            origen_key = mapa_clase["origen"][codigo_origen]
            destino_key = mapa_clase["destino"][codigo_destino]
        except KeyError as error:
            raise ErrorCarga(
                f"No se pudo asignar una clave de dimensión para la fila "
                f"{fila.Index if hasattr(fila, 'Index') else ''}: {error}."
            ) from error

        hechos.append(
            (
                territorio_key,
                tiempo_key,
                origen_key,
                destino_key,
                float(fila.area_ha),
                int(codigo_origen != codigo_destino),
                indicador(fila.es_atipico_tukey, "es_atipico_tukey"),
            )
        )
    return hechos


def cargar_sqlite(ruta_base, dimensiones, hechos):
    """Recrea en una transacción el esquema estrella y sus índices."""
    (
        territorios,
        tiempos,
        coberturas_origen,
        coberturas_destino,
    ) = dimensiones
    esquema = (
        """
        CREATE TABLE Dim_Territorio (
            territorio_key INTEGER PRIMARY KEY,
            municipio TEXT NOT NULL,
            departamento TEXT NOT NULL,
            pais TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE Dim_Tiempo (
            tiempo_key INTEGER PRIMARY KEY,
            periodo TEXT NOT NULL,
            anio_inicio INTEGER NOT NULL,
            anio_fin INTEGER NOT NULL,
            quinquenio TEXT NOT NULL,
            decada TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE Dim_CoberturaOrigen (
            origen_key INTEGER PRIMARY KEY,
            codigo TEXT NOT NULL,
            nivel2 TEXT NOT NULL,
            nivel1 TEXT NOT NULL,
            nivel0 TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE Dim_CoberturaDestino (
            destino_key INTEGER PRIMARY KEY,
            codigo TEXT NOT NULL,
            nivel2 TEXT NOT NULL,
            nivel1 TEXT NOT NULL,
            nivel0 TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE Fact_Transicion_Cobertura (
            territorio_key INTEGER NOT NULL
                REFERENCES Dim_Territorio (territorio_key),
            tiempo_key INTEGER NOT NULL
                REFERENCES Dim_Tiempo (tiempo_key),
            origen_key INTEGER NOT NULL
                REFERENCES Dim_CoberturaOrigen (origen_key),
            destino_key INTEGER NOT NULL
                REFERENCES Dim_CoberturaDestino (destino_key),
            area_ha REAL NOT NULL,
            es_cambio INTEGER NOT NULL,
            es_atipico INTEGER NOT NULL,
            PRIMARY KEY (territorio_key, tiempo_key, origen_key, destino_key)
        )
        """,
    )

    with sqlite3.connect(ruta_base) as conexion:
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute("DROP TABLE IF EXISTS Fact_Transicion_Cobertura")
        conexion.execute("DROP TABLE IF EXISTS Dim_CoberturaDestino")
        conexion.execute("DROP TABLE IF EXISTS Dim_CoberturaOrigen")
        conexion.execute("DROP TABLE IF EXISTS Dim_Tiempo")
        conexion.execute("DROP TABLE IF EXISTS Dim_Territorio")
        for sentencia in esquema:
            conexion.execute(sentencia)

        conexion.executemany(
            "INSERT INTO Dim_Territorio VALUES (?, ?, ?, ?)",
            [
                (indice, municipio, departamento, pais)
                for indice, (municipio, departamento, pais) in enumerate(
                    territorios, start=1
                )
            ],
        )
        conexion.executemany(
            "INSERT INTO Dim_Tiempo VALUES (?, ?, ?, ?, ?, ?)",
            tiempos,
        )
        conexion.executemany(
            "INSERT INTO Dim_CoberturaOrigen VALUES (?, ?, ?, ?, ?)",
            coberturas_origen,
        )
        conexion.executemany(
            "INSERT INTO Dim_CoberturaDestino VALUES (?, ?, ?, ?, ?)",
            coberturas_destino,
        )
        conexion.executemany(
            """
            INSERT INTO Fact_Transicion_Cobertura
                (territorio_key, tiempo_key, origen_key, destino_key,
                 area_ha, es_cambio, es_atipico)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            hechos,
        )
        conexion.execute(
            "CREATE INDEX idx_fact_territorio "
            "ON Fact_Transicion_Cobertura (territorio_key)"
        )
        conexion.execute(
            "CREATE INDEX idx_fact_tiempo "
            "ON Fact_Transicion_Cobertura (tiempo_key)"
        )
        conexion.execute(
            "CREATE INDEX idx_fact_origen "
            "ON Fact_Transicion_Cobertura (origen_key)"
        )
        conexion.execute(
            "CREATE INDEX idx_fact_destino "
            "ON Fact_Transicion_Cobertura (destino_key)"
        )


def cargar(ruta_origen):
    """Valida el Excel y genera Proyecto/dw_cobertura.db."""
    datos = leer_origen(ruta_origen)
    (
        territorios,
        tiempos,
        coberturas_origen,
        coberturas_destino,
        mapa_territorio,
        mapa_tiempo,
        mapa_clase,
    ) = crear_dimensiones(datos)
    hechos = crear_hechos(datos, mapa_territorio, mapa_tiempo, mapa_clase)
    cargar_sqlite(
        RUTA_BASE,
        (territorios, tiempos, coberturas_origen, coberturas_destino),
        hechos,
    )

    conteos = {
        "Fact_Transicion_Cobertura": len(hechos),
        "Dim_Territorio": len(territorios),
        "Dim_Tiempo": len(tiempos),
        "Dim_CoberturaOrigen": len(coberturas_origen),
        "Dim_CoberturaDestino": len(coberturas_destino),
    }
    for tabla, cantidad in conteos.items():
        print(f"{tabla}: {cantidad:,} filas")
    print(f"Base generada: {RUTA_BASE}")


def main():
    """Interpreta los argumentos de línea de comandos y ejecuta la carga."""
    analizador = argparse.ArgumentParser(
        description="Carga el modelo estrella desde DatosTratados1.xlsx."
    )
    analizador.add_argument(
        "--origen",
        required=True,
        help="Ruta local al archivo DatosTratados1.xlsx.",
    )
    argumentos = analizador.parse_args()

    try:
        cargar(os.path.abspath(argumentos.origen))
    except (ErrorCarga, FileNotFoundError, OSError, ValueError, sqlite3.Error) as error:
        print(f"Error al cargar el modelo: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
