#!/usr/bin/env python3
"""
StreamFlix Observability Chat
==============================
Ask questions about your streaming service in plain English.
The AI translates to PromQL, queries Prometheus, and explains the results.

Usage:
    export GROQ_API_KEY="your-key"
    python3 obs-chat.py

Examples:
    > When were errors high?
    > What's the current p95 latency?
    > Was there any downtime in the last hour?
    > Compare error rate vs latency over the last 30 minutes
    > How much error budget have we burned?

Requires: requests  (pip install requests)
"""

import os, sys, json, textwrap, subprocess

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run:  pip install requests")
    sys.exit(1)

PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def call_groq(messages):
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1000,
            },
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        data = resp.json()
        if "error" in data:
            return f"Error: {data['error'].get('message', 'unknown')}"
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"LLM call failed: {e}"

def prom_query(expr):
    """Run an instant PromQL query."""
    try:
        r = requests.get(f"{PROMETHEUS}/api/v1/query",
                         params={"query": expr}, timeout=5)
        return r.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}

def prom_query_range(expr, start, end, step="60s"):
    """Run a range PromQL query."""
    try:
        r = requests.get(f"{PROMETHEUS}/api/v1/query_range",
                         params={"query": expr, "start": start, "end": end, "step": step},
                         timeout=10)
        return r.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}

SYSTEM_PROMPT = textwrap.dedent("""\
You are an SRE observability assistant for StreamFlix, a video streaming service.
You help users understand their service metrics by querying Prometheus.
You can also inspect container logs when asked about logs, errors, or recent events.

AVAILABLE METRICS (these are the only ones that exist):
- http_requests_total{status="200"} — successful request counter
- http_requests_total{status="500"} — failed request counter
- http_request_duration_seconds_bucket{le="..."} — latency histogram
- http_request_duration_seconds_count — total request count for latency
- http_request_duration_seconds_sum — total latency sum
- up{job="checkout"} — is the service up (1) or down (0)
- go_goroutines{job="checkout"} — number of goroutines (saturation)
- process_resident_memory_bytes{job="checkout"} — memory usage
- process_cpu_seconds_total{job="checkout"} — CPU usage counter

COMMON PATTERNS:
- Error rate: 100 * sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
- Traffic: sum(rate(http_requests_total[5m]))
- Latency p95: 1000 * histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
- Service up: up{job="checkout"}
- Error budget: 100 * (1 - ((1 - sum(rate(http_requests_total{status!~"5.."}[30m])) / sum(rate(http_requests_total[30m]))) / (1 - 0.99)))

When the user asks a question:

IF the question is about LOGS, ERRORS IN LOGS, RECENT EVENTS, RESTARTS, or CRASHES:
Respond with:
```json
{"action": "logs", "container": "streamflix", "tail": 50}
```

IF the question needs PROMETHEUS METRICS:
Respond with:
```json
{"queries": [
    {"label": "Error rate now", "expr": "100 * sum(rate(http_requests_total{status=~\\"5..\\"}[5m])) / sum(rate(http_requests_total[5m]))"},
    {"label": "Traffic", "expr": "sum(rate(http_requests_total[5m]))"}
]}
```

IF the question is general knowledge (like "what is an SLO?"):
Respond with:
```json
{"answer": "your explanation here"}
```

IMPORTANT: Respond ONLY with the JSON block, nothing else.
""")

INTERPRET_PROMPT = textwrap.dedent("""\
You are an SRE observability assistant for StreamFlix, a video streaming service.
The user asked a question and you queried Prometheus. Here are the results.

USER QUESTION: {question}

QUERY RESULTS:
{results}

Now answer the user's question in plain English based on these results.
Be specific — mention actual numbers, times, and durations.
If the data shows a problem, explain what it likely means for viewers.
Keep it conversational but informative — like a senior SRE explaining to a colleague.
Use 3-5 sentences, no bullet points, no markdown headers.
""")

def fetch_logs(container="streamflix", tail=50):
    """Fetch Docker container logs."""
    try:
        result = subprocess.run(
            ["docker", "logs", container, "--tail", str(tail), "--timestamps"],
            capture_output=True, text=True, timeout=10
        )
        logs = result.stdout + result.stderr  # some apps log to stderr
        if not logs.strip():
            return "(no logs found)"
        return logs
    except Exception as e:
        return f"(failed to fetch logs: {e})"

def analyze_logs(question, logs):
    """Send logs to Groq for analysis."""
    prompt = textwrap.dedent(f"""\
    You are an SRE analyzing container logs for StreamFlix, a video streaming service.

    USER QUESTION: {question}

    RECENT CONTAINER LOGS:
    {logs}

    Analyze these logs and answer the user's question. Look for:
    - Error messages and their causes
    - Restart events (container starting up again)
    - Panic/crash traces
    - Status code patterns (200s vs 500s)
    - Response time issues
    - Anything unusual

    Be specific — mention exact timestamps, error messages, and patterns.
    Keep it conversational, like a senior SRE explaining to a colleague.
    Use 3-6 sentences.
    """)
    return call_groq([
        {"role": "system", "content": "You are a helpful SRE log analyst."},
        {"role": "user", "content": prompt}
    ])

def run_queries(queries):
    """Execute PromQL queries and format results."""
    results = []
    for q in queries:
        label = q.get("label", "Query")
        expr = q.get("expr", "")
        print(f"  {DIM}  → Running: {expr}{RESET}")
        data = prom_query(expr)
        if data.get("status") == "success" and data["data"]["result"]:
            for r in data["data"]["result"]:
                val = r["value"][1]
                metric = r.get("metric", {})
                metric_str = json.dumps(metric) if metric else ""
                results.append(f"{label}: {val} {metric_str}")
        elif data.get("status") == "success":
            results.append(f"{label}: no data (metric may not exist yet)")
        else:
            results.append(f"{label}: error — {data.get('error', 'unknown')}")
    return "\n".join(results)

def ask(question, conversation):
    """Process a user question through the LLM → Prometheus → LLM pipeline."""

    # Step 1: Ask LLM to generate PromQL queries
    conversation.append({"role": "user", "content": question})
    print(f"\n  {CYAN}🔍 Figuring out what to query...{RESET}")
    response = call_groq(conversation)

    # Try to extract JSON from the response
    try:
        # Find JSON in the response
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(response[json_start:json_end])
        else:
            parsed = json.loads(response)

        # Direct answer (no query needed)
        if "answer" in parsed:
            print(f"\n  {GREEN}{parsed['answer']}{RESET}")
            conversation.append({"role": "assistant", "content": response})
            return conversation

        # Log inspection requested
        if "action" in parsed and parsed["action"] == "logs":
            container = parsed.get("container", "streamflix")
            tail = parsed.get("tail", 50)
            print(f"  {CYAN}📋 Fetching last {tail} log lines from {container}...{RESET}")
            logs = fetch_logs(container, tail)
            print(f"  {DIM}  → Got {len(logs.splitlines())} lines{RESET}")
            print(f"  {CYAN}💬 Analyzing logs...{RESET}")
            analysis = analyze_logs(question, logs)
            print(f"\n  {GREEN}{analysis}{RESET}")
            conversation.append({"role": "assistant", "content": response})
            return conversation

        # Has queries — run them
        queries = parsed.get("queries", [])
        if not queries:
            print(f"\n  {YELLOW}No queries generated. Try rephrasing.{RESET}")
            return conversation

        print(f"  {CYAN}📊 Running {len(queries)} queries against Prometheus...{RESET}")
        results = run_queries(queries)

        # Step 2: Send results back to LLM for interpretation
        print(f"  {CYAN}💬 Interpreting results...{RESET}")
        interpret_msg = INTERPRET_PROMPT.format(question=question, results=results)
        interpretation = call_groq([
            {"role": "system", "content": "You are a helpful SRE assistant. Answer concisely."},
            {"role": "user", "content": interpret_msg}
        ])

        print(f"\n  {GREEN}{interpretation}{RESET}")
        conversation.append({"role": "assistant", "content": response})
        return conversation

    except (json.JSONDecodeError, KeyError, TypeError):
        # LLM didn't return valid JSON — treat the whole response as a direct answer
        print(f"\n  {GREEN}{response}{RESET}")
        conversation.append({"role": "assistant", "content": response})
        return conversation

def main():
    if not GROQ_KEY:
        print(f"{RED}Set GROQ_API_KEY first: export GROQ_API_KEY='your-key'{RESET}")
        sys.exit(1)

    # Verify Prometheus
    try:
        r = requests.get(f"{PROMETHEUS}/api/v1/status/config", timeout=5)
        prom_ok = r.status_code == 200
    except:
        prom_ok = False

    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════╗
║       StreamFlix Observability Chat  v1.0        ║
║    Ask questions about your service in English    ║
╚══════════════════════════════════════════════════╝{RESET}

  Prometheus: {GREEN + '✓ connected' if prom_ok else RED + '✗ not reachable'}{RESET}
  LLM: Groq (Llama 70B)

  {BOLD}Try asking:{RESET}
    • What's the current error rate?
    • When was the last time the service went down?
    • How much error budget is remaining?
    • Is the service healthy?
    • Show me any errors in the logs
    • Did the service crash recently?
    • What do the logs say about the last restart?
    • Are there any panic messages in the logs?

  Type {BOLD}quit{RESET} to exit.
""")

    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            question = input(f"  {BOLD}You → {RESET}").strip()
            if not question:
                continue
            if question.lower() in ("quit", "exit", "q"):
                print(f"\n  {CYAN}Goodbye!{RESET}\n")
                break
            conversation = ask(question, conversation)
            print()
        except KeyboardInterrupt:
            print(f"\n\n  {CYAN}Goodbye!{RESET}\n")
            break
        except Exception as e:
            print(f"  {RED}Error: {e}{RESET}")

if __name__ == "__main__":
    main()
