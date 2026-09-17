"""Dashboard Dash para explorar las tasas de interés activas de 2025.

El Parquet se consulta con DuckDB: los callbacks agregan en el motor y solo
envían al navegador tablas pequeñas (nunca las decenas de millones de filas).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb
import plotly.express as px
from dash import Dash, Input, Output, dcc, html


DATA_PATH = Path(os.getenv("DASH_DATA_PATH", "tasas_2025.parquet"))
if not DATA_PATH.exists() and Path("tasas_2025.parquet").exists():
    DATA_PATH = Path("tasas_2025.parquet")
DIVIPOLA_PATH = Path(os.getenv("DIVIPOLA_PATH", "data/divipola_municipios.json"))

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
COL_CIIU = "codigo_ciiu"
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
ACTIVITY_EXPR = f'''CASE WHEN left(regexp_replace(CAST("{COL_CIIU}" AS VARCHAR), '[^0-9]', '', 'g'), 2) = '01' THEN 'Agricultura y ganadería' WHEN left(regexp_replace(CAST("{COL_CIIU}" AS VARCHAR), '[^0-9]', '', 'g'), 2) = '02' THEN 'Silvicultura' WHEN left(regexp_replace(CAST("{COL_CIIU}" AS VARCHAR), '[^0-9]', '', 'g'), 2) = '03' THEN 'Pesca' ELSE 'Otras actividades' END'''

FILTERS = {
    "f-tipo": COL_TYPE,
    "f-producto": COL_PRODUCT,
    "f-entidad": COL_ENTITY,
    "f-sexo": COL_SEX,
    "f-empresa": COL_COMPANY,
    "f-persona": COL_PERSON,
    "f-tasa": COL_RATE_TYPE,
    "f-departamento": "__departamento__",
    "f-municipio": COL_MUNICIPALITY,
    "f-actividad": "__actividad__",
}


def load_divipola() -> dict[str, dict[str, str]]:
    if not DIVIPOLA_PATH.exists():
        return {}
    payload = json.loads(DIVIPOLA_PATH.read_text(encoding="utf-8"))
    result = {}
    for item in payload.get("features", []):
        row = item.get("attributes", {})
        code = str(row.get("MPIO_CDPMP", "")).zfill(5)
        if code and code != "00000":
            result[code] = {
                "municipio": str(row.get("MPIO_CNMBRE", "")).strip().title(),
                "departamento": str(row.get("DPTO_CNMBRE", "")).strip().title(),
                "lat": item.get("centroid", {}).get("y"),
                "lon": item.get("centroid", {}).get("x"),
            }
    return result


DIVIPOLA = load_divipola()

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
            if column == "__departamento__":
                selected = [code for code, row in DIVIPOLA.items() if row["departamento"] in selected]
                column = COL_MUNICIPALITY
            elif column == "__actividad__":
                clauses.append(f"{ACTIVITY_EXPR} IN ({', '.join('?' for _ in selected)})")
                params.extend(selected)
                continue
            if not selected:
                clauses.append("1 = 0")
                continue
            placeholders = ", ".join("?" for _ in selected)
            clauses.append(f'"{column}" IN ({placeholders})')
            params.extend(selected)
    return " AND ".join(clauses), params


def options(column: str) -> list[dict[str, str]]:
    if column == "__actividad__":
        values = ["Agricultura y ganadería", "Silvicultura", "Pesca", "Otras actividades"]
        return [{"label": value, "value": value} for value in values]
    if column == "__departamento__":
        values = sorted({row["departamento"] for row in DIVIPOLA.values()})
        return [{"label": value, "value": value} for value in values]
    if column == COL_MUNICIPALITY and DIVIPOLA:
        return [
            {"label": f'{row["municipio"]} ({code})', "value": code}
            for code, row in sorted(DIVIPOLA.items(), key=lambda item: item[1]["municipio"])
        ]
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
        [
            html.Label(label, className="filter-label"),
            dcc.Dropdown(
                id=component_id,
                options=options(FILTERS[component_id]),
                multi=True,
                placeholder="Todos",
            ),
        ],
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
                selector("f-departamento", "Departamento"),
                selector("f-municipio", "Municipio"),
                selector("f-actividad", "Actividad económica (CIIU)"),
                html.Button("Actualizar análisis", id="refresh", n_clicks=0, className="refresh-button"),
            ],
            className="filters",
        ),
        html.Div(id="status", className="status"),
        html.Div(id="cards", className="cards"),
        html.Div(
            [
                html.Div([dcc.Graph(id="trend", config={"displayModeBar": False}), html.P("Eje X: fecha de corte semanal. Eje Y: tasa efectiva promedio. Muestra cómo cambia la tasa en el tiempo.", className="chart-help")], className="chart-card"),
                html.Div([dcc.Graph(id="by-type", config={"displayModeBar": False}), html.P("Eje X: tasa efectiva promedio. Eje Y: tipo de crédito. Permite comparar el costo promedio entre productos.", className="chart-help")], className="chart-card"),
            ],
            className="grid-2",
        ),
        html.Div([dcc.Graph(id="by-entity", config={"displayModeBar": False}), html.P("Eje X: número de créditos. Eje Y: entidad financiera. Presenta las 20 entidades con más créditos.", className="chart-help")], className="panel chart-card"),
        html.Div(
            [
                html.Div([dcc.Graph(id="by-territory", config={"displayModeBar": False}), html.P("Eje X: número de créditos. Eje Y: municipio. Identifica los municipios con mayor volumen de crédito.", className="chart-help")], className="chart-card"),
                html.Div([dcc.Graph(id="territory-rate", config={"displayModeBar": False}), html.P("Eje X: tasa efectiva promedio. Eje Y: municipio. Compara el costo del crédito por territorio.", className="chart-help")], className="chart-card"),
            ],
            className="grid-2",
        ),
        html.Div(id="sex-analysis", className="analysis-section"),
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
                                {"label": "Actividad económica (CIIU)", "value": "activity"},
                            ],
                            value="rate",
                            clearable=False,
                        ),
                    ],
                    className="map-control",
                ),
                dcc.Graph(id="territory-map", config={"displayModeBar": False, "scrollZoom": True}),
                html.P(
                    "Cada punto corresponde al centroide oficial del municipio DIVIPOLA. "
                    "Usa la rueda del mouse, doble clic o los botones +/- para acercar y alejar.",
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
        territories["municipality_code"] = territories["municipality"].astype(str).str.zfill(5)
        territories["municipality_name"] = territories["municipality_code"].map(
            lambda code: DIVIPOLA.get(code, {}).get("municipio", f"Código {code}")
        )
        if map_variable == "activity":
            map_data = query(
                f'''SELECT COALESCE("{COL_MUNICIPALITY}", 'Sin código') AS municipality,
                           {ACTIVITY_EXPR} AS activity,
                           AVG({RATE_EXPR}) AS rate,
                           SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits
                    FROM {source} WHERE {where} AND "{COL_MUNICIPALITY}" IS NOT NULL
                    GROUP BY 1, 2 ORDER BY credits DESC LIMIT 500''', params
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
        map_data["municipality_code"] = map_data["municipality"].astype(str).str.zfill(5)
        map_data["municipality_name"] = map_data["municipality_code"].map(
            lambda code: DIVIPOLA.get(code, {}).get("municipio", f"Código {code}")
        )
        map_data["department_name"] = map_data["municipality_code"].map(
            lambda code: DIVIPOLA.get(code, {}).get("departamento", "Sin departamento")
        )
        map_data["lat"] = map_data["municipality_code"].map(lambda code: DIVIPOLA.get(code, {}).get("lat"))
        map_data["lon"] = map_data["municipality_code"].map(lambda code: DIVIPOLA.get(code, {}).get("lon"))
        map_data["lat"] = map_data["lat"].fillna(map_data["department"].map(lambda code: DEPARTMENT_CENTERS.get(code, (4.6, -74.1))[0]))
        map_data["lon"] = map_data["lon"].fillna(map_data["department"].map(lambda code: DEPARTMENT_CENTERS.get(code, (4.6, -74.1))[1]))
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
        by_territory = px.bar(territories.sort_values("credits"), x="credits", y="municipality_name", orientation="h", title="Top 25 municipios por número de créditos", labels={"credits": "Créditos", "municipality_name": "Municipio"}, color="credits", color_continuous_scale="Blues")
        territory_rate = px.bar(territories.sort_values("rate"), x="rate", y="municipality_name", orientation="h", title="Tasa promedio por municipio", labels={"rate": "% efectiva", "municipality_name": "Municipio"}, color="rate", color_continuous_scale="RdYlBu_r")
        if map_variable == "activity":
            territory_map = px.scatter_mapbox(map_data, lat="lat", lon="lon", color="activity", size="credits", hover_name="municipality_name", hover_data={"department_name": True, "municipality_code": True, "rate": ":.2f", "credits": ":,.0f", "lat": False, "lon": False}, zoom=4.2, center={"lat": 4.6, "lon": -74.1}, height=560, title="Distribución territorial por actividad económica")
        else:
            color_column = "rate" if map_variable == "rate" else "credits"
            map_title = "Tasa efectiva promedio por territorio" if map_variable == "rate" else "Número de créditos por territorio"
            color_label = "% efectiva" if map_variable == "rate" else "Créditos"
            territory_map = px.scatter_mapbox(map_data, lat="lat", lon="lon", color=color_column, size="credits", hover_name="municipality_name", hover_data={"department_name": True, "municipality_code": True, "rate": ":.2f", "credits": ":,.0f", "lat": False, "lon": False}, color_continuous_scale="RdYlBu_r" if map_variable == "rate" else "Blues", zoom=4.2, center={"lat": 4.6, "lon": -74.1}, height=560, title=map_title, labels={color_column: color_label})
        territory_map.update_layout(
            mapbox_style="open-street-map",
            mapbox_bounds={"west": -80.5, "east": -66.5, "south": -4.5, "north": 13.8},
            uirevision="colombia",
        )
        for fig in (trend, by_type, by_entity, by_territory, territory_rate, territory_map):
            fig.update_layout(**common)
        return cards, trend, by_type, by_entity, by_territory, territory_rate, territory_map, f"Consulta optimizada · {int(metrics['rows']):,} filas agregadas en DuckDB"
    except FileNotFoundError as exc:
        empty = px.scatter(title="Carga el Parquet para iniciar el dashboard")
        return [html.Div(str(exc), className="error")], empty, empty, empty, empty, empty, empty, "Falta el archivo de datos"
    except Exception as exc:
        empty = px.scatter(title="No se pudo actualizar la consulta")
        return [html.Div(f"Error de consulta: {exc}", className="error")], empty, empty, empty, empty, empty, empty, "Error al consultar los datos"


def analysis_card(fig, explanation: str) -> html.Div:
    return html.Div([dcc.Graph(figure=fig, config={"displayModeBar": False}), html.P(explanation, className="chart-help")], className="chart-card")


@app.callback(
    Output("sex-analysis", "children"),
    Input("f-fecha", "start_date"), Input("f-fecha", "end_date"), Input("refresh", "n_clicks"),
    *[Input(component_id, "value") for component_id in FILTERS],
)
def update_sex_analysis(start_date, end_date, _refresh_clicks, *filter_values):
    selected = dict(zip(FILTERS, filter_values))
    try:
        where, params = filter_sql(selected, [start_date, end_date])
        source = parquet_expr()
        sex = f'COALESCE("{COL_SEX}", \'Sin dato\')'
        common = dict(template="plotly_white", margin=dict(l=45, r=20, t=55, b=42), font=dict(family="Inter, sans-serif"))

        access = query(f'''SELECT {sex} AS sex, SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits, SUM(COALESCE({AMOUNT_EXPR}, 0)) AS amount FROM {source} WHERE {where} GROUP BY 1 ORDER BY 1''', params)
        access_long = access.melt(id_vars="sex", value_vars=["credits", "amount"], var_name="metric", value_name="value")
        access_long["metric"] = access_long["metric"].map({"credits": "Número de créditos", "amount": "Monto desembolsado"})
        fig_access = px.bar(access_long, x="sex", y="value", color="metric", barmode="group", title="Acceso al crédito por sexo", labels={"sex": "Sexo", "value": "Valor", "metric": "Indicador"})
        fig_access.update_yaxes(tickformat=",.0f")

        timeline = query(f'''SELECT {DATE_EXPR} AS date, {sex} AS sex, SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY 1''', params)
        fig_timeline = px.line(timeline, x="date", y="credits", color="sex", markers=True, title="Evolución semanal del número de créditos por sexo", labels={"date": "Fecha de corte", "credits": "Número de créditos", "sex": "Sexo"})

        average = query(f'''SELECT {sex} AS sex, SUM(COALESCE({AMOUNT_EXPR}, 0)) / NULLIF(SUM(COALESCE({CREDITS_EXPR}, 0)), 0) AS average_amount FROM {source} WHERE {where} GROUP BY 1''', params)
        fig_average = px.bar(average, x="sex", y="average_amount", color="sex", title="Monto promedio del crédito por sexo", labels={"sex": "Sexo", "average_amount": "Monto promedio ($)"}, color_discrete_sequence=px.colors.qualitative.Set2)

        rates = query(f'''SELECT COALESCE("{COL_TYPE}", 'Sin dato') AS credit_type, {sex} AS sex, AVG({RATE_EXPR}) AS rate FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY rate''', params)
        fig_rates = px.bar(rates, x="rate", y="credit_type", color="sex", barmode="group", orientation="h", title="Tasas de interés por tipo de crédito y sexo", labels={"rate": "% efectiva promedio", "credit_type": "Tipo de crédito", "sex": "Sexo"})
        rate_timeline = query(f'''SELECT {DATE_EXPR} AS date, {sex} AS sex, AVG({RATE_EXPR}) AS rate FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY 1''', params)
        fig_rate_timeline = px.line(rate_timeline, x="date", y="rate", color="sex", markers=True, title="Evolución semanal de la tasa por sexo", labels={"date": "Fecha de corte", "rate": "% efectiva promedio", "sex": "Sexo"})

        by_type = query(f'''SELECT COALESCE("{COL_TYPE}", 'Sin dato') AS credit_type, {sex} AS sex, SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY credits DESC LIMIT 40''', params)
        fig_by_type = px.bar(by_type, x="credit_type", y="credits", color="sex", barmode="group", title="Número de créditos por tipo y sexo", labels={"credit_type": "Tipo de crédito", "credits": "Número de créditos", "sex": "Sexo"})

        guarantees = query(f'''SELECT COALESCE("{COL_GUARANTEE}", 'Sin dato') AS guarantee, {sex} AS sex, SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY credits DESC LIMIT 30''', params)
        fig_guarantees = px.bar(guarantees, x="guarantee", y="credits", color="sex", barmode="group", title="Garantías utilizadas por sexo", labels={"guarantee": "Tipo de garantía", "credits": "Número de créditos", "sex": "Sexo"})

        terms = query(f'''SELECT COALESCE("{COL_TERM}", 'Sin dato') AS term, {sex} AS sex, SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY credits DESC LIMIT 30''', params)
        fig_terms = px.bar(terms, x="term", y="credits", color="sex", barmode="group", title="Plazo del crédito por sexo", labels={"term": "Plazo", "credits": "Número de créditos", "sex": "Sexo"})

        activities = query(f'''SELECT CASE WHEN left(regexp_replace(CAST("codigo_ciiu" AS VARCHAR), '[^0-9]', '', 'g'), 2) = '01' THEN 'Agricultura y ganadería' WHEN left(regexp_replace(CAST("codigo_ciiu" AS VARCHAR), '[^0-9]', '', 'g'), 2) = '02' THEN 'Silvicultura' WHEN left(regexp_replace(CAST("codigo_ciiu" AS VARCHAR), '[^0-9]', '', 'g'), 2) = '03' THEN 'Pesca' ELSE 'Otras actividades' END AS activity, {sex} AS sex, SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY credits DESC''', params)
        fig_activities = px.bar(activities, x="activity", y="credits", color="sex", barmode="group", title="Actividad económica por sexo", labels={"activity": "Actividad económica (CIIU agrupado)", "credits": "Número de créditos", "sex": "Sexo"})

        entities = query(f'''SELECT COALESCE("{COL_ENTITY}", 'Sin dato') AS entity, {sex} AS sex, SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY credits DESC LIMIT 30''', params)
        fig_entities = px.bar(entities, x="credits", y="entity", color="sex", barmode="group", orientation="h", title="Entidades financieras y sexo", labels={"entity": "Entidad", "credits": "Número de créditos", "sex": "Sexo"})

        companies = query(f'''SELECT COALESCE("{COL_COMPANY}", 'Sin dato') AS company, {sex} AS sex, SUM(COALESCE({CREDITS_EXPR}, 0)) AS credits FROM {source} WHERE {where} GROUP BY 1, 2 ORDER BY credits DESC''', params)
        fig_companies = px.bar(companies, x="company", y="credits", color="sex", barmode="group", title="Tamaño de empresa por sexo", labels={"company": "Tamaño de empresa", "credits": "Número de créditos", "sex": "Sexo"})

        figures = [fig_access, fig_timeline, fig_average, fig_rates, fig_rate_timeline, fig_by_type, fig_guarantees, fig_terms, fig_activities, fig_entities, fig_companies]
        for fig in figures:
            fig.update_layout(**common)
        return html.Div([
            html.H2("Análisis de acceso y condiciones por sexo"),
            html.P("Usa los filtros superiores para estudiar diferencias entre mujeres y hombres. Los valores se calculan sobre los registros filtrados y se agregan en DuckDB.", className="analysis-intro"),
            html.Div([analysis_card(fig_access, "Eje X: sexo. Eje Y: valor del indicador. Compara simultáneamente cantidad de créditos y monto desembolsado."), analysis_card(fig_timeline, "Eje X: fecha de corte. Eje Y: número de créditos. Muestra la evolución semanal para cada sexo.")], className="grid-2"),
            html.Div([analysis_card(fig_average, "Eje X: sexo. Eje Y: monto promedio. Se calcula como monto desembolsado dividido entre número de créditos."), analysis_card(fig_rates, "Eje X: tasa efectiva promedio. Eje Y: tipo de crédito. Las barras separan mujeres y hombres.")], className="grid-2"),
            html.Div([analysis_card(fig_rate_timeline, "Eje X: fecha de corte. Eje Y: tasa efectiva promedio. Permite observar cambios temporales por sexo."), analysis_card(fig_by_type, "Eje X: tipo de crédito. Eje Y: número de créditos. Compara la concentración de cada sexo por producto.")], className="grid-2"),
            html.Div([analysis_card(fig_guarantees, "Eje X: tipo de garantía. Eje Y: número de créditos. Ayuda a estudiar diferencias en las garantías utilizadas."), analysis_card(fig_terms, "Eje X: plazo del crédito. Eje Y: número de créditos. Compara las condiciones de plazo por sexo.")], className="grid-2"),
            html.Div([analysis_card(fig_activities, "Eje X: actividad económica agrupada desde CIIU. Eje Y: número de créditos. Destaca agricultura, ganadería, silvicultura y pesca."), analysis_card(fig_entities, "Eje X: número de créditos. Eje Y: entidad financiera. Muestra qué entidades concentran el crédito por sexo.")], className="grid-2"),
            html.Div([analysis_card(fig_companies, "Eje X: tamaño de empresa. Eje Y: número de créditos. Permite ver si un sexo se concentra en unidades productivas más pequeñas.")], className="panel"),
        ], className="analysis-content")
    except Exception as exc:
        return html.Div(f"No se pudo construir el análisis por sexo: {exc}", className="error")


if __name__ == "__main__":
    app.run(debug=os.getenv("DASH_DEBUG", "false").lower() == "true", host="0.0.0.0", port=int(os.getenv("PORT", "8050")))
