import threading
import time

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db import get_history, init_db, insert_sample
from metrics import (
    get_current, get_gpu_stats, get_memory_pressure,
    get_ollama_status, get_processes, get_scheduled,
)

app = FastAPI(title="Mac Mini Monitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _sampler():
    while True:
        try:
            d = get_current()
            gpu = get_gpu_stats()
            insert_sample(
                cpu=d["cpu_percent"],
                mem_pct=d["memory"]["percent"],
                mem_used=d["memory"]["used_gb"],
                mem_total=d["memory"]["total_gb"],
                disk_pct=d["disk"]["percent"],
                disk_used=d["disk"]["used_gb"],
                disk_total=d["disk"]["total_gb"],
                gpu=gpu.get("gpu_percent"),
            )
        except Exception as e:
            print(f"Sampler error: {e}")
        time.sleep(30)


@app.on_event("startup")
def startup():
    init_db()
    threading.Thread(target=_sampler, daemon=True).start()


@app.get("/api/current")
def api_current():
    return get_current()


@app.get("/api/history")
def api_history(window: int = Query(default=3600, ge=60, le=86400)):
    return get_history(window_seconds=window)


@app.get("/api/extended")
def api_extended():
    return {
        "gpu": get_gpu_stats(),
        "memory_pressure": get_memory_pressure(),
        "ollama": get_ollama_status(),
    }


@app.get("/api/processes")
def api_processes():
    return get_processes()


@app.get("/api/scheduled")
def api_scheduled():
    return get_scheduled()


app.mount("/", StaticFiles(directory="static", html=True), name="static")
