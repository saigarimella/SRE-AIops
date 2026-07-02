#!/bin/bash
# ============================================================
# StreamFlix Lab — Reset Metrics
# ============================================================
# Wipes Prometheus's stored history so all SLO/error-budget
# panels go back to a clean 100% baseline. Use this right
# before going live, or any time chaos testing has left the
# dashboards looking permanently "broken" (they're not broken —
# the bad data just hasn't rolled out of the 30m window yet).
#
# This does NOT affect your services, Grafana dashboards, or
# the StreamFlix UI — only Prometheus's stored metric history.

set -e
GREEN='\033[92m'
CYAN='\033[96m'
RESET='\033[0m'

LABDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}Resetting Prometheus metrics history...${RESET}"

docker rm -f prometheus 2>/dev/null || true

docker run -d --name prometheus --network streamflix-net \
  -p 9090:9090 \
  -v "$LABDIR/prometheus.yml:/etc/prometheus/prometheus.yml" \
  prom/prometheus

echo -e "${CYAN}Waiting for Prometheus to come back up...${RESET}"
for i in $(seq 1 20); do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/-/ready 2>/dev/null | grep -q "200"; then
    echo -e "${GREEN}✓ Prometheus is ready${RESET}"
    break
  fi
  sleep 1
done

echo ""
echo -e "${GREEN}✅ Metrics reset!${RESET}"
echo ""
echo "Dashboards will show 'No data' for a few seconds, then"
echo "climb back to a clean 100% baseline as fresh traffic flows in."
echo ""
echo "Tip: wait 20-30 seconds before opening Grafana so the"
echo "SLI panels have at least a little fresh data to average."
