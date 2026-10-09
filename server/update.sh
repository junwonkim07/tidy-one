#!/bin/sh
# Pull-based auto-deploy: runs from tidy-one-update.timer every few minutes.
# If origin/main moved, reset the checkout to it and run deploy.sh. `--force` redeploys anyway.
# Wrapped in main() so the shell has parsed everything before git replaces this file.
set -eu

main() {
  cd /opt/tidy-one
  git fetch -q origin main
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ] || [ "${1:-}" = "--force" ]; then
    git reset -q --hard origin/main
    exec /opt/tidy-one/server/deploy.sh
  fi
}

main "$@"
