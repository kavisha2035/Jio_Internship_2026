"""
app.py  (v4 — Simplified Chair Counting Engine)
FastAPI application — serves REST APIs, WebSocket live stream, and the dashboard.

Endpoints:
  GET  /                        → Redirect to dashboard
  GET  /api/health              → System health check
  GET  /api/status              → Current chair occupancy counts
  WS   /ws/live                 → WebSocket: streams annotated frames + chair counts
"""

import sys
import asyncio
import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.append(str(Path(__file__).parent))

from core.multi_cam_manager import camera_manager
from core import database as db

# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[App] Starting chair detection pipelines...")
    camera_manager.start()
    print("[App] Pipelines running.")
    yield
    camera_manager.stop()
    print("[App] Shutdown complete.")


# ─── App Init ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="OccuSense AI — Chair Occupancy Counter",
    description="Real-time chair occupancy detection from video feeds",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── WebSocket Manager ────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        print(f"[WS] Client connected. Total: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        print(f"[WS] Client disconnected. Total: {len(self.active)}")


manager = ConnectionManager()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/health")
async def health(camera_id: str = "cam_floor2"):
    """System health check."""
    proc = camera_manager.get_processor(camera_id)
    if not proc:
        return JSONResponse(status_code=404, content={"error": f"Camera {camera_id} not found"})
    return {
        "status":       "ok",
        "camera":       proc.is_running,
        "model":        "yolov8n" if proc.detector and not proc.detector.is_mock else "mock",
        "frame_count":  proc.frame_count,
    }


@app.get("/api/status")
async def get_current_status():
    """Return current chair occupancy counts."""
    processors = camera_manager.get_all_processors()
    total_chairs = 0
    occupied_chairs = 0
    total_persons = 0

    for proc in processors.values():
        with proc._lock:
            total_chairs    += proc.total_chairs
            occupied_chairs += proc.occupied_chairs
            total_persons   += proc.total_persons

    return {
        "total_chairs":    total_chairs,
        "occupied_chairs": occupied_chairs,
        "vacant_chairs":   total_chairs - occupied_chairs,
        "total_persons":   total_persons,
    }


@app.get("/api/chairs/summary")
def chair_summary(camera_id: str = "cam_floor2"):
    """Current chair counts"""
    proc = camera_manager.get_processor(camera_id)
    if not proc:
        return {"total": 0, "occupied": 0, "vacant": 0}
    with proc._lock:
        return proc.latest_chair_counts


@app.get("/api/chairs/history")
def chair_history(days: int = 7):
    """Historical occupancy for analytics charts"""
    return db.get_chair_history(days)


@app.get("/api/chairs/dwell")
def dwell_stats():
    """Average dwell times per chair"""
    return db.get_dwell_stats()


@app.get("/api/startups/utilization")
def startup_utilization():
    """Contract vs reality report"""
    return db.get_startup_utilization()


class AddStartupRequest(BaseModel):
    name: str
    contracted: int


@app.post("/api/startups")
def api_add_startup(req: AddStartupRequest):
    if not req.name.strip():
        return JSONResponse(status_code=400, content={"error": "Startup name cannot be empty"})
    if req.contracted <= 0:
        return JSONResponse(status_code=400, content={"error": "Contracted chairs must be greater than 0"})
    try:
        result = db.add_startup(req.name, req.contracted)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/heatmap/toggle")
def toggle_heatmap(camera_id: str = "cam_floor2"):
    """Toggle the heatmap overlay state on/off"""
    proc = camera_manager.get_processor(camera_id)
    if proc:
        proc.show_heatmap_overlay = not proc.show_heatmap_overlay
        return {"show_heatmap": proc.show_heatmap_overlay}
    return {"error": "Camera not found"}


# ─── WebSocket Endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket, camera_id: str = "cam_floor2"):
    """WebSocket: streams annotated frames + chair counts."""
    await manager.connect(websocket)
    loop = asyncio.get_running_loop()
    frame_queue: asyncio.Queue = asyncio.Queue(maxsize=2)

    def on_frame(payload: str):
        def safe_put():
            try:
                frame_queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
        loop.call_soon_threadsafe(safe_put)

    proc = camera_manager.get_processor(camera_id)
    if not proc:
        processors = list(camera_manager.get_all_processors().values())
        if processors:
            proc = processors[0]

    if proc:
        proc.subscribe(on_frame)

    try:
        while True:
            try:
                payload = await asyncio.wait_for(frame_queue.get(), timeout=5.0)
                await websocket.send_text(payload)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if proc:
            proc.unsubscribe(on_frame)
        manager.disconnect(websocket)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("=" * 65)
    print("  OccuSense AI — Chair Occupancy Counter")
    print("  Dashboard:  http://localhost:8000")
    print("  API Docs:   http://localhost:8000/docs")
    print("=" * 65)
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
