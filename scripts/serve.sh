#!/usr/bin/env bash
# Run the TraceSquad API on this machine and register where it is, so every agent's `tsq` finds it.
#
#   scripts/serve.sh             local only: http://127.0.0.1:$PORT (agents on this machine)
#   scripts/serve.sh --tunnel    also a public https URL (Cloudflare quick tunnel; needs cloudflared)
#   scripts/serve.sh --publish   --tunnel, and push the public URL to the repo's `endpoint` branch,
#                                where `tsq` on other machines discovers it
#
# Every start: installs bin/tsq as ~/.tracesquad/bin/tsq and writes the local URL to
# ~/.tracesquad/api-url. Prompts and the Switch template never contain a URL, so restarting the API,
# changing PORT or getting a new tunnel URL needs no change to any agent. Ctrl-C stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8095}"
TSQ_HOME="${TRACESQUAD_HOME:-$HOME/.tracesquad}"
REMOTE="${TRACESQUAD_PUBLISH_REMOTE:-origin}"
TUNNEL=0
PUBLISH=0
for arg in "$@"; do
  case "$arg" in
    --tunnel) TUNNEL=1 ;;
    --publish) TUNNEL=1; PUBLISH=1 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

if [ "$TUNNEL" = 1 ] && ! command -v cloudflared >/dev/null; then
  echo "--tunnel needs cloudflared: brew install cloudflared" >&2
  exit 1
fi
if [ "$PUBLISH" = 1 ] && ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "--publish pushes to the git remote '$REMOTE', and this clone has none." >&2
  echo "Add one (git remote add origin <url>) or set TRACESQUAD_PUBLISH_REMOTE." >&2
  exit 1
fi

# Never serve on (or tunnel to) a port something else already owns.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is already in use; rerun with PORT=<free port> $0" >&2
  exit 1
fi

LOCAL_URL="http://127.0.0.1:$PORT"
uv run uvicorn tracesquad.api:app --host 127.0.0.1 --port "$PORT" &
API_PID=$!

cleanup() {
  kill "$API_PID" 2>/dev/null || true
  # Forget this address only if it is still ours, so a newer serve.sh keeps its registration.
  if [ "$(head -n 1 "$TSQ_HOME/api-url" 2>/dev/null)" = "$LOCAL_URL" ]; then
    rm -f "$TSQ_HOME/api-url"
  fi
}
trap cleanup EXIT

if ! curl -sf --retry 30 --retry-connrefused --retry-delay 1 "$LOCAL_URL/health" | grep -q '"tracesquad-api"'; then
  echo "the TraceSquad API did not come up on port $PORT" >&2
  exit 1
fi

mkdir -p "$TSQ_HOME/bin"
install -m 755 bin/tsq "$TSQ_HOME/bin/tsq"
printf '%s\n' "$LOCAL_URL" > "$TSQ_HOME/api-url"
echo ">>> TraceSquad API on $LOCAL_URL"
echo ">>> agents on this machine call it with $TSQ_HOME/bin/tsq (check: $TSQ_HOME/bin/tsq doctor)"

# The repo's `endpoint` branch holds one file, api-url. Each publish replaces the branch with a single
# fresh commit, built with git plumbing so the working tree and the current branch are never touched.
publish() {
  local url="$1" blob tree commit slug
  blob=$(printf '%s\n' "$url" | git hash-object -w --stdin)
  tree=$(printf '100644 blob %s\tapi-url\n' "$blob" | git mktree)
  commit=$(git commit-tree "$tree" -m "endpoint: $url")
  if git push --force --quiet "$REMOTE" "${commit}:refs/heads/endpoint"; then
    echo ">>> published $url to the '$REMOTE' remote's endpoint branch"
    slug=$(git remote get-url "$REMOTE" | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')
    if [[ "$(git remote get-url "$REMOTE")" == *github.com* ]]; then
      echo ">>> discovery URL for other machines: https://raw.githubusercontent.com/$slug/endpoint/api-url"
    fi
  else
    echo ">>> could not push the endpoint branch; agents on other machines won't see this URL" >&2
  fi
}

if [ "$TUNNEL" = 0 ]; then
  wait "$API_PID"
  exit $?
fi

cloudflared tunnel --no-autoupdate --url "$LOCAL_URL" 2>&1 | while IFS= read -r line; do
  echo "$line"
  url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' <<<"$line" || true)
  if [ -n "$url" ]; then
    echo ">>> public URL: $url (agents on this machine keep using $LOCAL_URL)"
    if [ "$PUBLISH" = 1 ]; then publish "$url"; fi
  fi
done
