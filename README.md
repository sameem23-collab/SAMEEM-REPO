# Marketing Performance Assessment

This repository contains two parts of the assessment:

- `TASK1_Product_Scoping.md`: Product scoping and delivery plan for an internal marketing performance tool.
- `task2_pipeline.py`: A Python pipeline that ingests public Open-Meteo forecast data and writes it to BigQuery.
- `task2_summary.sql`: A summary query for analyzing loaded BigQuery data.
- `requirements.txt`: Python dependencies for the pipeline.

## Task 1: Product Scoping
Open `TASK1_Product_Scoping.md` for:
- Primary user definition and justification
- What success looks like
- V1 scope decisions with inclusions and exclusions
- Trust-building principles
- A user journey diagram and wireframe
- A README-style section on decisions and future exploration

## Task 2: Pipeline Building
The pipeline demonstrates a full ETL flow with a public API and BigQuery.

### API choice and rationale
- Chosen API: Open-Meteo public forecast API
- Rationale: It is publicly accessible, requires no API key, and returns nested JSON suitable for flattening.
- Marketing relevance: weather is a commonly used campaign signal for timing, channel planning, and seasonal performance analysis.

### How to run the pipeline
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Authenticate with Google Cloud for BigQuery sandbox access. For local testing, use:
   ```bash
   gcloud auth application-default login
   ```
3. Run the pipeline:
   ```bash
   python task2_pipeline.py \
     --project YOUR_PROJECT_ID \
     --dataset marketing_forecast \
     --table weather_channel_signals \
     --start-date 2026-05-26 \
     --end-date 2026-05-28
   ```
4. Use `--dry-run` to fetch and inspect rows without loading into BigQuery:
   ```bash
   python task2_pipeline.py --project YOUR_PROJECT_ID --dataset marketing_forecast --table weather_channel_signals --dry-run
   ```

### BigQuery setup and loading approach
- The script uses `google-cloud-bigquery` and will create the dataset if it does not exist.
- Data is loaded with `write_disposition` set to `WRITE_TRUNCATE` by default.
- A clean, typed schema is defined in the script and includes derived fields.

### SQL query with sample output
Open `task2_summary.sql` and replace `project.dataset.table` with your dataset.
This query aggregates hourly forecast rows by location and date, showing average temperature, humidity, and a derived comfort score.

### Production thinking
- **Scheduling:** Use Cloud Scheduler or Airflow to run on a cadence appropriate for forecast refresh (e.g. daily or twice daily).
- **Failure detection:** Implement alerting on API failures, BigQuery load errors, and row count anomalies.
- **Scaling to 10x volume:** Partition the table by `forecast_date` and shard by location if needed. Use batch load jobs, avoid per-row inserts, and store only the necessary hourly metrics.

## Notes
- The pipeline is intentionally parameterized with dates, endpoints, and location configuration.
- The BigQuery sandbox has no billing account requirement, but still requires a Google project and auth.
