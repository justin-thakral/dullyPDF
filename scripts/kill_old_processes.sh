#!/bin/bash

# Kill Old Backend/Frontend Processes
# This script ensures only one instance of the backend/frontend is running

echo "Checking for running processes..."

# Resolve repo root for more precise process matching.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Find uvicorn backend processes (FastAPI)
UVICORN_PIDS=$(pgrep -f 'uvicorn .*backend\.main:app' 2>/dev/null || true)

# Find vite frontend processes for this repo
VITE_PIDS=$(pgrep -f "vite.*${REPO_ROOT}/frontend" 2>/dev/null || true)

count_pids() {
    if [ -z "$1" ]; then
        echo 0
        return
    fi
    local count=0
    for _pid in $1; do
        count=$((count + 1))
    done
    echo "$count"
}

UVICORN_COUNT=$(count_pids "$UVICORN_PIDS")
VITE_COUNT=$(count_pids "$VITE_PIDS")

if [ "$UVICORN_COUNT" -eq "0" ] && [ "$VITE_COUNT" -eq "0" ]; then
    echo "No old processes found. Starting fresh..."
    exit 0
fi

echo ""
echo "Found running processes:"

if [ "$UVICORN_COUNT" -gt "0" ]; then
    echo "   Backend (uvicorn): $UVICORN_COUNT process(es)"
    echo "   PIDs: $UVICORN_PIDS"
fi

if [ "$VITE_COUNT" -gt "0" ]; then
    echo "   Frontend (vite): $VITE_COUNT process(es)"
    echo "   PIDs: $VITE_PIDS"
fi

echo ""
echo "Killing old processes..."

# Kill uvicorn processes
if [ -n "$UVICORN_PIDS" ]; then
    echo "$UVICORN_PIDS" | xargs kill -9 2>/dev/null || true
    echo "   Killed backend processes"
fi

# Kill vite processes
if [ -n "$VITE_PIDS" ]; then
    echo "$VITE_PIDS" | xargs kill -9 2>/dev/null || true
    echo "   Killed frontend processes"
fi

# Wait a moment for processes to die
sleep 1

# Verify they're gone
REMAINING_UVICORN=$(pgrep -f 'uvicorn .*backend\.main:app' 2>/dev/null || true)
REMAINING_VITE=$(pgrep -f "vite.*${REPO_ROOT}/frontend" 2>/dev/null || true)

REMAINING_UVICORN_COUNT=$(count_pids "$REMAINING_UVICORN")
REMAINING_VITE_COUNT=$(count_pids "$REMAINING_VITE")

if [ "$REMAINING_UVICORN_COUNT" -eq "0" ] && [ "$REMAINING_VITE_COUNT" -eq "0" ]; then
    echo ""
    echo "All old processes killed successfully."
else
    echo ""
    echo "Warning: Some processes may still be running"
    echo "   Backend remaining: $REMAINING_UVICORN_COUNT"
    echo "   Frontend remaining: $REMAINING_VITE_COUNT"
fi

exit 0
