-- Summary query for campaign-relevant weather forecast data in BigQuery.
-- Replace `project.dataset.table` with your actual BigQuery identifiers.

SELECT
  location_name,
  forecast_date,
  COUNT(*) AS hourly_observations,
  ROUND(AVG(temperature_c), 2) AS avg_temperature_c,
  ROUND(AVG(relative_humidity), 2) AS avg_relative_humidity,
  ROUND(AVG(comfort_score), 2) AS avg_comfort_score,
  MIN(forecast_time) AS first_hour,
  MAX(forecast_time) AS last_hour
FROM `project.dataset.table`
GROUP BY location_name, forecast_date
ORDER BY forecast_date DESC, avg_comfort_score DESC
LIMIT 50;

-- Example follow-up query: top 3 locations with the most discomfort risk this week.

-- SELECT
--   location_name,
--   forecast_date,
--   ROUND(AVG(100 - comfort_score), 2) AS avg_discomfort
-- FROM `project.dataset.table`
-- GROUP BY location_name, forecast_date
-- ORDER BY avg_discomfort DESC
-- LIMIT 10;
