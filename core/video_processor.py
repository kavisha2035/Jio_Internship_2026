"""
core/video_processor.py  (v4 — Hybrid: Chair Detection + Grid Overlay + Posture-First)

Key approach:
  1. YOLO detects persons (class 0) and chairs (class 56)
  2. Posture-first occupancy: sitting person → occupied, standing → not
  3. Grid overlay drawn on video feed (3×5 from camera_config)
  4. Chairs mapped to nearest grid cell for workspace ID assignment
  5. OccupancyTracker applies temporal smoothing to prevent flicker

Occupancy logic:
  - Person detected + sitting/unknown posture → workspace occupied
  - Person detected + standing posture → workspace NOT occupied
  - No person in cell → workspace vacant
"""

import sys
import base64
import json
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import cv2
import numpy as np

sys.path.append(str(Path(__file__).parent.parent))

from ml.detector import PersonDetector
from ml.grid_mapper import WorkspaceGridMapper, annotate_workspaces
from ml.zones import ChairTracker, match_persons_to_chairs
from ml.tracker import OccupancyTracker
from core import database as db

# ─── Performance Config ────────────────────────────────────────────────────────
PROCESS_EVERY_N_FRAMES  = 6        # ~5fps at 30fps camera (was 15 → smoother)
PROCESS_WIDTH           = 640      # resize before ML
LOG_INTERVAL_SECONDS    = 300      # save snapshots to DB every 5 min
RECONNECT_MAX_RETRIES   = 5
RECONNECT_DELAY_SECONDS = 3
JPEG_QUALITY            = 60       # lower = faster WS transmission (was 75)

# ─── Annotation Colors (BGR) ───────────────────────────────────────────────────
COLOR_PERSON    = (40, 220, 160)   # Teal — person bbox
OVERLAY_ALPHA   = 0.28

# ─── Camera ID ────────────────────────────────────────────────────────────────
DEFAULT_CAMERA_ID = "cam_floor2"


class VideoProcessor:
    """
    Single-camera ML pipeline — hybrid: chair detection + grid overlay + posture occupancy.
    Runs in a background daemon thread.
    """

    def __init__(self, source=None, camera_id: str = DEFAULT_CAMERA_ID):
        self.source    = source
        self.camera_id = camera_id
        self._running  = False
        self._thread:  Optional[threading.Thread] = None
        self._lock     = threading.Lock()

        # Shared state for API
        self.latest_frame_b64: Optional[str] = None
        self.latest_states:    dict[str, str] = {}   # {ws_id: "occupied"|"vacant"}
        self.frame_count:      int = 0

        # ML components (initialized on start())
        self.detector:      Optional[PersonDetector]      = None
        self.grid_mapper:   Optional[WorkspaceGridMapper]  = None
        self.chair_tracker: Optional[ChairTracker]         = None
        self.occ_tracker:   Optional[OccupancyTracker]     = None
        self.workspace_map: dict[str, str]                 = {}   # {ws_id: startup_id}

        # DB timing
        self._last_log_time = 0.0

        # Last occupancy state cache (for skipping redundant annotations)
        self._last_smoothed: dict[str, str] = {}

        # WebSocket subscribers
        self._ws_subscribers: list = []
        self._ws_lock = threading.Lock()

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        print("[VideoProcessor] Initializing pipeline (v4 — hybrid: chair + grid + posture)...")
        db.init_db()

        self.workspace_map  = db.get_workspace_map()
        workspace_ids       = list(self.workspace_map.keys())

        self.occ_tracker   = OccupancyTracker(
            seat_ids        = workspace_ids,
            window_size     = 20,
            enter_threshold = 0.70,
            exit_threshold  = 0.30,
        )
        self.chair_tracker = ChairTracker()
        self.detector      = PersonDetector(confidence=0.45)

        # GridMapper will be initialized after we know the frame size
        # (deferred to first frame)

        self._running = True
        self._thread  = threading.Thread(
            target=self._run_loop, daemon=True, name="VideoProcessor"
        )
        self._thread.start()
        print("[VideoProcessor] Pipeline thread started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("[VideoProcessor] Stopped.")

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ─── Main Loop ────────────────────────────────────────────────────────────

    def _run_loop(self):
        cap = self._open_capture()
        if cap is None:
            self._run_mock_loop()
            return

        raw_frame_count = 0
        retries = 0

        while self._running:
            grabbed = cap.grab()
            if not grabbed:
                retries += 1
                print(f"[VideoProcessor] Grab failed. Retry {retries}/{RECONNECT_MAX_RETRIES}")
                if retries >= RECONNECT_MAX_RETRIES:
                    cap.release()
                    self._run_mock_loop()
                    return
                time.sleep(RECONNECT_DELAY_SECONDS)
                cap = self._open_capture()
                if cap is None:
                    continue
                retries = 0
                continue

            retries = 0
            raw_frame_count += 1

            if raw_frame_count % PROCESS_EVERY_N_FRAMES != 0:
                continue

            ret, frame = cap.retrieve()
            if not ret:
                continue

            # Resize for ML
            h, w = frame.shape[:2]
            if w > PROCESS_WIDTH:
                scale = PROCESS_WIDTH / w
                frame = cv2.resize(
                    frame, (PROCESS_WIDTH, int(h * scale)),
                    interpolation=cv2.INTER_AREA
                )

            self._process_frame(frame)
            self.frame_count += 1

        cap.release()

    def _run_mock_loop(self):
        """Mock loop — synthetic frames for testing without a camera."""
        print("[VideoProcessor] Running MOCK loop.")
        while self._running:
            h, w = 480, 640
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[:] = (20, 22, 30)
            self._process_frame(frame)
            self.frame_count += 1
            time.sleep(1.0)

    # ─── Core Pipeline ────────────────────────────────────────────────────────

    def _process_frame(self, frame: np.ndarray):
        """Full ML + business logic pipeline on one frame."""
        h, w = frame.shape[:2]

        # Lazy-init grid mapper (needs frame size)
        if self.grid_mapper is None:
            self.grid_mapper = WorkspaceGridMapper(
                camera_id=self.camera_id,
                frame_w=w,
                frame_h=h,
            )
            # Sync occ_tracker with grid workspace IDs
            for ws_id in self.grid_mapper.workspace_ids:
                self.occ_tracker._add_tracker(ws_id)
        else:
            self.grid_mapper.update_frame_size(w, h)

        # 1. Detect persons and chairs (YOLO)
        persons, chairs = self.detector.detect(frame)

        # 2. Stabilize chair IDs across frames
        chairs = self.chair_tracker.update(chairs)

        # 3. CHAIR + POSTURE OCCUPANCY LOGIC:
        #    A workspace cell is occupied only if a sitting person is sitting on a chair in that cell.
        #    If no chairs are detected in the frame at all, we fall back to person-posture mapping.
        raw_occ = {cell.ws_id: False for cell in self.grid_mapper.cells}
        
        if len(chairs) > 0:
            matches = match_persons_to_chairs(persons, chairs, require_sitting=True)
            occupied_chairs = [chairs[ci] for ci, m in matches.items() if m.get("occupied")]
            
            assigned_cells = set()
            pairs = []
            for chi, chair in enumerate(occupied_chairs):
                cx, cy = chair.center
                for ci, cell in enumerate(self.grid_mapper.cells):
                    if cell.contains_point(cx, cy, tolerance=1.3):
                        dist = cell.distance_to_point(cx, cy)
                        pairs.append((dist, chi, ci))
            
            pairs.sort(key=lambda x: x[0])
            assigned_occupied_chairs = set()
            for dist, chi, ci in pairs:
                if chi in assigned_occupied_chairs or ci in assigned_cells:
                    continue
                assigned_occupied_chairs.add(chi)
                assigned_cells.add(ci)
                raw_occ[self.grid_mapper.cells[ci].ws_id] = True
        else:
            # Fallback when no chairs are visible/detected
            raw_occ_str = self.grid_mapper.map_persons_to_cells_by_posture(persons)
            raw_occ = {k: v == "occupied" for k, v in raw_occ_str.items()}


        # 4. Temporal smoothing (prevents flicker)
        smoothed = self.occ_tracker.update(raw_occ)
        # Enforce binary: only occupied / vacant (no unknown)
        smoothed = {
            ws_id: "occupied" if state == "occupied" else "vacant"
            for ws_id, state in smoothed.items()
        }

        # 5. DB snapshot logging (every LOG_INTERVAL_SECONDS)
        now = time.time()
        if now - self._last_log_time >= LOG_INTERVAL_SECONDS:
            try:
                bool_states = {k: v == "occupied" for k, v in smoothed.items()}
                db.log_occupancy_batch(bool_states, self.workspace_map)
                self._last_log_time = now
                occ_count = sum(1 for s in smoothed.values() if s == "occupied")
                print(f"[VideoProcessor] DB snapshot | Occupied={occ_count}/{len(smoothed)}")
            except Exception as e:
                print(f"[VideoProcessor] DB log error (skipping): {e}")
                self._last_log_time = now  # skip to avoid retry spam

        # 6. Annotate frame with grid overlay + person bboxes
        annotated = self._annotate(frame.copy(), persons, smoothed)

        # 7. Encode to JPEG base64
        _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        frame_b64 = "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode("utf-8")

        # 8. Update shared state
        with self._lock:
            self.latest_frame_b64 = frame_b64
            self.latest_states    = smoothed
            self._last_smoothed   = smoothed

        # 9. Broadcast to WebSocket clients
        payload = self._build_payload(frame_b64, smoothed)
        self._broadcast(payload)

    # ─── Frame Annotation ─────────────────────────────────────────────────────

    def _annotate(self, frame: np.ndarray, persons: list,
                  states: dict[str, str]) -> np.ndarray:
        """Draw workspace grid overlay + person bounding boxes on frame."""
        cells = self.grid_mapper.get_cells() if self.grid_mapper else []

        # Draw workspace grid overlay (colored rectangles)
        annotate_workspaces(frame, cells, states, overlay_alpha=OVERLAY_ALPHA)

        # Draw person bounding boxes
        for person in persons:
            cv2.rectangle(frame,
                          (person.x1, person.y1), (person.x2, person.y2),
                          COLOR_PERSON, 2)
            # Posture label
            label = person.posture.upper() if person.posture else "PERSON"
            cv2.putText(frame, label, (person.x1, person.y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_PERSON, 1, cv2.LINE_AA)

        # Stats overlay bar
        self._draw_stats(frame, states)
        return frame

    def _draw_stats(self, frame: np.ndarray, states: dict):
        total    = len(states)
        occupied = sum(1 for s in states.values() if s == "occupied")
        vacant   = total - occupied
        h, w     = frame.shape[:2]
        mode     = "[MOCK]" if (self.detector and self.detector.is_mock) else "[LIVE]"
        ts       = datetime.now().strftime("%H:%M:%S")

        cv2.rectangle(frame, (0, 0), (w, 28), (15, 17, 24), -1)
        text = f"{mode}  Workspaces: {occupied} occupied / {vacant} vacant / {total} total  |  {ts}"
        cv2.putText(frame, text, (8, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (200, 200, 200), 1, cv2.LINE_AA)

    # ─── WebSocket ────────────────────────────────────────────────────────────

    def _build_payload(self, frame_b64: str, states: dict) -> str:
        occupied = sum(1 for s in states.values() if s == "occupied")
        total    = len(states)
        return json.dumps({
            "type":      "frame",
            "data":      frame_b64,
            "workspaces": states,           # {ws_id: "occupied"|"vacant"}
            "timestamp": datetime.now().isoformat(),
            "stats": {
                "occupied": occupied,
                "vacant":   total - occupied,
                "total":    total,
            }
        })

    def subscribe(self, cb):
        with self._ws_lock:
            self._ws_subscribers.append(cb)

    def unsubscribe(self, cb):
        with self._ws_lock:
            if cb in self._ws_subscribers:
                self._ws_subscribers.remove(cb)

    def _broadcast(self, payload: str):
        with self._ws_lock:
            dead = []
            for cb in self._ws_subscribers:
                try:
                    cb(payload)
                except Exception:
                    dead.append(cb)
            for cb in dead:
                self._ws_subscribers.remove(cb)

    # ─── Source Selection ──────────────────────────────────────────────────────

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        sources = []
        if self.source is not None:
            sources = [self.source]
        else:
            vid = Path(__file__).parent.parent / "data" / "sample_video.mp4"
            if vid.exists():
                sources.append(str(vid))
            sources.append(0)

        for src in sources:
            cap = cv2.VideoCapture(src)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                print(f"[VideoProcessor] Source: {src}")
                return cap
            cap.release()

        return None


# Global singleton
processor = VideoProcessor()
