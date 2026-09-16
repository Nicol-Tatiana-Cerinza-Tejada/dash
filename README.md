# Dash — Tasas de interés activas 2025

Dashboard interactivo en Plotly Dash para el dataset de tasas de interés activas de la Superintendencia Financiera (`w9zh-vetq`, datos.gov.co).

## Rendimiento

El dashboard está pensado para archivos grandes (el notebook reporta aproximadamente 36,8 millones de filas en 2025):

- DuckDB consulta directamente el Parquet y ejecuta filtros/agregaciones en el motor.
- El navegador recibe únicamente series y top-N agregados, nunca el dataset completo.
- Los gráficos limitan entidades y tipos a los grupos más relevantes.
- `DASH_DATA_PATH` permite apuntar a un Parquet fuera del repositorio, evitando subir varios GB a GitHub.

## Ejecutar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data
# Copia aquí tasas_2025.parquet, generado por el notebook de EDA.
python3 app.py
```

Abre <http://localhost:8050>.

También puedes indicar otra ubicación:

```bash
DASH_DATA_PATH=/ruta/tasas_2025.parquet python3 app.py
```

## Datos

El notebook `EDA_tasas_interes_2025 (1).ipynb` contiene la descarga reproducible desde datos.gov.co, por semana, y la generación de `tasas_2025.parquet`. Para probar rápido, descarga algunas semanas ajustando `SEMANAS_A_DESCARGAR`; para el dashboard completo usa `None`.

Fuente: [Tasas de interés activas por tipo de crédito](https://www.datos.gov.co/Econom-a-y-Finanzas/Tasas-de-inter-s-activas-por-tipo-de-cr-dito-Hist-/w9zh-vetq/about_data).
