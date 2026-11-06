#!/usr/bin/env bash
# Serve bugmock on this laptop and expose it on a public https URL (Cloudflare quick tunnel).
# No Cloudflare account needed. The URL changes on every start, and stops working when this
# script stops or the laptop sleeps. Ctrl-C stops both the API and the tunnel.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8095}"

# Never tunnel to a port something else already owns: that would publish that service instead.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is already in use; rerun with PORT=<free port> $0" >&2
  exit 1
fi

uv run uvicorn bugmock.api:app --host 127.0.0.1 --port "$PORT" &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT

# Open the tunnel only once bugmock itself answers on the port.
if ! curl -sf --retry 30 --retry-connrefused --retry-delay 1 "http://127.0.0.1:$PORT/openapi.json" | grep -q '"title":"Bugmock"'; then
  echo "bugmock did not come up on port $PORT; not opening a tunnel" >&2
  exit 1
fi

cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" 2>&1 | while IFS= read -r line; do
  echo "$line"
  url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' <<<"$line" || true)
  if [ -n "$url" ]; then
    echo ">>> BUGMOCK_URL=$url"
    # Keep the agent prompts pointing at the live URL (BSD sed, macOS).
    sed -i '' -E "s#https://[a-z0-9-]+\.trycloudflare\.com#$url#g" prompts/*.md
    if ls switch/*.yaml >/dev/null 2>&1; then
      sed -i '' -E "s#https://[a-z0-9-]+\.trycloudflare\.com#$url#g" switch/*.yaml
    fi
    echo ">>> prompts/*.md now use $url"
  fi
done
