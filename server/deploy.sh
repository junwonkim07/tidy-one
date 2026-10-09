#!/bin/sh
# Idempotent deploy for the tidy-one server. Run as root from /opt/tidy-one.
# Installs systemd units, applies Basic Memory settings and (re)starts what changed.
# The public connector (memory-proxy) only starts when /etc/tidy-one/proxy.env exists,
# which the owner creates with server/enable-connector.sh.
set -eu

main() {
  REPO=/opt/tidy-one
  PROXY_VERSION=v2.10.2
  EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  cd "$REPO"

  if ! id memory >/dev/null 2>&1 || [ ! -x /home/memory/.local/bin/bm ]; then
    echo "tidy-one: user 'memory' or Basic Memory missing; run server/bootstrap.sh first" >&2
    exit 1
  fi

  chmod +x server/*.sh server/bin/*.sh

  # mcp-auth-proxy binary, pinned
  if [ ! -x /usr/local/bin/mcp-auth-proxy ] || [ "$(cat /usr/local/lib/tidy-one-proxy.version 2>/dev/null)" != "$PROXY_VERSION" ]; then
    curl -fsSL -o /usr/local/bin/mcp-auth-proxy \
      "https://github.com/sigbit/mcp-auth-proxy/releases/download/$PROXY_VERSION/mcp-auth-proxy-linux-amd64"
    chmod +x /usr/local/bin/mcp-auth-proxy
    mkdir -p /usr/local/lib && echo "$PROXY_VERSION" > /usr/local/lib/tidy-one-proxy.version
  fi

  # Basic Memory settings: never rewrite the git-tracked markdown, multilingual embeddings
  su - memory -c "PATH=\$HOME/.local/bin:\$PATH
    bm config set disable_permalinks true >/dev/null
    bm config set ensure_frontmatter_on_sync false >/dev/null
    bm config set semantic_embedding_model $EMBED_MODEL >/dev/null
    bm config set semantic_min_similarity 0.3 >/dev/null
    bm project list 2>/dev/null | grep -q claude-memory || bm project add claude-memory ~/claude-memory --default --local >/dev/null
    for u in 0 1; do
      [ -d ~/mirrors/aside-u\$u ] && { bm project list 2>/dev/null | grep -q aside-u\$u || bm project add aside-u\$u ~/mirrors/aside-u\$u --local >/dev/null; }
    done
    true"

  # systemd units
  changed=""
  for f in server/systemd/*; do
    name=$(basename "$f")
    if ! cmp -s "$f" "/etc/systemd/system/$name"; then
      install -m 644 "$f" "/etc/systemd/system/$name"
      changed="$changed $name"
    fi
  done
  [ -n "$changed" ] && systemctl daemon-reload

  systemctl enable --now basic-memory.service memory-sync.timer tidy-one-update.timer >/dev/null 2>&1
  case "$changed" in *basic-memory.service*) systemctl restart basic-memory.service ;; esac

  if [ -f /etc/tidy-one/proxy.env ]; then
    systemctl enable memory-proxy.service >/dev/null 2>&1
    case "$changed" in
      *memory-proxy.service*|*basic-memory.service*) systemctl restart memory-proxy.service ;;
      *) systemctl is-active -q memory-proxy.service || systemctl start memory-proxy.service ;;
    esac
  fi

  echo "tidy-one: deployed $(git -C "$REPO" rev-parse --short HEAD)${changed:+ (units:$changed)}"
}

main "$@"
