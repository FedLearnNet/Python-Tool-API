#!/usr/bin/env bash
# Knows where this repository keeps its version, and nothing more.
# The rules (format, which branch takes which version, what gets released) are the same for all FL-Net
# repositories, so they live once in FedLearnNet/.github (actions/version) instead of in every copy of this file.
# See "Release workflow" in the contribution guide of the Documentation.
#
# Usage:
#   version.sh                  print the version
#   version.sh set <version>    change the version, e.g. 1.1.0.dev, 1.1.0.rc0 or 1.1.0
set -euo pipefail
cd "$(dirname "$0")/../.."

# Stored in pyproject.toml ([project] version); the comment behind it stays
read_version() {
  python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
}
write_version() {
  python3 - "$1" <<'EOF'
import re, sys
path = "pyproject.toml"
text = open(path, encoding="utf-8").read()
text, count = re.subn(r'^version = "[^"]*"', f'version = "{sys.argv[1]}"', text, count=1, flags=re.M)
if count != 1:
    sys.exit("No version line in pyproject.toml")
open(path, "w", encoding="utf-8").write(text)
EOF
}

case "${1:-}" in
  "")
    read_version
    ;;
  set)
    write_version "${2:?Usage: version.sh set <version>}"
    read_version
    ;;
  *)
    echo "Usage: version.sh [set <version>]" >&2
    exit 2
    ;;
esac
