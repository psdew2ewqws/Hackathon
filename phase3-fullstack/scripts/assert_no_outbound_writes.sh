#!/usr/bin/env bash
# Isolation assertion for §7.7 — exits non-zero if any outbound-write HTTP
# pattern shows up in the Python source. Safe to run in CI. A judge can run
# this to confirm the system never POSTs to operational traffic
# infrastructure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ROOT="${ROOT}/src"

# Patterns that would indicate an outbound write.
PATTERNS=(
    'requests\.(post|put|delete|patch)'
    'httpx\.(post|put|delete|patch)'
    'aiohttp\.ClientSession.*(post|put|delete|patch)'
    'urllib\.request\.urlopen.*(method=.POST|method=.PUT|method=.DELETE)'
    'smtplib\.'
    'socket\.send(all)?.*(to:|:514|:9092)'  # syslog / kafka
)

FOUND=""
for p in "${PATTERNS[@]}"; do
    if grep -rIEn "$p" "$SRC_ROOT" 2>/dev/null; then
        FOUND=1
    fi
done

if [[ -n "$FOUND" ]]; then
    echo "[isolation] FAIL — outbound-write patterns found above." >&2
    exit 1
fi

echo "[isolation] PASS — no outbound-write patterns in ${SRC_ROOT}"
exit 0
