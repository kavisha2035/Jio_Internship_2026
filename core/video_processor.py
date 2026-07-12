"""
core/video_processor.py  (v5 — Simplified: Chair + Person counting only)

Stripped-down pipeline:
  1. YOLO detects persons (class 0) and chairs (class 56)
  2. Match persons to nearest chairs to find occupied chairs
  3. Draw person + chair bounding boxes on frame
  4. Send total_chairs / occupied_chairs counts via WebSocket

Removed (for speed):
  - Grid overlay / workspace grid mapper
  - CLAHE preprocessing
  - Heatmap accumulator
  - Perspective warp
  - OccupancyTracker temporal smoothing
  - DB logging per frame
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

from ml.detector import PersonDetector, ChairDetection
from ml.zones import ChairTracker, match_persons_to_chairs, boxes_overlap
from ml.chair_occupancy import get_chair_occupancy
from ml.chair_smoother import ChairCountSmoother
from ml.heatmap import OccupancyHeatmap
from core.dwell_tracker import DwellTimeTracker
from core import database as db

# ─── Performance Config ────────────────────────────────────────────────────────
PROCESS_EVERY_N_FRAMES  = 2        # process every 2nd frame for speed
PROCESS_WIDTH           = 640      # resize before ML
RECONNECT_MAX_RETRIES   = 5
RECONNECT_DELAY_SECONDS = 3
JPEG_QUALITY            = 65

# ─── Annotation Colors (BGR) ───────────────────────────────────────────────────
COLOR_PERSON         = (40, 220, 160)    # Teal — person bbox
COLOR_CHAIR_VACANT   = (180, 180, 180)   # Grey — empty chair
COLOR_CHAIR_OCCUPIED = (0, 140, 255)     # Orange — occupied chair
COLOR_SITTING        = (50, 255, 50)     # Green — sitting person

# ─── Camera ID ────────────────────────────────────────────────────────────────
DEFAULT_CAMERA_ID = "cam_floor2"


class VideoProcessor:
    """
    Simplified single-camera ML pipeline.
    Detects chairs + people, counts occupied chairs.
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
        self.latest_states:    dict[str, str] = {}
        self.frame_count:      int = 0
        self.latest_chair_counts = {"total": 0, "occupied": 0, "vacant": 0}

        # Detection counts (the new simple data)
        self.total_chairs:    int = 0
        self.occupied_chairs: int = 0
        self.total_persons:   int = 0

        # ML components and trackers
        self.detector:       Optional[PersonDetector]     = None
        self.chair_tracker:  Optional[ChairTracker]       = None
        self.heatmap:        Optional[OccupancyHeatmap]   = None
        self.chair_smoother: Optional[ChairCountSmoother] = None
        self.dwell_tracker:   Optional[DwellTimeTracker]   = None
        self.show_heatmap_overlay = False
        
        # Logging timing
        self._last_log_time  = 0.0
        self.LOG_INTERVAL_SECONDS = 300  # Log to DB every 5 minutes

        # WebSocket subscribers
        self._ws_subscribers: list = []
        self._ws_lock = threading.Lock()

        # Playlist state for sequential video looping
        self.video_playlist: list[str] = []
        self.current_video_idx: int = 0
        self.current_video_path: Optional[str] = None

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        print("[VideoProcessor] Initializing pipeline (v5 — simplified: chair + person counting)...")

        self.chair_tracker = ChairTracker()
        self.detector      = PersonDetector(confidence=0.45)
        self.chair_smoother = ChairCountSmoother(window=30)
        self.dwell_tracker  = DwellTimeTracker(db_path=str(db.DB_PATH))

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
            if getattr(self, "_is_video_file", False):
                # Pacing — use half the actual fps for faster playback
                time.sleep(1.0 / (self._video_fps * 2))

            grabbed = cap.grab()
            if not grabbed:
                if getattr(self, "_is_video_file", False):
                    if len(self.video_playlist) > 1:
                        self.current_video_idx = (self.current_video_idx + 1) % len(self.video_playlist)
                        self.current_video_path = self.video_playlist[self.current_video_idx]
                        print(f"[VideoProcessor] Switching to next video: {self.current_video_path}")
                        cap.release()
                        cap = cv2.VideoCapture(self.current_video_path)
                        if cap.isOpened():
                            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                            fps = cap.get(cv2.CAP_PROP_FPS)
                            if fps > 0:
                                self._video_fps = fps
                            grabbed = cap.grab()
                        else:
                            print(f"[VideoProcessor] Failed to open: {self.current_video_path}")
                    else:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        grabbed = cap.grab()

                if not grabbed:
                    retries += 1
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
        """Simplified pipeline: detect → match → annotate → broadcast."""
        h, w = frame.shape[:2]
        if self.heatmap is None or self.heatmap.heatmap.shape != (h, w):
            self.heatmap = OccupancyHeatmap(w, h)
        if self.detector is None:
            self.detector = PersonDetector(confidence=0.45)
        if self.chair_tracker is None:
            self.chair_tracker = ChairTracker()

        # 1. Detect persons and chairs
        persons, chairs = self.detector.detect(frame)

        
        # Step 2: Filter sitting persons only
        sitting = [p for p in persons if p.posture == "sitting"]
        
        # Synthesize virtual chairs for sitting persons who do not overlap with any detected chair
        for person in sitting:
            has_overlap = False
            for chair in chairs:
                if boxes_overlap(person, chair, pad=25):
                    has_overlap = True
                    break
            if not has_overlap:
                pw = person.x2 - person.x1
                ph = person.y2 - person.y1
                virtual_chair = ChairDetection(
                    x1 = max(0, person.x1 - int(pw * 0.15)),
                    y1 = max(0, person.y2 - int(ph * 0.45)),
                    x2 = min(w, person.x2 + int(pw * 0.15)),
                    y2 = min(h, person.y2 + int(ph * 0.15)),
                    confidence = 1.0
                )
                chairs.append(virtual_chair)
                
        # Step 2.5: Stabilize chair IDs across frames
        chairs = self.chair_tracker.update(chairs)

        # Step 3: Update heatmap with sitting persons
        self.heatmap.update(sitting)
        
        # Step 4: Get per-chair occupancy
        chair_results, raw_counts = get_chair_occupancy(
            chairs, sitting, match_distance=120
        )
        
        # Step 5.5: Smooth individual chair occupancy states (Hysteresis)
        with self._lock:
            if not hasattr(self, "chair_smoothed_states"):
                self.chair_smoothed_states = {}  # chair_id -> "vacant" or "occupied"
            if not hasattr(self, "chair_consecutive_vacant"):
                self.chair_consecutive_vacant = {}  # chair_id -> int
            if not hasattr(self, "chair_consecutive_occupied"):
                self.chair_consecutive_occupied = {}  # chair_id -> int
                
        for chair in chair_results:
            chair_id = chair["id"]
            raw_is_occupied = (chair["state"] == "occupied")
            
            # Init state if not present
            if chair_id not in self.chair_smoothed_states:
                self.chair_smoothed_states[chair_id] = "occupied" if raw_is_occupied else "vacant"
                self.chair_consecutive_vacant[chair_id] = 0
                self.chair_consecutive_occupied[chair_id] = 0
                
            current_state = self.chair_smoothed_states[chair_id]
            
            if raw_is_occupied:
                self.chair_consecutive_vacant[chair_id] = 0
                self.chair_consecutive_occupied[chair_id] += 1
                
                # Vacant -> Occupied transition: requires 3 consecutive occupied frames (~0.5s)
                if current_state == "vacant" and self.chair_consecutive_occupied[chair_id] >= 3:
                    self.chair_smoothed_states[chair_id] = "occupied"
            else:
                self.chair_consecutive_occupied[chair_id] = 0
                self.chair_consecutive_vacant[chair_id] += 1
                
                # Occupied -> Vacant transition: requires 15 consecutive vacant frames (~2.5s)
                if current_state == "occupied" and self.chair_consecutive_vacant[chair_id] >= 15:
                    self.chair_smoothed_states[chair_id] = "vacant"
            
            # Assign the stabilized state
            chair["state"] = self.chair_smoothed_states[chair_id]
                
        # Recalculate occupied/vacant based on smoothed chair states
        occupied_count = sum(1 for c in chair_results if c["state"] == "occupied")
        total_count = len(chair_results)
        raw_counts["occupied"] = occupied_count
        raw_counts["vacant"] = total_count - occupied_count
                    
        # Step 6: Smooth total chair count
        stable_total = self.chair_smoother.update(raw_counts["total"])
        
        final_counts = {
            "total":    stable_total,
            "occupied": raw_counts["occupied"],
            "vacant":   max(0, stable_total - raw_counts["occupied"])
        }
        
        # Step 7: Update dwell time tracker
        self.dwell_tracker.update(chair_results)
        dwell_times = self.dwell_tracker.get_current_dwell()
        
        # Step 8: Annotate frame (with heatmap if toggled)
        frame_to_draw = frame.copy()
        if self.show_heatmap_overlay:
            frame_to_draw = self.heatmap.get_visualization(frame_to_draw)
            
        annotated = self._annotate(
            frame_to_draw, persons, chair_results, 
            final_counts, dwell_times
        )
        
        # Step 9: Log to DB every 5 minutes
        now = time.time()
        if now - self._last_log_time >= self.LOG_INTERVAL_SECONDS:
            try:
                db.log_chair_counts(final_counts)
                self._last_log_time = now
            except Exception as e:
                print(f"[VideoProcessor] DB log error: {e}")
                self._last_log_time = now
                
        # Step 10: Broadcast
        with self._lock:
            self.total_chairs = final_counts["total"]
            self.occupied_chairs = final_counts["occupied"]
            self.total_persons = len(persons)
            self.latest_chair_counts = final_counts
            
        payload = self._build_payload(annotated, final_counts, dwell_times, len(persons))
        self._broadcast(payload)

    # ─── Frame Annotation ─────────────────────────────────────────────────────

    def _annotate(self, frame: np.ndarray, persons: list,
                  chair_results: list, counts: dict, dwell_times: dict) -> np.ndarray:
        # Draw chair bounding boxes
        for chair in chair_results:
            is_occupied = chair["state"] == "occupied"
            color = (0, 0, 255) if is_occupied else (0, 255, 0)
            thickness = 2 if is_occupied else 1
            
            cv2.rectangle(frame,
                          (chair["x1"], chair["y1"]),
                          (chair["x2"], chair["y2"]),
                          color, thickness)
            
            # Show dwell time if occupied
            idx = chair["index"]
            if idx in dwell_times:
                label = f"OCCUPIED {dwell_times[idx]}"
            else:
                label = "OCCUPIED" if is_occupied else "VACANT"
                
            # Show if detected via heatmap
            if chair.get("detection_method") == "heatmap":
                label += " (heat)"
                
            cv2.putText(frame, label,
                        (chair["x1"], chair["y1"]-8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        color, 1, cv2.LINE_AA)
                        
        # Draw person bounding boxes
        for person in persons:
            cv2.rectangle(frame,
                          (person.x1, person.y1),
                          (person.x2, person.y2),
                          (40, 220, 160), 2)
            cv2.putText(frame,
                        person.posture.upper() if person.posture else "?",
                        (person.x1, person.y1-6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                        (40, 220, 160), 1, cv2.LINE_AA)
                        
        # Stats bar
        self._draw_stats(frame, counts)
        return frame

    def _draw_stats(self, frame: np.ndarray, counts: dict):
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 30), (15, 17, 24), -1)
        
        if getattr(self, "_is_video_file", False) and self.current_video_path:
            source_name = Path(self.current_video_path).name
            mode = f"[{source_name}]"
        else:
            mode = "[MOCK]" if (self.detector and self.detector.is_mock) else "[LIVE]"
            
        text = (f"{mode}  "
                f"Chairs: {counts['occupied']} occupied  |  "
                f"{counts['vacant']} vacant  |  "
                f"{counts['total']} total")
        cv2.putText(frame, text, (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (200, 200, 200), 1, cv2.LINE_AA)

    # ─── WebSocket ────────────────────────────────────────────────────────────

    def _build_payload(self, annotated_frame: np.ndarray, counts: dict,
                       dwell_times: dict, total_persons: int) -> str:
        _, jpeg = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        frame_b64 = "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode("utf-8")
        
        with self._lock:
            self.latest_frame_b64 = frame_b64
            
        return json.dumps({
            "type":      "frame",
            "data":      frame_b64,
            "chairs": {
                "total":    counts["total"],
                "occupied": counts["occupied"],
                "vacant":   counts["vacant"]
            },
            "dwell_times":  dwell_times,
            "total_persons": total_persons,
            "timestamp":    datetime.now().isoformat()
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
            video_dir = Path(__file__).parent.parent / "video"
            if video_dir.exists():
                video_files = list(video_dir.glob("*.mp4")) + list(video_dir.glob("*.avi")) + list(video_dir.glob("*.mkv"))
                video_files = sorted(video_files)
                for vf in video_files:
                    sources.append(str(vf))

            vid = Path(__file__).parent.parent / "data" / "sample_video.mp4"
            if vid.exists():
                sources.append(str(vid))
            sources.append(0)

        # Build playlist
        if self.source is None:
            self.video_playlist = [s for s in sources if isinstance(s, str) and Path(s).exists()]
            if self.video_playlist:
                if self.current_video_path is None or self.current_video_path not in self.video_playlist:
                    self.current_video_path = self.video_playlist[self.current_video_idx]
                src = self.current_video_path
            else:
                src = 0
        else:
            src = self.source

        cap = cv2.VideoCapture(src)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            print(f"[VideoProcessor] Source: {src}")
            self._is_video_file = False
            self._video_fps = 30.0
            if isinstance(src, str) and not str(src).isdigit():
                self._is_video_file = True
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps > 0:
                    self._video_fps = fps
            return cap
        cap.release()

        return None


# Global singleton
processor = VideoProcessor()
