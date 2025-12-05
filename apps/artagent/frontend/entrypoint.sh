#!/bin/sh
set -e

echo "🚀 Starting frontend container..."

# Replace placeholder with actual backend URL from environment variable
# Replace backend placeholder used by the REST client
if [ -n "$BACKEND_URL" ]; then
    echo "📝 Replacing __BACKEND_URL__ with: $BACKEND_URL"
    find /app/dist -type f -name "*.js" -exec sed -i "s|__BACKEND_URL__|${BACKEND_URL}|g" {} \;
    find /app/dist -type f -name "*.html" -exec sed -i "s|__BACKEND_URL__|${BACKEND_URL}|g" {} \;
else
    echo "⚠️  BACKEND_URL environment variable not set, using placeholder"
fi

# Determine WS URL (prefer explicit WS_URL, otherwise derive from BACKEND_URL)
derive_ws_url() {
    input="$1"
    case "$input" in
        https://*) echo "${input/https:\/\//wss://}" ;;
        http://*) echo "${input/http:\/\//ws://}" ;;
        *) echo "$input" ;;
    esac
}

if [ -n "$WS_URL" ]; then
    ws_target="$WS_URL"
elif [ -n "$BACKEND_URL" ]; then
    ws_target="$(derive_ws_url "$BACKEND_URL")"
else
    ws_target=""
fi

if [ -n "$ws_target" ]; then
    echo "📝 Replacing __WS_URL__ with: $ws_target"
    find /app/dist -type f -name "*.js" -exec sed -i "s|__WS_URL__|${ws_target}|g" {} \;
    find /app/dist -type f -name "*.html" -exec sed -i "s|__WS_URL__|${ws_target}|g" {} \;
else
    echo "⚠️  WS_URL not set and BACKEND_URL unavailable; leaving __WS_URL__ placeholder"
fi

# Start the application
echo "🌟 Starting serve..."
exec "$@"
