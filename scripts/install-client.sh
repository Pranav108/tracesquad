#!/usr/bin/env bash
# Install `tsq` on a machine where agents run but the TraceSquad API does not (scripts/serve.sh
# already does this on the API's own machine), and tell it once how to find the API:
#
#   scripts/install-client.sh                      discovery = this clone's GitHub repo, `endpoint` branch
#                                                  (kept current by `scripts/serve.sh --publish`)
#   scripts/install-client.sh --discovery <url>    any URL whose body is the API's address
#   scripts/install-client.sh --url <address>      a fixed address (must be updated by hand)
#
# Without a clone on that machine, the same thing by hand:
#   mkdir -p ~/.tracesquad/bin
#   curl -fsSL https://raw.githubusercontent.com/Pranav108/tracesquad/main/bin/tsq -o ~/.tracesquad/bin/tsq
#   chmod +x ~/.tracesquad/bin/tsq
#   echo https://raw.githubusercontent.com/Pranav108/tracesquad/endpoint/api-url > ~/.tracesquad/discovery-url
set -euo pipefail
cd "$(dirname "$0")/.."
TSQ_HOME="${TRACESQUAD_HOME:-$HOME/.tracesquad}"

mkdir -p "$TSQ_HOME/bin"
install -m 755 bin/tsq "$TSQ_HOME/bin/tsq"
case "${1:-}" in
  --discovery) printf '%s\n' "${2:?--discovery needs a URL}" > "$TSQ_HOME/discovery-url" ;;
  --url) printf '%s\n' "${2:?--url needs a URL}" > "$TSQ_HOME/api-url" ;;
  "")
    origin=$(git remote get-url origin 2>/dev/null || true)
    if [[ "$origin" == *github.com* ]]; then
      slug=$(sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##' <<<"$origin")
      printf '%s\n' "https://raw.githubusercontent.com/$slug/endpoint/api-url" > "$TSQ_HOME/discovery-url"
    else
      echo "this clone has no GitHub origin; pass --discovery <url> or --url <address>" >&2
    fi
    ;;
  *) echo "usage: $0 [--discovery <url> | --url <address>]" >&2; exit 2 ;;
esac
echo "installed $TSQ_HOME/bin/tsq"
"$TSQ_HOME/bin/tsq" doctor || true
