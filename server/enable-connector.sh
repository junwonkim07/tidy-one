#!/bin/sh
# Owner-only step, run on your Mac: turn on the public, password-protected MCP connector
# for claude.ai web/mobile. Nothing here runs automatically.
#   sh server/enable-connector.sh <server-ip>
# - creates a random password, saved only on this Mac (~/.config/tidy-one/password)
# - sends just its bcrypt hash + the public URL to the server (/etc/tidy-one/proxy.env, root-only)
# - starts memory-proxy (auto TLS on https://<ip-with-dashes>.sslip.io)
set -eu

main() {
  HOST=${1:?usage: enable-connector.sh <server-ip>}
  KEY=${TIDY_ONE_SSH_KEY:-$HOME/.ssh/memory_server_ed25519}
  SSH="ssh -i $KEY -o BatchMode=yes root@$HOST"
  URL="https://$(echo "$HOST" | tr . -).sslip.io"

  mkdir -p "$HOME/.config/tidy-one" && chmod 700 "$HOME/.config/tidy-one"
  PWF="$HOME/.config/tidy-one/password"
  [ -f "$PWF" ] || { python3 -c "import secrets;print(secrets.token_urlsafe(24))" > "$PWF"; chmod 600 "$PWF"; }

  HASH=$($SSH 'htpasswd -niBC 12 x | cut -d: -f2' < "$PWF")
  [ -n "$HASH" ] || { echo "failed to hash password" >&2; exit 1; }
  printf "EXTERNAL_URL=%s\nPW_HASH='%s'\n" "$URL" "$HASH" | $SSH 'umask 077; mkdir -p /etc/tidy-one; cat > /etc/tidy-one/proxy.env'
  $SSH 'systemctl enable --now memory-proxy.service && sleep 10 && systemctl is-active memory-proxy.service'

  echo "Connector URL: $URL/mcp"
  echo "Password file: $PWF"
}

main "$@"
