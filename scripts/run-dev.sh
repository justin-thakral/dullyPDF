#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.dev.env}"
EXAMPLE="config/backend.dev.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $EXAMPLE. Update values as needed."
    exit 1
  fi
  echo "Missing $ENV_FILE and $EXAMPLE." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

SKIP_PREFLIGHT_RAW="${DULLYPDF_SKIP_PREFLIGHT:-}"
SKIP_PREFLIGHT="$(printf '%s' "$SKIP_PREFLIGHT_RAW" | tr '[:upper:]' '[:lower:]')"
if [[ "$SKIP_PREFLIGHT" != "1" && "$SKIP_PREFLIGHT" != "true" && "$SKIP_PREFLIGHT" != "yes" ]]; then
  bash collaborators/preflight_dev.sh "$ENV_FILE"
fi

if [[ -f "mcp/.env.local" ]]; then
  set -a
  source "mcp/.env.local"
  set +a
fi

BACKEND_PORT="${PORT:-8000}"
FORWARD_TO="${STRIPE_DEV_FORWARD_URL:-http://localhost:${BACKEND_PORT}/api/billing/webhook}"
EVENTS="${STRIPE_DEV_FORWARD_EVENTS:-checkout.session.completed,invoice.paid,customer.subscription.updated,customer.subscription.deleted}"
RUNNER_COMMAND="${DEV_RUN_COMMAND:-npm run dev:core}"
ENABLE_LISTENER_RAW="${STRIPE_DEV_LISTEN_ENABLED:-true}"
ENABLE_LISTENER="$(printf '%s' "$ENABLE_LISTENER_RAW" | tr '[:upper:]' '[:lower:]')"

LISTENER_PID=""
LISTENER_LOG=""

cleanup() {
  if [[ -n "$LISTENER_PID" ]] && kill -0 "$LISTENER_PID" >/dev/null 2>&1; then
    kill "$LISTENER_PID" >/dev/null 2>&1 || true
    wait "$LISTENER_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$LISTENER_LOG" && -f "$LISTENER_LOG" ]]; then
    rm -f "$LISTENER_LOG" || true
  fi
}

trap cleanup EXIT INT TERM

if [[ "$ENABLE_LISTENER" != "false" && "$ENABLE_LISTENER" != "0" && "$ENABLE_LISTENER" != "no" ]]; then
  if [[ -z "${STRIPE_SECRET_KEY:-}" ]]; then
    echo "Stripe forwarding skipped: STRIPE_SECRET_KEY is missing in $ENV_FILE."
  elif ! command -v stripe >/dev/null 2>&1; then
    echo "Stripe forwarding skipped: Stripe CLI is not installed."
  else
    LISTENER_LOG="$(mktemp -t dullypdf-stripe-listen-XXXX.log)"
    echo "Starting Stripe CLI forwarding to ${FORWARD_TO}"
    echo "Forwarded events: ${EVENTS}"
    STRIPE_API_KEY="${STRIPE_SECRET_KEY}" stripe listen --events "$EVENTS" --forward-to "$FORWARD_TO" \
      > >(tee -a "$LISTENER_LOG") \
      2> >(tee -a "$LISTENER_LOG" >&2) &
    LISTENER_PID="$!"

    secret=""
    deadline=$((SECONDS + 20))
    while (( SECONDS < deadline )); do
      if ! kill -0 "$LISTENER_PID" >/dev/null 2>&1; then
        echo "Stripe listener exited before readiness. See output above for details." >&2
        exit 1
      fi
      secret="$(grep -Eo 'whsec_[A-Za-z0-9]+' "$LISTENER_LOG" | tail -n 1 || true)"
      if [[ -n "$secret" ]]; then
        break
      fi
      sleep 0.2
    done

    if [[ -z "$secret" ]]; then
      echo "Failed to capture Stripe webhook signing secret from listener output." >&2
      exit 1
    fi

    # Stripe CLI forwarding does not register a dashboard webhook endpoint, so
    # health enforcement must be disabled locally to allow checkout.
    export STRIPE_WEBHOOK_SECRET="$secret"
    export STRIPE_ENFORCE_WEBHOOK_HEALTH=false
    echo "Stripe forwarding active. Using ephemeral webhook secret from this listener session."
  fi
fi

exec bash -lc "$RUNNER_COMMAND"
