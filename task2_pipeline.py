"""Pipeline to ingest Open-Meteo forecast data into BigQuery.

This script is written as a marketing-adjacent ETL example: weather data is a useful signal
for marketing campaign timing, channel planning, and seasonal performance analysis.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from google.cloud import bigquery
from google.cloud.bigquery import SchemaField
from google.api_core.exceptions import NotFound

_logger = logging.getLogger(__name__)

DEFAULT_LOCATIONS = [
    {"name": "New York", "latitude": 40.7128, "longitude": -74.0060},
    {"name": "Los Angeles", "latitude": 34.0522, "longitude": -118.2437},
    {"name": "Chicago", "latitude": 41.8781, "longitude": -87.6298},
]

DEFAULT_API_URL = "https://api.open-meteo.com/v1/forecast"

BQ_SCHEMA = [
    SchemaField("retrieved_at_utc", "TIMESTAMP", mode="REQUIRED"),
    SchemaField("location_name", "STRING", mode="REQUIRED"),
    SchemaField("latitude", "FLOAT", mode="REQUIRED"),
    SchemaField("longitude", "FLOAT", mode="REQUIRED"),
    SchemaField("timezone", "STRING", mode="NULLABLE"),
    SchemaField("forecast_time", "TIMESTAMP", mode="REQUIRED"),
    SchemaField("temperature_c", "FLOAT", mode="NULLABLE"),
    SchemaField("relative_humidity", "FLOAT", mode="NULLABLE"),
    SchemaField("comfort_score", "FLOAT", mode="NULLABLE"),
    SchemaField("forecast_date", "DATE", mode="REQUIRED"),
    SchemaField("source", "STRING", mode="REQUIRED"),
]


class PipelineError(Exception):
    pass


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def log_json(level: int, message: str, **kwargs: Any) -> None:
    payload = {"message": message, **kwargs}
    _logger.log(level, json.dumps(payload, default=str))


def parse_location(value: str) -> Dict[str, Any]:
    parts = value.split("=")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            "Location must be NAME=LAT,LON, for example: NewYork=40.71,-74.01"
        )
    name, coords = parts
    lat_lon = coords.split(",")
    if len(lat_lon) != 2:
        raise argparse.ArgumentTypeError("Location coords must be LAT,LON")
    try:
        return {
            "name": name.strip(),
            "latitude": float(lat_lon[0].strip()),
            "longitude": float(lat_lon[1].strip()),
        }
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Latitude and longitude must be numeric") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load Open-Meteo forecast data into BigQuery."
    )
    parser.add_argument(
        "--project",
        required=True,
        help="BigQuery project ID for sandbox or active project.",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="BigQuery dataset name to write into.",
    )
    parser.add_argument(
        "--table",
        required=True,
        help="BigQuery table name to write into.",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="Base Open-Meteo API URL.",
    )
    parser.add_argument(
        "--start-date",
        type=lambda value: datetime.date.fromisoformat(value),
        default=datetime.date.today(),
        help="Start date for the forecast window (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        type=lambda value: datetime.date.fromisoformat(value),
        default=datetime.date.today() + datetime.timedelta(days=2),
        help="End date for the forecast window (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--location",
        action="append",
        type=parse_location,
        help=(
            "Location to fetch in the format NAME=LAT,LON. "
            "Repeat for multiple locations."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and transform data without loading into BigQuery.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to the existing table instead of replacing it.",
    )
    return parser.parse_args()


def build_api_params(start_date: datetime.date, end_date: datetime.date) -> Dict[str, Any]:
    return {
        "hourly": "temperature_2m,relativehumidity_2m",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timezone": "UTC",
    }


def fetch_forecast(api_url: str, location: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_params = {**params, "latitude": location["latitude"], "longitude": location["longitude"]}
    log_json(logging.INFO, "fetching forecast", location=location["name"], params=request_params)
    response = requests.get(api_url, params=request_params, timeout=15)

    if response.status_code != 200:
        raise PipelineError(
            f"API returned unexpected status {response.status_code}: {response.text}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise PipelineError("Failed to decode JSON response") from exc

    if "hourly" not in payload or "time" not in payload["hourly"]:
        raise PipelineError("API response did not contain expected hourly forecast data")

    return payload


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_comfort_score(temperature_c: Optional[float], humidity: Optional[float]) -> Optional[float]:
    if temperature_c is None or humidity is None:
        return None
    score = 100 - abs(22.0 - temperature_c) * 2.0 - humidity * 0.15
    return max(0.0, min(100.0, round(score, 2)))


def flatten_forecast_json(payload: Dict[str, Any], location: Dict[str, Any]) -> List[Dict[str, Any]]:
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    temperatures = hourly.get("temperature_2m", [])
    humidities = hourly.get("relativehumidity_2m", [])
    timezone = payload.get("timezone")

    if not (len(times) == len(temperatures) == len(humidities)):
        raise PipelineError("Forecast payload arrays have inconsistent lengths")

    rows: List[Dict[str, Any]] = []
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for ts, temp, humidity in zip(times, temperatures, humidities):
        temperature_c = safe_float(temp)
        relative_humidity = safe_float(humidity)
        comfort_score = compute_comfort_score(temperature_c, relative_humidity)
        try:
            forecast_time = datetime.datetime.fromisoformat(ts)
        except ValueError:
            raise PipelineError(f"Unable to parse forecast timestamp: {ts}")

        rows.append(
            {
                "retrieved_at_utc": retrieved_at,
                "location_name": location["name"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "timezone": timezone,
                "forecast_time": forecast_time.isoformat(),
                "temperature_c": temperature_c,
                "relative_humidity": relative_humidity,
                "comfort_score": comfort_score,
                "forecast_date": forecast_time.date().isoformat(),
                "source": "open-meteo",
            }
        )
    log_json(
        logging.INFO,
        "flattened forecast rows",
        location=location["name"],
        row_count=len(rows),
    )
    return rows


def ensure_dataset(client: bigquery.Client, dataset_id: str) -> None:
    try:
        client.get_dataset(dataset_id)
        _logger.info("dataset exists", extra={"dataset": dataset_id})
    except NotFound:
        _logger.info("creating dataset", extra={"dataset": dataset_id})
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = "US"
        client.create_dataset(dataset)


def load_to_bigquery(
    project: str,
    dataset: str,
    table: str,
    rows: List[Dict[str, Any]],
    append: bool,
) -> None:
    client = bigquery.Client(project=project)
    dataset_id = f"{project}.{dataset}"
    ensure_dataset(client, dataset_id)
    table_id = f"{project}.{dataset}.{table}"

    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND if append else bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        autodetect=False,
    )

    log_json(logging.INFO, "loading rows into BigQuery", table=table_id, rows=len(rows), append=append)
    result = client.load_table_from_json(rows, table_id, job_config=job_config).result()
    log_json(
        logging.INFO,
        "BigQuery load complete",
        table=table_id,
        loaded_rows=result.output_rows,
        job_id=result.job_id,
    )


def main() -> int:
    configure_logging()
    args = parse_args()
    locations = args.location if args.location else DEFAULT_LOCATIONS

    if args.end_date < args.start_date:
        _logger.error("end-date must be after or equal to start-date")
        return 1

    api_params = build_api_params(args.start_date, args.end_date)
    all_rows: List[Dict[str, Any]] = []

    for location in locations:
        payload = fetch_forecast(args.api_url, location, api_params)
        rows = flatten_forecast_json(payload, location)
        all_rows.extend(rows)

    log_json(logging.INFO, "total rows prepared", row_count=len(all_rows))

    if args.dry_run:
        print(json.dumps(all_rows[:5], indent=2))
        _logger.info("dry-run complete; no BigQuery load performed")
        return 0

    if not all_rows:
        _logger.warning("no rows to load into BigQuery")
        return 0

    load_to_bigquery(args.project, args.dataset, args.table, all_rows, args.append)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
