#!/bin/bash
# ============================================================
# StreamFlix Lab — Complete Startup Script (podinfo version)
# ============================================================
# Run this from the folder where you unzipped the lab files.

set -e
GREEN='\033[92m'
CYAN='\033[96m'
RED='\033[91m'
RESET='\033[0m'

# Always operate from the folder this script lives in
LABDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$LABDIR"

echo -e "${CYAN}Starting StreamFlix lab from: $LABDIR${RESET}"

# ── Cleanup any previous run ──────────────────────────────
docker rm -f streamflix-api streamflix-catalog streamflix-streaming \
  streamflix-payments node-exporter prometheus grafana streamflix-ui \
  viewers viewers-catalog viewers-streaming viewers-payments \
  errors slow-traffic 2>/dev/null || true
docker network rm streamflix-net 2>/dev/null || true

# ── Network ────────────────────────────────────────────────
docker network create streamflix-net

# ── 4 podinfo services (each pretending to be a microservice) ──
# NOTE: no --restart flag on purpose — when you crash a service with
# curl localhost:PORT/panic, it should STAY DOWN so the audience can
# see the failure. The AIOps agent (or you, manually) brings it back
# with `docker start <container>`.
docker run -d --name streamflix-api --network streamflix-net \
  -p 9898:9898 stefanprodan/podinfo

docker run -d --name streamflix-catalog --network streamflix-net \
  -p 9899:9898 stefanprodan/podinfo

docker run -d --name streamflix-streaming --network streamflix-net \
  -p 9900:9898 stefanprodan/podinfo

docker run -d --name streamflix-payments --network streamflix-net \
  -p 9901:9898 stefanprodan/podinfo

# ── Node Exporter (your laptop's real metrics) ────────────
docker run -d --name node-exporter --network streamflix-net \
  -p 9100:9100 \
  --pid="host" \
  -v "/:/host:ro,rslave" \
  prom/node-exporter \
  --path.rootfs=/host

# ── Prometheus config ──────────────────────────────────────
cat > "$LABDIR/prometheus.yml" <<'EOF'
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: api-gateway
    static_configs:
      - targets: ['streamflix-api:9898']

  - job_name: catalog
    static_configs:
      - targets: ['streamflix-catalog:9898']

  - job_name: streaming
    static_configs:
      - targets: ['streamflix-streaming:9898']

  - job_name: payments
    static_configs:
      - targets: ['streamflix-payments:9898']

  - job_name: node
    static_configs:
      - targets: ['node-exporter:9100']
EOF

docker run -d --name prometheus --network streamflix-net \
  -p 9090:9090 \
  -v "$LABDIR/prometheus.yml:/etc/prometheus/prometheus.yml" \
  prom/prometheus

# ── Grafana ─────────────────────────────────────────────────
docker run -d --name grafana --network streamflix-net \
  -p 3000:3000 \
  -e GF_AUTH_ANONYMOUS_ENABLED=true \
  -e GF_AUTH_ANONYMOUS_ORG_ROLE=Admin \
  grafana/grafana

# ── Download demo video (once — skipped if already present) ──
mkdir -p "$LABDIR/video"
if [ ! -s "$LABDIR/video/BigBuckBunny.mp4" ]; then
  echo -e "${CYAN}Downloading demo video (64 MB, one-time)...${RESET}"
  if command -v wget >/dev/null 2>&1; then
    wget -q -O "$LABDIR/video/BigBuckBunny.mp4" \
      "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4"
  else
    curl -sL -o "$LABDIR/video/BigBuckBunny.mp4" \
      "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4"
  fi
  echo -e "${GREEN}✓ Video downloaded${RESET}"
else
  echo -e "${GREEN}✓ Video already present${RESET}"
fi

# ── nginx.conf for StreamFlix UI ───────────────────────────
cat > "$LABDIR/nginx.conf" <<'EOF'
resolver 127.0.0.11 valid=5s;
server {
    listen 80;
    location / {
        root /usr/share/nginx/html;
        index index.html;
    }
    location /video/ {
        alias /usr/share/nginx/html/video/;
    }
    location /backend/ {
        set $backend http://streamflix-api:9898;
        proxy_pass $backend;
        rewrite ^/backend/(.*) /$1 break;
    }
    location /svc/api/ {
        set $api http://streamflix-api:9898;
        proxy_pass $api;
        rewrite ^/svc/api/(.*) /$1 break;
    }
    location /svc/catalog/ {
        set $catalog http://streamflix-catalog:9898;
        proxy_pass $catalog;
        rewrite ^/svc/catalog/(.*) /$1 break;
    }
    location /svc/streaming/ {
        set $streaming http://streamflix-streaming:9898;
        proxy_pass $streaming;
        rewrite ^/svc/streaming/(.*) /$1 break;
    }
    location /svc/payments/ {
        set $payments http://streamflix-payments:9898;
        proxy_pass $payments;
        rewrite ^/svc/payments/(.*) /$1 break;
    }
    location /prom/ {
        set $prom http://prometheus:9090;
        proxy_pass $prom;
        rewrite ^/prom/(.*) /$1 break;
    }
}
EOF

# ── StreamFlix UI ───────────────────────────────────────────
docker run -d --name streamflix-ui --network streamflix-net \
  -p 8080:80 \
  -v "$LABDIR/streamflix-live.html:/usr/share/nginx/html/index.html:ro" \
  -v "$LABDIR/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$LABDIR/video:/usr/share/nginx/html/video:ro" \
  nginx:alpine

# ── Traffic generators ──────────────────────────────────────
docker run -d --name viewers --network streamflix-net busybox \
  sh -c 'while true; do for i in $(seq 1 10); do wget -q -O /dev/null http://streamflix-api:9898/ & done; sleep 1; done'

docker run -d --name viewers-catalog --network streamflix-net busybox \
  sh -c 'while true; do for i in $(seq 1 5); do wget -q -O /dev/null http://streamflix-catalog:9898/ & done; sleep 1; done'

docker run -d --name viewers-streaming --network streamflix-net busybox \
  sh -c 'while true; do for i in $(seq 1 8); do wget -q -O /dev/null http://streamflix-streaming:9898/ & done; sleep 1; done'

docker run -d --name viewers-payments --network streamflix-net busybox \
  sh -c 'while true; do for i in $(seq 1 5); do wget -q -O /dev/null http://streamflix-payments:9898/ & done; sleep 1; done'

# ── Wait for Grafana to be truly ready ─────────────────────
echo -e "${CYAN}Waiting for Grafana to be ready...${RESET}"
for i in $(seq 1 30); do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/health 2>/dev/null | grep -q "200"; then
    echo -e "${GREEN}✓ Grafana is ready${RESET}"
    break
  fi
  sleep 1
done

# ── Push data source ─────────────────────────────────────────
DS_RESPONSE=$(curl -s -X POST http://localhost:3000/api/datasources \
  -H "Content-Type: application/json" \
  -d '{"name":"Prometheus","type":"prometheus","uid":"prometheus","url":"http://prometheus:9090","access":"proxy","isDefault":true}')

if echo "$DS_RESPONSE" | grep -q '"id"'; then
  echo -e "${GREEN}✓ Data source added${RESET}"
elif echo "$DS_RESPONSE" | grep -q "already exists\|name-exists"; then
  echo -e "${GREEN}✓ Data source already exists${RESET}"
else
  echo -e "${RED}⚠ Data source response: $DS_RESPONSE${RESET}"
fi

# ── Push dashboard ────────────────────────────────────────────
DASH_RESPONSE=$(curl -s -X POST http://localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d "{\"dashboard\": $(cat "$LABDIR/checkout-slo.json"), \"overwrite\": true}")

if echo "$DASH_RESPONSE" | grep -q '"status":"success"'; then
  echo -e "${GREEN}✓ Dashboard pushed successfully${RESET}"
else
  echo -e "${RED}⚠ Dashboard push response: $DASH_RESPONSE${RESET}"
fi

echo ""
echo -e "${GREEN}✅ DONE! StreamFlix lab is ready.${RESET}"
echo ""
echo "   StreamFlix UI  → http://localhost:8080"
echo "   Prometheus     → http://localhost:9090"
echo "   Grafana        → http://localhost:3000"
echo ""
docker ps --format '{{.Names}}\t{{.Status}}'
