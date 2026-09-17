"""Dashboard Dash para explorar las tasas de interés activas de 2025.

El Parquet se consulta con DuckDB: los callbacks agregan en el motor y solo
envían al navegador tablas pequeñas (nunca las decenas de millones de filas).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
import plotly.express as px
from dash import Dash, Input, Output, dcc, html


DATA_PATH = Path(os.getenv("DASH_DATA_PATH", "tasas_2025.parquet"))
if not DATA_PATH.exists() and Path("tasas_2025.parquet").exists():
    DATA_PATH = Path("tasas_2025.parquet")

COL_DATE = "fecha_corte"
COL_RATE = "tasa_efectiva_promedio"
COL_MARGIN = "margen_adicional_a_la"
COL_TYPE = "tipo_de_cr_dito"
COL_PRODUCT = "producto_de_cr_dito"
COL_TERM = "plazo_de_cr_dito"
COL_GUARANTEE = "tipo_de_garant_a"
COL_ENTITY = "nombre_entidad"
COL_ENTITY_TYPE = "nombre_tipo_entidad"
COL_PERSON = "tipo_de_persona"
COL_SEX = "sexo"
COL_COMPANY = "tama_o_de_empresa"
COL_AGE = "antiguedad_de_la_empresa"
COL_ETHNICITY = "grupo_etnico"
COL_RATE_TYPE = "tipo_de_tasa"
COL_AMOUNT_RANGE = "rango_monto_desembolsado"
COL_DEBTOR = "clase_deudor"
COL_AMOUNT = "montos_desembolsados"
COL_CREDITS = "numero_de_creditos"
COL_MUNICIPALITY = "codigo_municipio"
DEPARTMENT_EXPR = f"left(cast(\"{COL_MUNICIPALITY}\" AS VARCHAR), 2)"

# Centroides departamentales para ubicar aproximadamente los códigos DANE.
# El dataset no incluye latitud/longitud municipal.
DEPARTMENT_CENTERS = {
    "05": (6.25, -75.56), "08": (10.99, -74.79), "11": (4.71, -74.07),
    "13": (10.40, -75.50), "15": (5.53, -73.36), "17": (5.07, -75.52),
    "18": (1.61, -75.61), "19": (2.45, -76.61), "20": (10.46, -73.25),
    "23": (8.75, -75.88), "25": (4.60, -74.08), "27": (5.69, -76.66),
    "41": (2.93, -75.28), "44": (11.54, -72.91), "47": (11.24, -74.20),
    "50": (4.15, -73.64), "52": (1.21, -77.28), "54": (7.89, -72.50),
    "63": (4.53, -75.68), "66": (4.81, -75.69), "68": (7.12, -73.12),
    "70": (9.30, -75.40), "73": (4.44, -75.24), "76": (3.45, -76.53),
    "81": (7.09, -70.76), "85": (5.34, -72.39), "86": (1.15, -76.65),
    "88": (12.58, -81.70), "91": (-1.44, -71.94), "94": (3.87, -67.92),
    "95": (2.57, -72.64), "97": (1.25, -70.23), "99": (4.08, -69.52),
}

# Socrata puede exportar estas columnas como texto. Estas conversiones hacen
# que los callbacks funcionen tanto con Parquet tipado como sin tipar.
DATE_EXPR = f'try_cast("{COL_DATE}" AS DATE)'
RATE_EXPR = f'''try_cast(replace("{COL_RATE}", ',', '.') AS DOUBLE)'''
AMOUNT_EXPR = f'''try_cast(replace("{COL_AMOUNT}", ',', '.') AS DOUBLE)'''
CREDITS_EXPR = f'''try_cast(replace("{COL_CREDITS}", ',', '.') AS DOUBLE)'''

FILTERS = {
    "f-tipo": COL_TYPE,
    "f-producto": COL_PRODUCT,
    "f-entidad": COL_ENTITY,
    "f-sexo": COL_SEX,
    "f-empresa": COL_COMPANY,
    "f-persona": COL_PERSON,
    "f-tasa": COL_RATE_TYPE,
}

app = Dash(__name__, title="Dash — Tasas de interés 2025")
server = app.server


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parquet_expr() -> str:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de datos: {DATA_PATH}. "
            "Descarga el Parquet indicado en README.md."
        )
    return f"read_parquet({sql_quote(str(DATA_PATH))}, hive_partitioning=false)"


def query(sql: str, params: list[Any] | None = None):
    """Abre una conexión corta; DuckDB libera recursos al terminar el callback."""
    with duckdb.connect(database=":memory:", read_only=False) as con:
        return con.execute(sql, params or []).fetchdf()


def filter_sql(values: dict[str, Any], date_range: list[str] | None) -> tuple[str, list[Any]]:
    clauses = [f"{RATE_EXPR} IS NOT NULL"]
    params: list[Any] = []
    if date_range and len(date_range) == 2:
        clauses += [f"{DATE_EXPR} >= CAST(? AS DATE)", f"{DATE_EXPR} <= CAST(? AS DATE)"]
        params.extend(date_range)
    for component_id, column in FILTERS.items():
        selected = values.get(component_id)
        if selected:
            placeholders = ", ".join("?" for _ in selected)
            clauses.append(f'"{column}" IN ({placeholders})')
            params.extend(selected)
    return " AND ".join(clauses), params


def options(column: str) -> list[dict[str, str]]:
    try:
        frame = query(
            f'''SELECT DISTINCT "{column}" AS value
                FROM {parquet_expr()}
                WHERE "{column}" IS NOT NULL
                ORDER BY 1 LIMIT 500'''
        )
    except FileNotFoundError:
        return []
    return [{"label": str(v), "value": str(v)} for v in frame["value"].tolist()]


def selector(component_id: str, label: str) -> html.Div:
    return html.Div(
        [html.Label(label, className="filter-label"), dcc.Dropdown(id=component_id, multi=True, placeholder="Todos")],
        className="filter",
    )


app.layout = html.Div(
    [
        html.Div(
            [
                html.H1("Tasas de interés activas", className="title"),
                html.P("Colombia · 2025 · agregación interactiva sobre Parquet", className="subtitle"),
            ],
            className="hero",
        ),
        html.Div(
            [
                html.Div([html.Label("Periodo", className="filter-label"), dcc.DatePickerRange(id="f-fecha", min_date_allowed="2025-01-01", max_date_allowed="2025-12-31", start_date="2025-01-01", end_date="2025-12-31", display_format="YYYY-MM-DD")], className="filter"),
                selector("f-tipo", "Tipo de crédito"),
                selector("f-producto", "Producto"),
                selector("f-entidad", "Entidad"),
                selector("f-sexo", "Sexo"),
                selector("f-empresa", "Tamaño de empresa"),
                selector("f-persona", "Tipo de persona"),
                selector("f-tasa", "Tipo de tasa"),
                html.Button("Actualizar análisis", id="refresh", n_clicks=0, className="refresh-button"),
            ],
            className="filters",
        ),
        html.Div(id="status", className="status"),
        html.Div(id="cards", className="cards"),
        html.Div(
            [
                dcc.Graph(id="trend", config={"displayModeBar": False}),
                dcc.Graph(id="by-type", config={"displayModeBar": False}),
            ],
            className="grid-2",
        ),
        html.Div([dcc.Graph(id="by-entity", config={"displayModeBar": False})], className="panel"),
        html.Div(
            [
                dcc.Graph(id="by-territory", config={"displayModeBar": False}),
                dcc.Graph(id="territory-rate", config={"displayModeBar": False}),
            ],
            className="grid-2",
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Label("Variable de color del mapa", className="filter-label"),
                        dcc.Dropdown(
                            id="f-map-variable",
                            options=[
                                {"label": "Tasa efectiva promedio", "value": "rate"},
                                {"label": "Número de créditos", "value": "credits"},
                                {"label": "Sexo", "value": "sex"},
                            ],
                            value="rate",
                            clearable=False,
                        ),
                    ],
                    className="map-control",
                ),
                dcc.Graph(id="territory-map", config={"displayModeBar": False}),
                html.P(
                    "Ubicación aproximada por departamento a partir del código DANE; "
                    "el dataset no contiene coordenadas municipales.",
                    className="map-note",
                ),
            ],
            className="panel map-panel",
        ),
        html.Footer("Fuente: Superintendencia Financiera · datos.gov.co · Dataset w9zh-vetq", className="footer"),
    ],
    className="page",
)


@app.callback(
    [Output(component_id, "options") for component_id in FILTERS],
    [Input("f-fecha", "id")],
)
def load_options(_):
    return [options(column) for column in FILTERS.values()]


@app.callback(
    Output("cards", "children"), Output("trend", "figure"), Output("by-type", "figure"), Output("by-entity", "figure"), Output("by-territory", "figure"), Output("territory-rate", "figure"), Output("territory-map", "figure"), Output("status", "children"),
    Input("f-fecha", "start_date"), Input("f-fecha", "end_date"),
    Input("refresh", "n_clicks"),
    Input("f-map-variable", "value"),
    *[Input(component_id, "value") for component_id in FILTERS],
)
def update_dashboard(start_date, end_date, _refresh_clicks, map_variable, *filter_values):
    selected = dict(zip(FILTERS, filter_values))
    try:
        where, params = filter_sql(selected, [start_date, end_date])
        source = parquet_expr()
        metrics = query(
            f'''SELECT COUNT(*) AS rows, AVG({RATE_EXPR}) AS rate,
                       SUM(COALESCE({AMOUNT_EXPR}, 0)) AS amount,
                       SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits
                FROM {source} WHERE {where}''', params
        ).iloc[0]
        weekly = query(
            f'''SELECT {DATE_EXPR} AS date, AVG({RATE_EXPR}) AS rate,
                       SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits
                FROM {source} WHERE {where}
                GROUP BY 1 ORDER BY 1''', params
        )
        types = query(
            f'''SELECT COALESCE("{COL_TYPE}", 'Sin dato') AS type, AVG({RATE_EXPR}) AS rate,
                       SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits
                FROM {source} WHERE {where}
                GROUP BY 1 ORDER BY credits DESC LIMIT 25''', params
        )
        entities = query(
            f'''SELECT COALESCE("{COL_ENTITY}", 'Sin dato') AS entity,
                       SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits,
                       AVG({RATE_EXPR}) AS rate
                FROM {source} WHERE {where}
                GROUP BY 1 ORDER BY credits DESC LIMIT 20''', params
        )
        territories = query(
            f'''SELECT COALESCE("{COL_MUNICIPALITY}", 'Sin código') AS municipality,
                       SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits,
                       AVG({RATE_EXPR}) AS rate
                FROM {source} WHERE {where} AND "{COL_MUNICIPALITY}" IS NOT NULL
                GROUP BY 1 ORDER BY credits DESC LIMIT 25''', params
        )
        if map_variable == "sex":
            map_data = query(
                f'''SELECT COALESCE("{COL_MUNICIPALITY}", 'Sin código') AS municipality,
                           COALESCE("{COL_SEX}", 'Sin dato') AS sex,
                           AVG({RATE_EXPR}) AS rate,
                           SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits
                    FROM {source} WHERE {where} AND "{COL_MUNICIPALITY}" IS NOT NULL
                    GROUP BY 1, 2 ORDER BY credits DESC LIMIT 300''', params
            )
        else:
            map_data = query(
                f'''SELECT COALESCE("{COL_MUNICIPALITY}", 'Sin código') AS municipality,
                           AVG({RATE_EXPR}) AS rate,
                           SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits
                    FROM {source} WHERE {where} AND "{COL_MUNICIPALITY}" IS NOT NULL
                    GROUP BY 1 ORDER BY credits DESC LIMIT 300''', params
            )
        map_data["department"] = map_data["municipality"].astype(str).str[:2]
        map_data["lat"] = map_data["department"].map(lambda code: DEPARTMENT_CENTERS.get(code, (4.6, -74.1))[0])
        map_data["lon"] = map_data["department"].map(lambda code: DEPARTMENT_CENTERS.get(code, (4.6, -74.1))[1])
        cards = [
            html.Div([html.Span("Filas analizadas"), html.Strong(f"{int(metrics['rows']):,}")], className="card"),
            html.Div([html.Span("Tasa promedio"), html.Strong(f"{float(metrics['rate'] or 0):.2f}%")], className="card"),
            html.Div([html.Span("Número de créditos"), html.Strong(f"{float(metrics['credits'] or 0):,.0f}")], className="card"),
            html.Div([html.Span("Monto desembolsado"), html.Strong(f"${float(metrics['amount'] or 0):,.0f}")], className="card"),
        ]
        common = dict(template="plotly_white", margin=dict(l=40, r=20, t=55, b=40), font=dict(family="Inter, sans-serif"))
        trend = px.line(weekly, x="date", y="rate", markers=True, title="Tasa promedio semanal", labels={"date": "Fecha", "rate": "% efectiva"})
        by_type = px.bar(types.sort_values("rate"), x="rate", y="type", orientation="h", title="Tasa promedio por tipo de crédito", labels={"rate": "% efectiva", "type": "Tipo"})
        by_entity = px.bar(entities.sort_values("credits"), x="credits", y="entity", orientation="h", color="rate", title="Top 20 entidades por número de créditos", labels={"credits": "Créditos", "entity": "Entidad", "rate": "% efectiva"}, color_continuous_scale="Blues")
        by_territory = px.bar(territories.sort_values("credits"), x="credits", y="municipality", orientation="h", title="Top 25 municipios por número de créditos", labels={"credits": "Créditos", "municipality": "Código de municipio"}, color="credits", color_continuous_scale="Blues")
        territory_rate = px.bar(territories.sort_values("rate"), x="rate", y="municipality", orientation="h", title="Tasa promedio por municipio", labels={"rate": "% efectiva", "municipality": "Código de municipio"}, color="rate", color_continuous_scale="RdYlBu_r")
        if map_variable == "sex":
            territory_map = px.scatter_mapbox(map_data, lat="lat", lon="lon", color="sex", size="credits", hover_name="municipality", hover_data={"rate": ":.2f", "credits": ":,.0f", "lat": False, "lon": False}, zoom=4.2, center={"lat": 4.6, "lon": -74.1}, height=560, title="Distribución territorial por sexo")
        else:
            color_column = "rate" if map_variable == "rate" else "credits"
            map_title = "Tasa efectiva promedio por territorio" if map_variable == "rate" else "Número de créditos por territorio"
            color_label = "% efectiva" if map_variable == "rate" else "Créditos"
            territory_map = px.scatter_mapbox(map_data, lat="lat", lon="lon", color=color_column, size="credits", hover_name="municipality", hover_data={"rate": ":.2f", "credits": ":,.0f", "lat": False, "lon": False}, color_continuous_scale="RdYlBu_r" if map_variable == "rate" else "Blues", zoom=4.2, center={"lat": 4.6, "lon": -74.1}, height=560, title=map_title, labels={color_column: color_label})
        territory_map.update_layout(mapbox_style="open-street-map")
        for fig in (trend, by_type, by_entity, by_territory, territory_rate, territory_map):
            fig.update_layout(**common)
        return cards, trend, by_type, by_entity, by_territory, territory_rate, territory_map, f"Consulta optimizada · {int(metrics['rows']):,} filas agregadas en DuckDB"
    except FileNotFoundError as exc:
        empty = px.scatter(title="Carga el Parquet para iniciar el dashboard")
        return [html.Div(str(exc), className="error")], empty, empty, empty, empty, empty, empty, "Falta el archivo de datos"
    except Exception as exc:
        empty = px.scatter(title="No se pudo actualizar la consulta")
        return [html.Div(f"Error de consulta: {exc}", className="error")], empty, empty, empty, empty, empty, empty, "Error al consultar los datos"


if __name__ == "__main__":
    app.run(debug=os.getenv("DASH_DEBUG", "false").lower() == "true", host="0.0.0.0", port=int(os.getenv("PORT", "8050")))
