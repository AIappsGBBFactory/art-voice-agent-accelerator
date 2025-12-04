#!/bin/bash

# ============================================================
# Script: start_frontend.sh
# Purpose: Start the frontend Vite + React dev server.
# ============================================================

set -e

# Resolve project root (find directory containing environment.yaml)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/apps/artagent/frontend"

# Run frontend dev server
function start_frontend() {
    if [[ ! -d "$FRONTEND_DIR" ]]; then
        echo "Error: Frontend directory not found at $FRONTEND_DIR"
        exit 1
    fi

    echo "Starting frontend in $FRONTEND_DIR"
    cd "$FRONTEND_DIR"
    npm install
    npm run dev
}

function start_frontend_preview() {
    if [[ ! -d "$FRONTEND_DIR" ]]; then
        echo "Error: Frontend directory not found at $FRONTEND_DIR"
        exit 1
    fi

    echo "Starting frontend in production mode in $FRONTEND_DIR"
    cd "$FRONTEND_DIR"
    npm run build
    npm run start
}

start_frontend
