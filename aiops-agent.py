#!/usr/bin/env python3
"""
StreamFlix AIOps Agent v3.0 — Microservices Edition
=====================================================
Monitors 4 microservices, detects anomalies per-service,
calls Groq for root-cause analysis, auto-remediates.

Usage:
    export GROQ_API_KEY="your-key"
    python3 aiops-agent.py
"""

import os, sys, time, json, statistics, subprocess, textwrap
from datetime import datetime
from collections import deque

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run:  pip install requests")
    sys.exit(1)

PROMETHEUS    = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
WINDOW_SIZE   = int(os.getenv("WINDOW_SIZE", "30"))
Z_THRESHOLD   = float(os.getenv("Z_THRESHOLD", "3.0"))
COOLDOWN      = int(os.getenv("COOLDOWN", "60"))

GROQ_KEY      = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL    = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_KEY    = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL  = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SERVICES = {
    "api-gateway":  {"container": "streamflix-api",       "port": 9898, "label": "API Gateway"},
    "catalog":      {"container": "streamflix-catalog",   "port": 9899, "label": "Catalog"},
    "streaming":    {"container": "streamflix-streaming",  "port": 9900, "label": "Streaming"},
    "payments":     {"container": "streamflix-payments",   "port": 9901, "label": "Payments"},
}

def get_llm_provider():
    if GROQ_KEY: return "groq"
    elif GEMINI_KEY: return "gemini"
    return None

LLM_PROVIDER = get_llm_provider()

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def banner():
    p = "Groq (Llama 70B)" if LLM_PROVIDER == "groq" else \
        "Google Gemini" if LLM_PROVIDER == "gemini" else "None"
    svc_list = ", ".join(s["label"] for s in SERVICES.values())
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════╗
║    StreamFlix AIOps Agent v3.0 — Microservices   ║
║  Anomaly Detection → LLM RCA → Auto-Remediation ║
╚══════════════════════════════════════════════════╝{RESET}

  Prometheus : {PROMETHEUS}
  LLM        : {p}
  LLM key    : {'✓ set' if LLM_PROVIDER else '✗ not set'}
  Services   : {svc_list}
  Poll       : {POLL_INTERVAL}s | Window: {WINDOW_SIZE} | Z: {Z_THRESHOLD}
  Cooldown   : {COOLDOWN}s
""")

def prom_query(expr):
    try:
        r = requests.get(f"{PROMETHEUS}/api/v1/query", params={"query": expr}, timeout=5)
        data = r.json()
        if data["status"] == "success" and data["data"]["result"]:
            return float(data["data"]["result"][0]["value"][1])
    except: pass
    return None

def gather_all_metrics():
    """Gather metrics for ALL services."""
    all_metrics = {}
    for job, info in SERVICES.items():
        m = {}
        total = prom_query(f'sum(rate(http_requests_total{{job="{job}"}}[1m]))')
        errors = prom_query(f'sum(rate(http_requests_total{{job="{job}",status=~"5.."}}[1m]))')
        if total and total > 0 and errors is not None:
            m["error_rate"] = round((errors / total) * 100, 2)
        else:
            m["error_rate"] = 0.0
        lat = prom_query(f'1000 * histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{job="{job}"}}[1m])))')
        m["latency_p95_ms"] = round(lat, 2) if lat else 0.0
        m["traffic_rps"] = round(total, 2) if total else 0.0
        up = prom_query(f'up{{job="{job}"}}')
        m["service_up"] = int(up) if up is not None else 0
        goroutines = prom_query(f'go_goroutines{{job="{job}"}}')
        m["goroutines"] = int(goroutines) if goroutines else 0
        m["job"] = job
        m["label"] = info["label"]
        m["container"] = info["container"]
        all_metrics[job] = m
    return all_metrics

class MultiServiceDetector:
    def __init__(self):
        self.histories = {}
        self.baselines = {}
        for job in SERVICES:
            self.histories[job] = {
                "error_rate": deque(maxlen=WINDOW_SIZE),
                "latency_p95_ms": deque(maxlen=WINDOW_SIZE),
            }
            self.baselines[job] = {"traffic": deque(maxlen=WINDOW_SIZE), "baseline_traffic": None}

    def check(self, all_metrics):
        anomalies = []
        for job, metrics in all_metrics.items():
            info = SERVICES[job]

            # Z-score checks (spikes)
            for key in self.histories[job]:
                value = metrics.get(key, 0)
                window = self.histories[job][key]
                if len(window) >= 5:
                    mean = statistics.mean(window)
                    stdev = max(statistics.stdev(window) if len(window) > 1 else 0.001, 0.001)
                    z = (value - mean) / stdev
                    if z > Z_THRESHOLD:
                        anomalies.append({
                            "service": info["label"], "container": info["container"],
                            "job": job, "metric": key, "value": value,
                            "mean": round(mean, 3), "stdev": round(stdev, 3), "z_score": round(z, 2),
                        })
                window.append(value)

            # Service down check
            if metrics["service_up"] == 0:
                anomalies.append({
                    "service": info["label"], "container": info["container"],
                    "job": job, "metric": "service_down", "value": 0,
                    "mean": 1, "stdev": 0, "z_score": 999,
                })

            # Traffic collapse
            self.baselines[job]["traffic"].append(metrics["traffic_rps"])
            if len(self.baselines[job]["traffic"]) >= 5 and self.baselines[job]["baseline_traffic"] is None:
                self.baselines[job]["baseline_traffic"] = statistics.mean(self.baselines[job]["traffic"])
            if self.baselines[job]["baseline_traffic"] and self.baselines[job]["baseline_traffic"] > 3:
                if metrics["traffic_rps"] < 1:
                    anomalies.append({
                        "service": info["label"], "container": info["container"],
                        "job": job, "metric": "traffic_collapsed", "value": metrics["traffic_rps"],
                        "mean": round(self.baselines[job]["baseline_traffic"], 1), "stdev": 1, "z_score": 10,
                    })

        return anomalies

def build_prompt(all_metrics, anomalies):
    svc_status = "\n".join(
        f"  {m['label']}: up={m['service_up']} traffic={m['traffic_rps']}/s "
        f"errors={m['error_rate']}% p95={m['latency_p95_ms']}ms goroutines={m['goroutines']}"
        for m in all_metrics.values()
    )
    anomaly_text = "\n".join(
        f"  - [{a['service']}] {a['metric']}: current={a['value']}, baseline={a['mean']}, z={a['z_score']}"
        for a in anomalies
    )
    affected = list(set(a['container'] for a in anomalies))
    return textwrap.dedent(f"""\
    You are an SRE for StreamFlix, a video streaming platform with 4 microservices.

    CURRENT STATUS OF ALL SERVICES:
    {svc_status}

    ANOMALIES DETECTED:
    {anomaly_text}

    AFFECTED CONTAINERS: {', '.join(affected)}

    Based on the full picture across all services:
    1. What is the most likely root cause? (2-3 sentences, mention which service is the origin)
    2. Which containers need remediation? Pick the specific ones:
       - RESTART: <comma-separated container names to restart>
       - Or: SCALE_BACK (kill chaos injectors)
       - Or: NO_ACTION
    3. Could this be a cascading failure? (yes/no and why)
    4. Confidence: HIGH, MEDIUM, or LOW

    Respond in this exact format:
    ROOT_CAUSE: <diagnosis mentioning specific services>
    ACTION: RESTART <container1>,<container2> (or SCALE_BACK or NO_ACTION)
    CASCADE: <yes/no and brief reason>
    CONFIDENCE: <level>
    """)

def call_groq(prompt):
    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
            json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.2, "max_tokens": 500},
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            timeout=30)
        data = resp.json()
        if "error" in data: return f"Groq error: {data['error'].get('message', 'unknown')}"
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e: return f"LLM failed: {e}"

def call_gemini(prompt):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500}}, timeout=30)
        data = resp.json()
        if "error" in data: return f"Gemini error: {data['error'].get('message', 'unknown')}"
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e: return f"LLM failed: {e}"

def llm_root_cause(all_metrics, anomalies):
    if not LLM_PROVIDER:
        return "LLM skipped (no API key). Set GROQ_API_KEY or GEMINI_API_KEY."
    prompt = build_prompt(all_metrics, anomalies)
    return call_groq(prompt) if LLM_PROVIDER == "groq" else call_gemini(prompt)

def parse_action(llm_response):
    """Parse ACTION line — supports RESTART with specific containers."""
    for line in llm_response.split("\n"):
        stripped = line.strip().upper()
        if stripped.startswith("ACTION:"):
            rest = line.strip().split(":", 1)[1].strip()
            if "RESTART" in stripped:
                # Extract container names after RESTART
                parts = rest.replace("RESTART", "").replace("restart", "").strip()
                containers = [c.strip().lower() for c in parts.split(",") if c.strip()]
                # Validate container names
                valid = [s["container"] for s in SERVICES.values()]
                containers = [c for c in containers if c in valid]
                if containers:
                    return ("RESTART", containers)
                # If no valid containers parsed, restart all affected
                return ("RESTART", [])
            elif "SCALE_BACK" in stripped:
                return ("SCALE_BACK", [])
            elif "NO_ACTION" in stripped:
                return ("NO_ACTION", [])
    return ("NO_ACTION", [])

def remediate(action_type, containers, anomalies):
    if action_type == "RESTART":
        # If no specific containers, restart all affected ones from anomalies
        if not containers:
            containers = list(set(a["container"] for a in anomalies))
        for c in containers:
            print(f"  {YELLOW}⚡ Restarting {c}...{RESET}")
            r = subprocess.run(["docker", "restart", c], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                print(f"  {GREEN}✓ {c} restarted{RESET}")
            else:
                subprocess.run(["docker", "start", c], capture_output=True, text=True, timeout=30)
                print(f"  {GREEN}✓ {c} started{RESET}")
        return True
    elif action_type == "SCALE_BACK":
        print(f"  {YELLOW}⚡ Killing chaos injectors...{RESET}")
        for name in ["slow-traffic", "errors"]:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=10)
        print(f"  {GREEN}✓ Injectors stopped{RESET}")
        return True
    else:
        print(f"  {CYAN}ℹ No action taken{RESET}")
        return True

def verify_recovery(wait=30):
    print(f"  {CYAN}⏳ Waiting {wait}s to verify recovery...{RESET}")
    time.sleep(wait)
    all_metrics = gather_all_metrics()
    all_up = all(m["service_up"] == 1 for m in all_metrics.values())
    low_errors = all(m["error_rate"] < 5 for m in all_metrics.values())
    return all_up and low_errors, all_metrics

def generate_postmortem(anomalies, all_metrics, action_type, containers, llm_response, post_metrics, detection_time):
    if not LLM_PROVIDER: return "Postmortem skipped (no LLM key)."
    affected_svcs = ", ".join(set(a["service"] for a in anomalies))
    anomaly_text = "\n".join(f"  [{a['service']}] {a['metric']}={a['value']} (z={a['z_score']})" for a in anomalies)
    pre_status = "\n".join(f"  {m['label']}: up={m['service_up']} errors={m['error_rate']}% traffic={m['traffic_rps']}/s" for m in all_metrics.values())
    post_status = "\n".join(f"  {m['label']}: up={m['service_up']} errors={m['error_rate']}% traffic={m['traffic_rps']}/s" for m in post_metrics.values())
    prompt = textwrap.dedent(f"""\
    Write a blameless incident postmortem for StreamFlix (a microservices streaming platform).

    AFFECTED SERVICES: {affected_svcs}
    DETECTION TIME: {detection_time}
    ANOMALIES: {anomaly_text}
    STATUS BEFORE FIX: {pre_status}
    LLM DIAGNOSIS: {llm_response}
    ACTION TAKEN: {action_type} on {', '.join(containers) if containers else 'affected services'}
    STATUS AFTER FIX: {post_status}

    Format: # Incident Report — StreamFlix
    ## Summary  ## Timeline  ## Root Cause  ## Impact  ## Resolution  ## Lessons Learned  ## Action Items
    """)
    return call_groq(prompt) if LLM_PROVIDER == "groq" else call_gemini(prompt)

def main():
    banner()
    try:
        r = requests.get(f"{PROMETHEUS}/api/v1/status/config", timeout=5)
        if r.status_code == 200: print(f"  {GREEN}✓ Prometheus is reachable{RESET}")
        else: print(f"  {RED}✗ Prometheus returned {r.status_code}{RESET}")
    except Exception as e:
        print(f"  {RED}✗ Cannot reach Prometheus: {e}{RESET}"); sys.exit(1)

    detector = MultiServiceDetector()
    last_action_time = 0

    print(f"\n  {GREEN}▶ Monitoring {len(SERVICES)} services. Polling every {POLL_INTERVAL}s...{RESET}")
    print(f"  {CYAN}  (Baseline building — detection activates after 5 samples){RESET}\n")

    while True:
        try:
            now = datetime.now().strftime("%H:%M:%S")
            all_metrics = gather_all_metrics()

            # Status line per service
            for job, m in all_metrics.items():
                up_icon = f"{GREEN}●{RESET}" if m["service_up"] else f"{RED}●{RESET}"
                err_c = RED if m["error_rate"] > 1 else GREEN
                lat_c = YELLOW if m["latency_p95_ms"] > 500 else GREEN
                label = m["label"].ljust(12)
                print(f"  [{now}] {up_icon} {label} "
                      f"traffic={m['traffic_rps']}/s  "
                      f"errors={err_c}{m['error_rate']}%{RESET}  "
                      f"p95={lat_c}{m['latency_p95_ms']}ms{RESET}  "
                      f"gr={m['goroutines']}")
            print()

            anomalies = detector.check(all_metrics)

            if anomalies and (time.time() - last_action_time) > COOLDOWN:
                affected = set(a["service"] for a in anomalies)
                print(f"  {RED}{BOLD}🚨 ANOMALY DETECTED in: {', '.join(affected)}{RESET}")
                for a in anomalies:
                    print(f"     [{a['service']}] {a['metric']}: {a['value']} "
                          f"(baseline: {a['mean']} ± {a['stdev']}, z={a['z_score']})")
                print()

                provider = "Groq" if LLM_PROVIDER == "groq" else "Gemini"
                print(f"  {CYAN}🤖 Calling {provider} for cross-service root-cause analysis...{RESET}")
                llm_response = llm_root_cause(all_metrics, anomalies)
                print(f"\n  {BOLD}LLM Diagnosis:{RESET}")
                for line in llm_response.split("\n"):
                    if line.strip(): print(f"     {line.strip()}")
                print()

                action_type, containers = parse_action(llm_response)
                target_str = ", ".join(containers) if containers else "affected services"
                print(f"  {BOLD}Executing: {action_type} → {target_str}{RESET}")
                remediate(action_type, containers, anomalies)

                if action_type != "NO_ACTION":
                    recovered, post_metrics = verify_recovery()
                    if recovered:
                        print(f"\n  {GREEN}{BOLD}✅ RECOVERY CONFIRMED — all services healthy{RESET}")
                        for m in post_metrics.values():
                            print(f"     {m['label']}: up={m['service_up']} errors={m['error_rate']}% traffic={m['traffic_rps']}/s")
                        print(f"\n  {CYAN}📝 Generating incident postmortem...{RESET}")
                        pm = generate_postmortem(anomalies, all_metrics, action_type, containers, llm_response, post_metrics, now)
                        pm_file = f"incident_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                        with open(pm_file, "w") as f: f.write(pm)
                        print(f"  {GREEN}✓ Postmortem saved to {pm_file}{RESET}")
                        for line in pm.split("\n")[:12]:
                            print(f"  {line}")
                    else:
                        print(f"\n  {RED}{BOLD}⚠ NOT FULLY RECOVERED{RESET}")
                        for m in post_metrics.values():
                            if m["service_up"] == 0 or m["error_rate"] > 5:
                                print(f"     {RED}{m['label']}: up={m['service_up']} errors={m['error_rate']}%{RESET}")
                        print(f"     {YELLOW}Escalating to human{RESET}")

                last_action_time = time.time()
                print()

            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print(f"\n\n  {CYAN}Agent stopped.{RESET}"); break
        except Exception as e:
            print(f"  {RED}Error: {e}{RESET}"); time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
