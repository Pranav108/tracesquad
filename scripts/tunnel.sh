#!/usr/bin/env bash
# Kept for old notes: the same as `scripts/serve.sh --tunnel`. See serve.sh.
exec "$(dirname "$0")/serve.sh" --tunnel "$@"
