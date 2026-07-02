#!/bin/bash
# ============================================================
# StreamFlix Lab — Chaos & Traffic Commands
# ============================================================
# A menu of named commands for traffic generation and chaos
# injection. Run with no arguments to see the menu, or pass a
# command name directly, e.g.:
#
#   ./chaos.sh traffic-normal
#   ./chaos.sh crash-api
#   ./chaos.sh errors
#   ./chaos.sh latency
#   ./chaos.sh recover
#
# All commands are safe to run multiple times.

GREEN='\033[92m'
CYAN='\033[96m'
YELLOW='\033[93m'
RED='\033[91m'
RESET='\033[0m'

usage() {
  echo ""
  echo -e "${CYAN}StreamFlix Lab — Chaos & Traffic Commands${RESET}"
  echo ""
  echo -e "${GREEN}TRAFFIC${RESET}"
  echo "  traffic-normal     Start normal traffic on all 4 services (the default load)"
  echo "  traffic-spike      Spike a service's traffic +50 req/s (asks which — run multiple times on different services to stack)"
  echo "  traffic-stop       Stop ALL traffic generators (normal + spike)"
  echo ""
  echo -e "${YELLOW}CHAOS — each one asks which service to target${RESET}"
  echo "  crash              Crash a service (asks which one — 1-4)"
  echo "  errors             Inject HTTP 500s on a service (asks which one — 1-4)"
  echo "  latency            Inject 2s delay on a service (asks which one — 1-4)"
  echo ""
  echo -e "${GREEN}RECOVERY${RESET}"
  echo "  recover            Stop ALL chaos injectors and restart any crashed services"
  echo ""
  echo -e "${CYAN}RESET${RESET}"
  echo "  reset-metrics      Wipe Prometheus history for a clean 100% baseline (see reset-metrics.sh)"
  echo ""
}

case "$1" in

  traffic-normal)
    echo -e "${CYAN}Starting normal traffic on all 4 services...${RESET}"
    docker rm -f viewers viewers-catalog viewers-streaming viewers-payments 2>/dev/null || true
    docker run -d --name viewers --network streamflix-net busybox \
      sh -c 'while true; do for i in $(seq 1 10); do wget -q -O /dev/null http://streamflix-api:9898/ & done; sleep 1; done'
    docker run -d --name viewers-catalog --network streamflix-net busybox \
      sh -c 'while true; do for i in $(seq 1 5); do wget -q -O /dev/null http://streamflix-catalog:9898/ & done; sleep 1; done'
    docker run -d --name viewers-streaming --network streamflix-net busybox \
      sh -c 'while true; do for i in $(seq 1 8); do wget -q -O /dev/null http://streamflix-streaming:9898/ & done; sleep 1; done'
    docker run -d --name viewers-payments --network streamflix-net busybox \
      sh -c 'while true; do for i in $(seq 1 5); do wget -q -O /dev/null http://streamflix-payments:9898/ & done; sleep 1; done'
    echo -e "${GREEN}✓ Normal traffic running (api:10/s catalog:5/s streaming:8/s payments:5/s)${RESET}"
    ;;

  traffic-spike)
    echo -e "${CYAN}Which service should get the traffic spike?${RESET}"
    echo "  1) API Gateway"
    echo "  2) Catalog"
    echo "  3) Streaming"
    echo "  4) Payments"
    read -p "Enter 1-4: " choice
    case "$choice" in
      1) TARGET="streamflix-api:9898"; LABEL="API Gateway"; SVCTAG="api" ;;
      2) TARGET="streamflix-catalog:9898"; LABEL="Catalog"; SVCTAG="catalog" ;;
      3) TARGET="streamflix-streaming:9898"; LABEL="Streaming"; SVCTAG="streaming" ;;
      4) TARGET="streamflix-payments:9898"; LABEL="Payments"; SVCTAG="payments" ;;
      *) echo -e "${RED}Invalid choice${RESET}"; exit 1 ;;
    esac
    # Unique name every run so repeated spikes on the SAME service ADD UP
    # instead of replacing the previous container.
    SPIKENAME="spike-${SVCTAG}-$(date +%s)-$RANDOM"
    echo -e "${CYAN}Adding a 50 req/s spike to $LABEL...${RESET}"
    docker run -d --name "$SPIKENAME" --network streamflix-net busybox \
      sh -c "while true; do for i in \$(seq 1 50); do wget -q -O /dev/null http://$TARGET/ & done; sleep 1; done"
    RUNNING=$(docker ps --filter "name=spike-${SVCTAG}-" --format '{{.Names}}' | wc -l | tr -d ' ')
    echo -e "${GREEN}✓ Spike running on $LABEL — watch its Traffic line jump${RESET}"
    echo -e "  $RUNNING spike generator(s) now stacked on $LABEL (~$((RUNNING * 50)) req/s from spikes alone)"
    echo -e "  Run this again (same or different service) to stack more"
    echo -e "  Stop all spikes with: ${CYAN}./chaos.sh traffic-stop${RESET}"
    ;;

  traffic-stop)
    echo -e "${CYAN}Stopping all traffic generators...${RESET}"
    docker rm -f viewers viewers-catalog viewers-streaming viewers-payments 2>/dev/null || true
    SPIKE_IDS=$(docker ps -aq --filter "name=spike-")
    if [ -n "$SPIKE_IDS" ]; then
      docker rm -f $SPIKE_IDS 2>/dev/null || true
    fi
    echo -e "${GREEN}✓ All traffic stopped${RESET}"
    ;;

  crash)
    echo -e "${CYAN}Which service do you want to crash?${RESET}"
    echo "  1) API Gateway   (critical — video stops)"
    echo "  2) Catalog       (non-critical — yellow warning, video continues)"
    echo "  3) Streaming     (critical — video stops)"
    echo "  4) Payments      (non-critical — yellow warning, video continues)"
    read -p "Enter 1-4: " choice
    case "$choice" in
      1) SVC="streamflix-api"; PORT=9898; LABEL="API Gateway"; SEVERITY="${RED}CRITICAL — video should stop${RESET}" ;;
      2) SVC="streamflix-catalog"; PORT=9899; LABEL="Catalog"; SEVERITY="${YELLOW}non-critical — yellow warning, video continues${RESET}" ;;
      3) SVC="streamflix-streaming"; PORT=9900; LABEL="Streaming"; SEVERITY="${RED}CRITICAL — video should stop${RESET}" ;;
      4) SVC="streamflix-payments"; PORT=9901; LABEL="Payments"; SEVERITY="${YELLOW}non-critical — yellow warning, video continues${RESET}" ;;
      *) echo -e "${RED}Invalid choice${RESET}"; exit 1 ;;
    esac
    echo -e "${YELLOW}Crashing $LABEL...${RESET}"
    docker rm -f "$SVC" 2>/dev/null || true
    docker run -d --name "$SVC" --network streamflix-net -p "$PORT:9898" stefanprodan/podinfo
    sleep 3
    curl -s "localhost:$PORT/panic" > /dev/null 2>&1 || true
    echo -e "${GREEN}✓ $LABEL crashed — $SEVERITY${RESET}"
    echo -e "  Watch the StreamFlix page and the 'All Services' row in Grafana"
    echo -e "  Bring it back with: ${CYAN}./chaos.sh recover${RESET}"
    ;;


  errors)
    echo -e "${CYAN}Which service should return errors?${RESET}"
    echo "  1) API Gateway"
    echo "  2) Catalog"
    echo "  3) Streaming"
    echo "  4) Payments"
    read -p "Enter 1-4: " choice
    case "$choice" in
      1) TARGET="streamflix-api:9898"; LABEL="API Gateway" ;;
      2) TARGET="streamflix-catalog:9898"; LABEL="Catalog" ;;
      3) TARGET="streamflix-streaming:9898"; LABEL="Streaming" ;;
      4) TARGET="streamflix-payments:9898"; LABEL="Payments" ;;
      *) echo -e "${RED}Invalid choice${RESET}"; exit 1 ;;
    esac
    echo -e "${YELLOW}Injecting continuous HTTP 500 errors on $LABEL...${RESET}"
    docker rm -f errors 2>/dev/null || true
    docker run -d --name errors --network streamflix-net busybox \
      sh -c "while true; do wget -q -O /dev/null http://$TARGET/status/500; done"
    echo -e "${RED}✓ Errors flowing on $LABEL — watch its Success Rate SLO drop (allow 15-20s)${RESET}"
    echo -e "  Stop with: ${CYAN}./chaos.sh recover${RESET}"
    ;;

  latency)
    echo -e "${CYAN}Which service should get slow?${RESET}"
    echo "  1) API Gateway"
    echo "  2) Catalog"
    echo "  3) Streaming"
    echo "  4) Payments"
    read -p "Enter 1-4: " choice
    case "$choice" in
      1) TARGET="streamflix-api:9898"; LABEL="API Gateway" ;;
      2) TARGET="streamflix-catalog:9898"; LABEL="Catalog" ;;
      3) TARGET="streamflix-streaming:9898"; LABEL="Streaming" ;;
      4) TARGET="streamflix-payments:9898"; LABEL="Payments" ;;
      *) echo -e "${RED}Invalid choice${RESET}"; exit 1 ;;
    esac
    echo -e "${YELLOW}Injecting continuous 2s delay on $LABEL...${RESET}"
    docker rm -f slow 2>/dev/null || true
    docker run -d --name slow --network streamflix-net busybox \
      sh -c "while true; do for i in \$(seq 1 10); do wget -q -O /dev/null http://$TARGET/delay/2 & done; sleep 0.5; done"
    echo -e "${RED}✓ Slow traffic flowing on $LABEL — watch its Latency SLO drop (allow 15-20s)${RESET}"
    echo -e "  Stop with: ${CYAN}./chaos.sh recover${RESET}"
    ;;

  recover)
    echo -e "${CYAN}Stopping all chaos and restarting any crashed services...${RESET}"
    docker rm -f errors slow 2>/dev/null || true
    SPIKE_IDS=$(docker ps -aq --filter "name=spike-")
    if [ -n "$SPIKE_IDS" ]; then
      docker rm -f $SPIKE_IDS 2>/dev/null || true
      echo -e "  Cleared stacked traffic spikes too"
    fi
    for svc in streamflix-api streamflix-catalog streamflix-streaming streamflix-payments; do
      docker start "$svc" > /dev/null 2>&1 || true
    done
    echo -e "${GREEN}✓ Recovered — all services should be healthy within a few seconds${RESET}"
    echo -e "  (Baseline traffic from traffic-normal, if running, is untouched — use traffic-stop to kill that too)"
    ;;

  reset-metrics)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$SCRIPT_DIR/reset-metrics.sh" ]; then
      bash "$SCRIPT_DIR/reset-metrics.sh"
    else
      echo -e "${RED}reset-metrics.sh not found in this folder${RESET}"
    fi
    ;;

  *)
    usage
    ;;
esac
