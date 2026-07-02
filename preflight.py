#!/usr/bin/env python3
"""
StreamFlix Lab — Pre-Event Setup Checker
=========================================
Run this BEFORE the workshop to verify everything works.

Usage:
    python3 preflight.py

Checks: Docker, RAM, disk, port availability, image pulls, Python + requests,
        LLM API key (Groq or Gemini).
"""

import os, sys, shutil, subprocess, platform

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

checks_passed = 0
checks_failed = 0
warnings = 0

def ok(msg):
    global checks_passed
    checks_passed += 1
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg, hint=""):
    global checks_failed
    checks_failed += 1
    print(f"  {RED}✗{RESET} {msg}")
    if hint:
        print(f"    {YELLOW}→ {hint}{RESET}")

def warn(msg):
    global warnings
    warnings += 1
    print(f"  {YELLOW}!{RESET} {msg}")

print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════╗
║     StreamFlix Lab — Pre-Event Setup Checker     ║
╚══════════════════════════════════════════════════╝{RESET}
""")

# ── 1. Docker installed? ────────────────────────────────────────────
print(f"{BOLD}1. Docker{RESET}")
docker_path = shutil.which("docker")
if docker_path:
    ok(f"Docker found at {docker_path}")
else:
    fail("Docker not found in PATH",
         "Install Docker Desktop from https://www.docker.com/products/docker-desktop/")
    print(f"\n  {RED}Cannot continue without Docker. Install it and re-run this script.{RESET}")
    sys.exit(1)

# Docker running?
try:
    result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        ok("Docker daemon is running")
    else:
        fail("Docker is installed but not running",
             "Start Docker Desktop and wait for it to say 'Engine running'")
except Exception as e:
    fail(f"Docker check failed: {e}",
         "Make sure Docker Desktop is started")

# Docker version
try:
    result = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=5)
    version = result.stdout.strip()
    ok(f"Version: {version}")
except Exception:
    warn("Could not determine Docker version")

# ── 2. System resources ─────────────────────────────────────────────
print(f"\n{BOLD}2. System resources{RESET}")

# RAM
try:
    import psutil
    ram_gb = psutil.virtual_memory().total / (1024**3)
    if ram_gb >= 8:
        ok(f"RAM: {ram_gb:.1f} GB (need 8 GB)")
    elif ram_gb >= 6:
        warn(f"RAM: {ram_gb:.1f} GB (8 GB recommended, may be tight)")
    else:
        fail(f"RAM: {ram_gb:.1f} GB", "Need at least 8 GB for 5 containers")
except ImportError:
    if platform.system() == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        gb = kb / (1024**2)
                        if gb >= 8:
                            ok(f"RAM: {gb:.1f} GB")
                        else:
                            warn(f"RAM: {gb:.1f} GB (8 GB recommended)")
                        break
        except Exception:
            warn("Could not check RAM (install psutil: pip install psutil)")
    else:
        warn("Could not check RAM (install psutil: pip install psutil)")

# Disk
try:
    total, used, free = shutil.disk_usage("/")
    free_gb = free / (1024**3)
    if free_gb >= 5:
        ok(f"Disk: {free_gb:.1f} GB free (need 5 GB)")
    else:
        fail(f"Disk: {free_gb:.1f} GB free", "Need at least 5 GB for Docker images")
except Exception:
    warn("Could not check disk space")

# ── 3. Port availability ────────────────────────────────────────────
print(f"\n{BOLD}3. Port availability{RESET}")
import socket
for port, service in [(9898, "StreamFlix backend"), (9090, "Prometheus"), (3000, "Grafana"), (8080, "StreamFlix UI")]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex(("localhost", port))
    sock.close()
    if result != 0:
        ok(f"Port {port} ({service}) is free")
    else:
        warn(f"Port {port} ({service}) is in use — stop whatever is using it before the lab")

# ── 4. Pull Docker images ───────────────────────────────────────────
print(f"\n{BOLD}4. Docker images (pulling — this may take a minute){RESET}")
images = [
    ("stefanprodan/podinfo", "StreamFlix backend"),
    ("prom/prometheus", "Prometheus"),
    ("grafana/grafana", "Grafana"),
    ("busybox", "Traffic generator"),
    ("nginx:alpine", "StreamFlix UI server"),
]
for image, label in images:
    try:
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            ok(f"{image} ({label})")
        else:
            fail(f"Failed to pull {image}", result.stderr.strip()[:100])
    except subprocess.TimeoutExpired:
        fail(f"Timeout pulling {image}", "Check your internet connection")
    except Exception as e:
        fail(f"Error pulling {image}: {e}")

# ── 5. Python + requests ────────────────────────────────────────────
print(f"\n{BOLD}5. Python (for AIOps agent){RESET}")
ok(f"Python {sys.version.split()[0]}")
try:
    import requests as req
    ok(f"requests library installed (v{req.__version__})")
except ImportError:
    warn("'requests' not installed — run: pip install requests")
    print(f"    {CYAN}(Only needed for Part 5: the AIOps agent){RESET}")

# ── 6. LLM API key (Groq or Gemini) ────────────────────────────────
print(f"\n{BOLD}6. LLM API key (for Part 5 — AIOps agent){RESET}")

groq_key = os.getenv("GROQ_API_KEY", "")
gemini_key = os.getenv("GEMINI_API_KEY", "")

if groq_key:
    ok(f"GROQ_API_KEY is set ({groq_key[:8]}...)")
    try:
        r = req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 5,
            },
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if r.status_code == 200:
            ok("Groq API key is valid — Llama 70B is ready")
        else:
            data = r.json()
            err = data.get("error", {}).get("message", f"status {r.status_code}")
            fail(f"Groq API key rejected: {err}",
                 "Get a free key at https://console.groq.com")
    except Exception as e:
        warn(f"Could not validate Groq key: {e}")

elif gemini_key:
    ok(f"GEMINI_API_KEY is set ({gemini_key[:8]}...)")
    try:
        r = req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}",
            json={"contents": [{"parts": [{"text": "Say OK"}]}]},
            timeout=10,
        )
        if r.status_code == 200:
            ok("Gemini API key is valid")
        else:
            data = r.json()
            err = data.get("error", {}).get("message", f"status {r.status_code}")
            fail(f"Gemini API key rejected: {err}",
                 "Try Groq instead (free, no card): https://console.groq.com")
    except Exception as e:
        warn(f"Could not validate Gemini key: {e}")

else:
    warn("No LLM API key set (GROQ_API_KEY or GEMINI_API_KEY)")
    print(f"    {CYAN}Option A (recommended): Get a free Groq key at https://console.groq.com{RESET}")
    print(f"    {CYAN}  Then run: export GROQ_API_KEY='your-key-here'{RESET}")
    print(f"    {CYAN}Option B: Get a Gemini key at https://aistudio.google.com/apikey{RESET}")
    print(f"    {CYAN}  Then run: export GEMINI_API_KEY='your-key-here'{RESET}")
    print(f"    {CYAN}(Only needed for Part 5: the AIOps agent){RESET}")

# ── Summary ─────────────────────────────────────────────────────────
print(f"\n{'='*52}")
if checks_failed == 0:
    print(f"  {GREEN}{BOLD}ALL CHECKS PASSED!{RESET}  ✓ {checks_passed} passed", end="")
    if warnings:
        print(f"  {YELLOW}! {warnings} warnings{RESET}")
    else:
        print()
    print(f"\n  {GREEN}You're ready for the StreamFlix lab! 🎬{RESET}")
else:
    print(f"  {RED}{BOLD}{checks_failed} CHECKS FAILED{RESET}  "
          f"✓ {checks_passed} passed  {YELLOW}! {warnings} warnings{RESET}")
    print(f"\n  {YELLOW}Fix the failed items above and run this script again.{RESET}")

print()
