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


DATA_PATH = Path(os.getenv("DASH_DATA_PATH", "data/tasas_2025.parquet"))
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
    clauses = [f"{COL_RATE} IS NOT NULL"]
    params: list[Any] = []
    if date_range and len(date_range) == 2:
        clauses += [f"{COL_DATE} >= ?", f"{COL_DATE} <= ?"]
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
    Output("cards", "children"), Output("trend", "figure"), Output("by-type", "figure"), Output("by-entity", "figure"), Output("status", "children"),
    Input("f-fecha", "start_date"), Input("f-fecha", "end_date"),
    *[Input(component_id, "value") for component_id in FILTERS],
)
def update_dashboard(start_date, end_date, *filter_values):
    selected = dict(zip(FILTERS, filter_values))
    try:
        where, params = filter_sql(selected, [start_date, end_date])
        source = parquet_expr()
        metrics = query(
            f'''SELECT COUNT(*) AS rows, AVG({COL_RATE}) AS rate,
                       SUM(COALESCE({COL_AMOUNT}, 0)) AS amount,
                       SUM(COALESCE({COL_CREDITS}, 0)) AS credits
                FROM {source} WHERE {where}''', params
        ).iloc[0]
        weekly = query(
            f'''SELECT CAST({COL_DATE} AS DATE) AS date, AVG({COL_RATE}) AS rate,
                       SUM(COALESCE({COL_CREDITS}, 0)) AS credits
                FROM {source} WHERE {where}
                GROUP BY 1 ORDER BY 1''', params
        )
        types = query(
            f'''SELECT COALESCE({COL_TYPE}, 'Sin dato') AS type, AVG({COL_RATE}) AS rate,
                       SUM(COALESCE({COL_CREDITS}, 0)) AS credits
                FROM {source} WHERE {where}
                GROUP BY 1 ORDER BY credits DESC LIMIT 25''', params
        )
        entities = query(
            f'''SELECT COALESCE({COL_ENTITY}, 'Sin dato') AS entity,
                       SUM(COALESCE({COL_CREDITS}, 0)) AS credits,
                       AVG({COL_RATE}) AS rate
                FROM {source} WHERE {where}
                GROUP BY 1 ORDER BY credits DESC LIMIT 20''', params
        )
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
        for fig in (trend, by_type, by_entity):
            fig.update_layout(**common)
        return cards, trend, by_type, by_entity, f"Consulta optimizada · {int(metrics['rows']):,} filas agregadas en DuckDB"
    except FileNotFoundError as exc:
        empty = px.scatter(title="Carga el Parquet para iniciar el dashboard")
        return [html.Div(str(exc), className="error")], empty, empty, empty, "Falta el archivo de datos"


if __name__ == "__main__":
    app.run(debug=os.getenv("DASH_DEBUG", "false").lower() == "true", host="0.0.0.0", port=int(os.getenv("PORT", "8050")))
