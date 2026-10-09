#!/bin/sh
# One-time setup of a fresh Ubuntu 24.04 VPS for tidy-one. Run as root.
#   curl/scp this file to the server, then:  sh bootstrap.sh
# Afterwards: add the two printed deploy keys on GitHub, then rerun to clone and deploy.
set -eu

main() {
  MEMORY_REPO=${MEMORY_REPO:-git@github.com:junwonkim07/claude-memory.git}
  APP_REPO=${APP_REPO:-git@github.com:junwonkim07/tidy-one.git}
  export DEBIAN_FRONTEND=noninteractive

  apt-get update -qq
  apt-get install -y -qq git ufw rsync curl sqlite3 apache2-utils >/dev/null

  swapon --show | grep -q . || { fallocate -l 2G /swapfile; chmod 600 /swapfile; mkswap -q /swapfile; swapon /swapfile; echo "/swapfile none swap sw 0 0" >> /etc/fstab; }
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null

  id memory >/dev/null 2>&1 || useradd -m -s /bin/bash memory
  su - memory -c 'command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    ~/.local/bin/uv tool install basic-memory >/dev/null 2>&1 || true
    test -f ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N "" -C tidy-one-memory -f ~/.ssh/id_ed25519 -q
    ssh-keyscan -q github.com >> ~/.ssh/known_hosts 2>/dev/null'
  test -f /root/.ssh/tidy_one_deploy || ssh-keygen -t ed25519 -N "" -C tidy-one-app -f /root/.ssh/tidy_one_deploy -q
  ssh-keyscan -q github.com >> /root/.ssh/known_hosts 2>/dev/null

  echo "Deploy key for the memory repo (read-write):"; cat /home/memory/.ssh/id_ed25519.pub
  echo "Deploy key for the tidy-one repo (read-only):"; cat /root/.ssh/tidy_one_deploy.pub

  su - memory -c "test -d ~/claude-memory || git clone -q $MEMORY_REPO ~/claude-memory" || { echo "add the memory deploy key, then rerun"; exit 1; }
  su - memory -c 'cd ~/claude-memory && git config user.name tidy-one && git config user.email tidy-one@users.noreply.github.com'
  test -d /opt/tidy-one || GIT_SSH_COMMAND="ssh -i /root/.ssh/tidy_one_deploy -o IdentitiesOnly=yes" git clone -q "$APP_REPO" /opt/tidy-one || { echo "add the tidy-one deploy key, then rerun"; exit 1; }
  git -C /opt/tidy-one config core.sshCommand "ssh -i /root/.ssh/tidy_one_deploy -o IdentitiesOnly=yes"

  sh /opt/tidy-one/server/deploy.sh
}

main "$@"
