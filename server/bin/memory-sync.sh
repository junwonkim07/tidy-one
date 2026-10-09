#!/bin/sh
# Keep the server copy of the memory repo in step with GitHub.
# Pulls edits from other devices; commits and pushes edits made through the server MCP.
cd "$HOME/claude-memory" || exit 0
git pull -q --rebase --autostash || exit 0
git add -A
git diff --cached --quiet || git commit -q -m "memory: update from tidy-one server"
git status -sb | head -1 | grep -q ahead && git push -q
exit 0
