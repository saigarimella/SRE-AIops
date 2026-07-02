# StreamFlix SRE + AIOps Lab

Everything you need is in this folder. No manual setup steps.

## Quick start

1. Make sure Docker Desktop is running.
2. Open a terminal in this folder.
3. Run:

   chmod +x start.sh cleanup.sh
   ./start.sh

That's it. The script will:
- Clean up any previous run
- Create the Docker network
- Start 4 microservices (API Gateway, Catalog, Streaming, Payments)
- Start Prometheus + Grafana + node-exporter
- Download the demo video (first run only, ~64 MB)
- Start the StreamFlix video player UI
- Start traffic generators
- Push the Grafana dashboard automatically

When it finishes, open:

  StreamFlix UI   →  http://localhost:8080
  Grafana         →  http://localhost:3000
  Prometheus      →  http://localhost:9090

## To stop everything

   ./cleanup.sh

This removes every container and the Docker network. Your files
(HTML, dashboard JSON, scripts) are untouched — run ./start.sh
again anytime to bring it all back up.

## To reset the SLO/error-budget dashboards to a clean baseline

   ./reset-metrics.sh

After running chaos experiments, the SLO panels will show the
effects for up to 30 minutes (that's the rolling window they
use — this is correct behavior, not a bug). If you want a clean
100% baseline again (e.g. right before going live), run this —
it wipes Prometheus's stored history without touching your
running services, Grafana dashboards, or the StreamFlix UI.

## Traffic + Chaos commands

Use chaos.sh for everything — traffic generation, chaos injection,
and recovery, all as simple commands. The chaos commands now ask
which service to target (1-4), so you can demo any of the 4
microservices on the fly:

   chmod +x chaos.sh
   ./chaos.sh                 (shows the full menu)

   ./chaos.sh traffic-normal  Start normal traffic on all 4 services
   ./chaos.sh traffic-spike   Spike traffic on a service (asks which)
   ./chaos.sh traffic-stop    Stop all traffic generators

   ./chaos.sh crash           Crash a service (asks which — 1-4)
   ./chaos.sh errors          Inject HTTP 500s (asks which — 1-4)
   ./chaos.sh latency         Inject 2s delay (asks which — 1-4)

   ./chaos.sh recover         Stop all chaos, restart crashed services
   ./chaos.sh reset-metrics   Wipe Prometheus history for a clean baseline

When you run ./chaos.sh crash, it shows:
   1) API Gateway   (critical — video stops)
   2) Catalog       (non-critical — yellow warning, video continues)
   3) Streaming     (critical — video stops)
   4) Payments      (non-critical — yellow warning, video continues)

NOTE: crashed services do NOT auto-restart — this is intentional,
so the audience can clearly see the "down" state. Always follow
a crash demo with ./chaos.sh recover before starting the next one.

The Grafana dashboard now shows golden signals (traffic, up/down,
latency, errors) for ALL 4 services as separate coloured lines in
each panel — so whichever service you crash or slow down, you'll
see exactly which line reacts.

## AIOps agent

Get a free Groq API key at https://console.groq.com (no credit card).

   export GROQ_API_KEY='your-key-here'
   python3 aiops-agent.py

This monitors all 4 services, detects anomalies via z-score,
calls Groq for root-cause diagnosis, and auto-restarts the
broken container. It also writes an incident postmortem after
each recovery.

## Observability chat

   export GROQ_API_KEY='your-key-here'
   python3 obs-chat.py

Ask questions in plain English:
   "What's the current error rate?"
   "Did any service crash recently?"
   "Show me errors in the logs"

## Pre-event check

Before the actual session, run:

   python3 preflight.py

This verifies Docker, Python, your Groq key, and pulls all
required images in advance.

## Files in this folder

  start.sh                 - one command to start everything
  cleanup.sh                - one command to stop everything
  streamflix-live.html      - the video player UI
  checkout-slo.json         - the Grafana dashboard definition
  aiops-agent.py             - the self-healing AIOps agent
  obs-chat.py                - natural language observability chatbot
  preflight.py                - pre-event setup checker
  video/                      - created automatically on first run
