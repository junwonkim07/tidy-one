#!/bin/sh
# Read-only mirror of Aside memory markdown for Basic Memory indexing. Aside stays the owner.
for u in 0 1; do
  src="$HOME/.aside/u/$u/memory/"; dst="$HOME/.basic-memory/mirrors/aside-u$u/"
  [ -d "$src" ] && rsync -a --delete --include='*/' --include='*.md' --exclude='.*' --exclude='*' --prune-empty-dirs "$src" "$dst"
done
