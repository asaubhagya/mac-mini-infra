import os
import platform
import plistlib
import re
import socket
import subprocess
import time
import urllib.request
import json
from pathlib import Path

import psutil


def _uptime_str():
    secs = int(time.time() - psutil.boot_time())
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def get_current():
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = os.getloadavg()
    return {
        "cpu_percent": round(cpu, 1),
        "memory": {
            "used_gb": round(mem.used / 1e9, 2),
            "total_gb": round(mem.total / 1e9, 2),
            "percent": mem.percent,
        },
        "disk": {
            "used_gb": round(disk.used / 1e9, 1),
            "total_gb": round(disk.total / 1e9, 1),
            "percent": disk.percent,
        },
        "load_avg": {"1m": round(load[0], 2), "5m": round(load[1], 2), "15m": round(load[2], 2)},
        "uptime": _uptime_str(),
        "hostname": socket.gethostname(),
        "os_version": platform.mac_ver()[0] or platform.version(),
        "local_ip": _local_ip(),
    }


def get_gpu_stats():
    """Read Apple Silicon GPU utilization from IOKit (no sudo required)."""
    try:
        out = subprocess.check_output(
            ["/usr/sbin/ioreg", "-r", "-c", "AGXAccelerator"],
            text=True, stderr=subprocess.DEVNULL, timeout=4,
        )
        stats_line = next((l for l in out.splitlines() if "PerformanceStatistics" in l), "")

        def extract_int(key):
            m = re.search(rf'"{re.escape(key)}"\s*=\s*(\d+)', stats_line)
            return int(m.group(1)) if m else None

        gpu_pct = extract_int("Device Utilization %")
        renderer_pct = extract_int("Renderer Utilization %")
        tiler_pct = extract_int("Tiler Utilization %")
        gpu_mem_bytes = extract_int("In use system memory")

        # Core count from separate line
        m = re.search(r'"gpu-core-count"\s*=\s*(\d+)', out)
        core_count = int(m.group(1)) if m else None

        return {
            "gpu_percent": gpu_pct,
            "renderer_percent": renderer_pct,
            "tiler_percent": tiler_pct,
            "gpu_mem_gb": round(gpu_mem_bytes / 1e9, 2) if gpu_mem_bytes is not None else None,
            "gpu_cores": core_count,
            "available": gpu_pct is not None,
        }
    except Exception:
        return {"available": False, "gpu_percent": None, "gpu_mem_gb": None, "gpu_cores": None}


def get_memory_pressure():
    """Parse vm_stat for unified memory breakdown (Apple Silicon specific)."""
    try:
        out = subprocess.check_output(["/usr/bin/vm_stat"], text=True, timeout=3)
        page_size = 16384
        m = re.search(r"page size of (\d+)", out)
        if m:
            page_size = int(m.group(1))

        def pages(key):
            m2 = re.search(rf"{re.escape(key)}:\s+(\d+)", out)
            return int(m2.group(1)) if m2 else 0

        free_gb = pages("Pages free") * page_size / 1e9
        wired_gb = pages("Pages wired down") * page_size / 1e9
        compressed_gb = pages("Pages occupied by compressor") * page_size / 1e9
        active_gb = pages("Pages active") * page_size / 1e9
        inactive_gb = pages("Pages inactive") * page_size / 1e9
        total_gb = psutil.virtual_memory().total / 1e9

        used_ratio = 1.0 - (free_gb / total_gb) if total_gb else 0
        if used_ratio < 0.75:
            pressure = "normal"
        elif used_ratio < 0.90:
            pressure = "moderate"
        else:
            pressure = "critical"

        return {
            "free_gb": round(free_gb, 2),
            "wired_gb": round(wired_gb, 2),
            "compressed_gb": round(compressed_gb, 2),
            "active_gb": round(active_gb, 2),
            "inactive_gb": round(inactive_gb, 2),
            "pressure": pressure,
        }
    except Exception:
        return {"pressure": "unknown", "free_gb": 0, "wired_gb": 0, "compressed_gb": 0}


def get_ollama_status():
    """Query Ollama API for running models."""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=2) as r:
            data = json.load(r)
        models = data.get("models", [])
        active = [
            {
                "name": m.get("name", ""),
                "size_gb": round(m.get("size", 0) / 1e9, 1),
                "vram_gb": round(m.get("size_vram", 0) / 1e9, 1),
            }
            for m in models
        ]
        return {"running": True, "active_models": active}
    except Exception:
        # Fall back to process check
        for p in psutil.process_iter(["name"]):
            try:
                if "ollama" in (p.info["name"] or "").lower():
                    return {"running": True, "active_models": []}
            except Exception:
                pass
        return {"running": False, "active_models": []}


def get_processes():
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
        try:
            info = p.info
            mem_mb = round(info["memory_info"].rss / 1e6, 1) if info["memory_info"] else 0
            procs.append({
                "pid": info["pid"],
                "name": info["name"] or "",
                "cpu_percent": info["cpu_percent"] or 0,
                "mem_mb": mem_mb,
                "status": info["status"] or "",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
    return procs[:20]


def _parse_launch_interval(plist_data):
    interval = plist_data.get("StartInterval")
    if interval:
        if interval < 60:   return f"Every {interval}s"
        if interval < 3600: return f"Every {interval // 60}m"
        return f"Every {interval // 3600}h"
    cal = plist_data.get("StartCalendarInterval")
    if cal:
        if isinstance(cal, list): cal = cal[0]
        days = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
        parts = []
        if "Weekday" in cal: parts.append(days[cal["Weekday"]])
        if "Hour" in cal and "Minute" in cal: parts.append(f"{cal['Hour']:02d}:{cal['Minute']:02d}")
        elif "Hour" in cal: parts.append(f"{cal['Hour']:02d}:00")
        return " ".join(parts) or "Scheduled"
    if plist_data.get("RunAtLoad"): return "At login"
    return "On demand"


def _scan_launch_agents(directory):
    results = []
    d = Path(directory)
    if not d.exists(): return results
    for f in d.glob("*.plist"):
        try:
            with open(f, "rb") as fh:
                data = plistlib.load(fh)
            results.append({
                "label": data.get("Label", f.stem),
                "schedule": _parse_launch_interval(data),
                "file": f.name,
            })
        except Exception:
            pass
    return results


def _get_app_jobs():
    """Query growthforge API for APScheduler job status (processing, discovery, etc.)."""
    try:
        with urllib.request.urlopen("http://localhost:8000/api/schedule", timeout=3) as r:
            data = json.load(r)
        return data.get("jobs", [])
    except Exception:
        pass

    # Fallback: return static known schedule
    return [
        {"name": "download", "interval_hours": 2, "last_run_at": None, "last_run_status": None, "next_run_at": None},
        {"name": "transcription", "interval_hours": 2, "last_run_at": None, "last_run_status": None, "next_run_at": None},
        {"name": "highlights", "interval_hours": 0.083, "last_run_at": None, "last_run_status": None, "next_run_at": None},
        {"name": "auto_heal", "interval_hours": 6, "last_run_at": None, "last_run_status": None, "next_run_at": None},
        {"name": "discovery", "interval_hours": 4, "last_run_at": None, "last_run_status": None, "next_run_at": None},
        {"name": "daily_pipeline", "interval_hours": 24, "last_run_at": None, "last_run_status": None, "next_run_at": None},
    ]


def get_scheduled():
    cron_jobs = []
    try:
        out = subprocess.check_output(["/usr/bin/crontab", "-l"], stderr=subprocess.DEVNULL, text=True)
        for line in out.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                cron_jobs.append(s)
    except subprocess.CalledProcessError:
        pass
    agents = (
        _scan_launch_agents(Path.home() / "Library" / "LaunchAgents")
        + _scan_launch_agents("/Library/LaunchAgents")
    )
    app_jobs = _get_app_jobs()
    return {"cron": cron_jobs, "launch_agents": agents, "app_jobs": app_jobs}
