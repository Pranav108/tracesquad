#!/bin/sh
# Run the herald, which links the public room and the squad's work log (docs/HERALD.md).
#
#   scripts/herald.sh            run it in the foreground (Ctrl-C stops it)
#   scripts/herald.sh check      find the bot and both channels; changes nothing
#   scripts/herald.sh status     the bugs it is tracking
#
# Reads ~/.tracesquad/herald.json (or --config <file>) and the bot token from
# ~/.tracesquad/herald-token or TRACESQUAD_HERALD_TOKEN.
set -eu
cd "$(dirname "$0")/.."
command="${1:-run}"
[ $# -gt 0 ] && shift
exec uv run python -m tracesquad.herald "$command" "$@"
