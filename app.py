"""
app.py  (v3 — Workspace Space Allocation Engine)
FastAPI application — serves REST APIs, WebSocket live stream, and the dashboard.

Endpoints:
  GET  /                        → Redirect to dashboard
  GET  /api/health              → System health check
  GET  /api/workspaces          → All workspace definitions + startup assignments
  GET  /api/status              → Current real-time workspace occupancy states
  GET  /api/analytics           → Full analytics report (peak hours, per-workspace table)
  GET  /api/analyze/{startup_id}→ Assignment engine analysis for one startup
  GET  /api/recommendations     → Space optimization report (all startups)
  POST /api/reassign            → Confirm a workspace reassignment
  GET  /api/assignment-letter   → Generate formal assignment letter text
  WS   /ws/live                 → WebSocket: streams annotated frames + workspace states

WebSocket message format (server → client):
  {
    "type":       "frame",
    "data":       "data:image/jpeg;base64,...",
    "workspaces": { "ws_001": "occupied", "ws_002": "vacant", ... },
    "timestamp":  "2026-06-11T14:32:43",
    "stats":      { "occupied": 10, "vacant": 5, "total": 15 }
  }
"""

import sys
import asyncio
import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

sys.path.append(str(Path(__file__).parent))

from core.video_processor import processor
from core import database as db
from core.assignment_engine import WorkspaceAssignmentEngine
from ml.analytics import full_analytics_report

# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[App] Starting workspace allocation pipeline...")
    processor.start()
    print("[App] Pipeline running.")
    yield
    processor.stop()
    print("[App] Shutdown complete.")


# ─── App Init ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="OccuSense AI — Workspace Allocation Engine",
    description="Real-time co-working space allocation monitoring and optimization",
    version="3.0.0",
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

engine = WorkspaceAssignmentEngine()


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

    async def broadcast(self, payload: str):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


manager = ConnectionManager()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/health")
async def health():
    """System health check."""
    ws_count = len(processor.workspace_map)
    return {
        "status":          "ok",
        "camera":          processor.is_running,
        "workspaces":      ws_count,
        "model":           "yolov8n" if processor.detector and not processor.detector.is_mock else "mock",
        "posture_model":   "mediapipe" if (processor.detector and processor.detector.posture.available) else "unavailable",
        "mode":            "mock" if (processor.detector and processor.detector.is_mock) else "live",
        "frame_count":     processor.frame_count,
    }


@app.get("/api/workspaces")
async def get_workspaces():
    """Return all workspace definitions with startup assignments."""
    workspaces = db.get_all_workspaces()
    startups   = db.get_all_startups()
    return {
        "workspaces":       workspaces,
        "startups":         startups,
        "total_workspaces": len(workspaces),
    }


@app.get("/api/status")
async def get_current_status():
    """Return current real-time workspace occupancy states (occupied / vacant only)."""
    with processor._lock:
        states = processor.latest_states.copy()

    occupied = sum(1 for s in states.values() if s == "occupied")
    total    = len(states)

    return {
        "workspaces":     states,
        "occupied":       occupied,
        "vacant":         total - occupied,
        "total":          total,
        "occupancy_rate": round(occupied / total, 3) if total > 0 else 0,
    }


@app.get("/api/analytics")
async def get_analytics(days: int = 7):
    """
    Return full analytics report including per-workspace utilization table.
    Response schema:
    {
      "peak_hours":           [...],
      "day_of_week":          [...],
      "workspace_utilization": [
        {
          "ws_id":          "ws_001",
          "label":          "Desk Space A1",
          "startup":        "startup_a",
          "startup_name":   "Startup Alpha",
          "avg_daily_hours": 6.8,
          "utilization_rate": 0.85,
          "utilization_pct":  "85.0%",
          "status":         "active"   // active / underused / reassignable
        }, ...
      ],
      "startup_efficiency":   [...],
    }
    """
    try:
        # Per-workspace utilization table
        ws_utils = db.get_all_workspace_utilizations(days=days)
        ws_table = []
        for ws in ws_utils:
            util = ws.get("utilization_rate", 0)
            if util >= 0.50:
                status = "active"
            elif util >= 0.25:
                status = "underused"
            else:
                status = "reassignable"

            ws_table.append({
                "ws_id":           ws["ws_id"],
                "label":           ws["label"],
                "startup":         ws["allocated_to"],
                "startup_name":    ws.get("startup_name", ws["allocated_to"]),
                "avg_daily_hours": ws.get("avg_daily_hours", 0),
                "utilization_rate": util,
                "utilization_pct": f"{util * 100:.1f}%",
                "consecutive_vacant_days": ws.get("consecutive_vacant_days", 0),
                "status":          status,
            })

        report = full_analytics_report(days=days)
        report["workspace_utilization"] = ws_table
        return report

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/analyze/{startup_id}")
async def analyze_startup(startup_id: str, days: int = 7):
    """
    Run the assignment engine analysis for a specific startup.
    Returns workspace-by-workspace utilization classification.
    """
    try:
        result = engine.analyze_startup(startup_id, days=days)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/recommendations")
async def get_recommendations(days: int = 7):
    """
    Full space optimization report — which spaces are safe to reassign
    across all startups, with confidence scoring.
    """
    try:
        report = engine.full_space_optimization_report(days=days)
        return report
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/recommend-for/{startup_id}")
async def recommend_for_startup(startup_id: str, spaces_needed: int = 5, days: int = 7):
    """
    Recommend specific workspaces for a requesting startup.
    Example: /api/recommend-for/startup_b?spaces_needed=5
    """
    try:
        rec = engine.recommend_assignment(startup_id, spaces_needed=spaces_needed, days=days)
        return rec
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/reassign")
async def confirm_reassignment(body: dict = Body(...)):
    """
    Confirm and execute a workspace reassignment.
    Body: { "ws_ids": ["ws_011", "ws_012"], "new_startup_id": "startup_b" }
    """
    try:
        ws_ids        = body.get("ws_ids", [])
        new_startup   = body.get("new_startup_id", "")
        if not ws_ids or not new_startup:
            return JSONResponse(status_code=400,
                                content={"error": "ws_ids and new_startup_id are required"})

        result = engine.confirm_reassignment(ws_ids, new_startup)

        # Refresh the workspace_map in the processor
        processor.workspace_map = db.get_workspace_map()

        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/assignment-letter")
async def get_assignment_letter(requesting_startup: str, spaces_needed: int = 5, days: int = 7):
    """
    Generate a formal assignment letter for a proposed reassignment.
    Query: /api/assignment-letter?requesting_startup=startup_b&spaces_needed=5
    """
    try:
        rec    = engine.recommend_assignment(requesting_startup, spaces_needed=spaces_needed, days=days)
        letter = engine.generate_assignment_letter(rec)
        return {"letter": letter, "recommendation": rec}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ─── WebSocket Endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """
    WebSocket endpoint: streams annotated frames + workspace states.

    Protocol (server → client, JSON):
    {
      "type":       "frame",
      "data":       "data:image/jpeg;base64,...",
      "workspaces": { "ws_001": "occupied", "ws_002": "vacant" },
      "timestamp":  "2026-06-11T14:32:43",
      "stats":      { "occupied": 10, "vacant": 5, "total": 15 }
    }
    """
    await manager.connect(websocket)
    loop = asyncio.get_running_loop()
    frame_queue: asyncio.Queue = asyncio.Queue(maxsize=2)

    def on_frame(payload: str):
        try:
            loop.call_soon_threadsafe(frame_queue.put_nowait, payload)
        except asyncio.QueueFull:
            pass

    processor.subscribe(on_frame)

    try:
        while True:
            try:
                payload = await asyncio.wait_for(frame_queue.get(), timeout=5.0)
                await websocket.send_text(payload)
            except asyncio.TimeoutError:
                # No frame yet — keep the connection alive and keep waiting
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        processor.unsubscribe(on_frame)
        manager.disconnect(websocket)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("=" * 65)
    print("  OccuSense AI — Workspace Allocation Engine")
    print("  Dashboard:  http://localhost:8000")
    print("  API Docs:   http://localhost:8000/docs")
    print("=" * 65)
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
