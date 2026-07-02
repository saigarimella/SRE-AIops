#!/bin/bash
# ============================================================
# StreamFlix Lab — Full Cleanup Script
# ============================================================
GREEN='\033[92m'
CYAN='\033[96m'
RESET='\033[0m'

LABDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}Cleaning up StreamFlix lab...${RESET}"

# ── Remove all lab containers ────────────────────────────────
docker rm -f \
  streamflix-api streamflix-catalog streamflix-streaming streamflix-payments \
  node-exporter prometheus grafana streamflix-ui \
  viewers viewers-catalog viewers-streaming viewers-payments \
  errors slow-traffic spike 2>/dev/null || true

# ── Remove the network ───────────────────────────────────────
docker network rm streamflix-net 2>/dev/null || true

# ── Remove generated config files (keep the source files) ───
rm -f "$LABDIR/prometheus.yml"

echo ""
echo -e "${GREEN}✅ All clean!${RESET}"
echo ""
echo "Verify nothing is left running:"
docker ps -a --format '{{.Names}}' | grep -E "streamflix|prometheus|grafana|node-exporter|viewers|errors|slow-traffic" && \
  echo "⚠ Some containers still exist (see above)" || \
  echo "✓ No StreamFlix containers remain"
