#!/usr/bin/env bash
# Copy to 00-vars.local.sh, fill values locally, and never commit real secrets.
set -euo pipefail

export AZURE_RESOURCE_GROUP="viettrip-rg"
export AZURE_LOCATION="southeastasia"
export AZURE_ACR_NAME="viettripacr"
export AZURE_CONTAINERAPPS_ENV="viettrip-aca-env"
export AZURE_LOG_ANALYTICS="viettrip-logs"

export IMAGE_NAME="viettrip-ai"
export IMAGE_TAG="dev-placeholder"
export IMAGE="${AZURE_ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}"

export WEB_APP_NAME="viettrip-web"
export MIGRATION_JOB_NAME="viettrip-migrate"
export MEMORY_WORKER_JOB_NAME="viettrip-memory-worker"
export BACKFILL_JOB_NAME="viettrip-backfill-embeddings"

# Secret values: set these in your shell/session or secret store, not in git.
export DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
export COOKIE_SECRET="replace-with-generated-secret"
export GOOGLE_API_KEY="replace-with-google-api-key"
export RAPIDAPI_KEY="replace-with-rapidapi-key"
export WEATHER_API_KEY="replace-with-weather-api-key"
export LANGSMITH_API_KEY=""

# Non-secret runtime defaults.
export COOKIE_SECURE="true"
export BOOKING_RAPIDAPI_HOST="booking-com15.p.rapidapi.com"
export GEOCODING_RAPIDAPI_HOST="booking-com15.p.rapidapi.com"
export GOOGLE_FLIGHT_RAPIDAPI_HOST="google-flights2.p.rapidapi.com"
export BOOKING_LANGUAGE_CODE="vi"
export BOOKING_CURRENCY_CODE="VND"
export COUNTRY_CODE="vn"
export LONG_TERM_MEMORY_RECALL_ENABLED="false"
export LONG_TERM_MEMORY_WRITE_ENABLED="false"
export LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED="false"
export LONG_TERM_MEMORY_VECTOR_FALLBACK_ENABLED="true"
export LONG_TERM_MEMORY_EXTRACTOR="deterministic"
export LONG_TERM_MEMORY_VERIFIER="deterministic"

# Revision/traffic controls.
export WEB_MIN_REPLICAS="1"
export WEB_MAX_REPLICAS="3"
export WEB_CPU="1.0"
export WEB_MEMORY="2.0Gi"
export WORKER_CRON_EXPRESSION="*/1 * * * *"
