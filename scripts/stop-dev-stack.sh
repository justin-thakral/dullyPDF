#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${DEV_STACK_BACKEND_CONTAINER:-dullypdf-backend-devstack}"

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  docker rm -f "$CONTAINER_NAME" >/dev/null
  echo "Stopped $CONTAINER_NAME"
else
  echo "No running dev stack container found."
fi

bash scripts/kill_old_processes.sh

rm -f /tmp/dullypdf-firebase-*.json >/dev/null 2>&1 || true
