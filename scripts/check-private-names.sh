#!/usr/bin/env bash
# Fail if a tracked file names an organisation that must stay private.
#
# The names themselves are private, so they are never in this repository: put them, one per
# line (a fixed string, matched case-insensitively), in a file outside git and pass it as
# $LEGAL_PRIVATE_NAMES, or keep them in ./.private-names (gitignored). CI reads them from the
# repository secret of the same name. With no list, the check says it was skipped.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
list="${LEGAL_PRIVATE_NAMES:-.private-names}"
if [ ! -s "$list" ]; then
  echo "  -- private-name check skipped: no list at $list"
  exit 0
fi
patterns=$(mktemp)
trap 'rm -f "$patterns"' EXIT
grep -v '^[[:space:]]*\(#\|$\)' "$list" > "$patterns" || true
count=$(wc -l < "$patterns")
# Tracked and untracked-but-not-ignored files: what a commit could carry.
if git ls-files -z --cached --others --exclude-standard | xargs -0 grep -I -n -i -F -f "$patterns" -- 2>/dev/null; then
  echo "  !! a private name appears above; replace it with an example name" >&2
  exit 1
fi
echo "  ok no private name ($count checked)"
