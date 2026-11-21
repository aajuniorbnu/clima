#!/bin/sh
set -eu
PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec ngrok start clima --config "$HOME/Library/Application Support/ngrok/ngrok.yml" --config "$PROJECT_DIR/ngrok.yml" "$@"
