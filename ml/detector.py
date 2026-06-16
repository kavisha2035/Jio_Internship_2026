"""
ml/detector.py  (v2 - Chair + Person + Posture)
Detects:
  - Persons (YOLO class 0)
  - Chairs  (YOLO class 56)

Posture analysis via MediaPipe Pose:
  - SITTING:  hip-knee vertical gap is small, person is low relative to frame
  - STANDING: hip-knee gap is large, person is taller
  - UNKNOWN:  pose landmarks not visible / confidence too low

Confidence threshold: 0.45  (calibrated for indoor office cameras)
  Too high → misses partially visible people behind desks
  Too low  → picks up bags/jackets as false positives

Performance:
  Frames are pre-resized to PROCESS_WIDTH=640 BEFORE being passed here.
  This module only receives already-downscaled frames.
"""

import os
from dataclasses import dataclass
from typing import Optional
import math

CONFIDENCE_THRESHOLD = 0.45
CHAIR_CONFIDENCE = 0.30        # Lowered — partially occluded chairs score 0.30-0.45
MIN_CHAIR_WIDTH  = 20          # Minimum chair bbox width in pixels (on 640px frame)
MIN_CHAIR_HEIGHT = 20          # Minimum chair bbox height in pixels
PROCESS_WIDTH = 640            # All frames resized to this before detection
MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() == "true"
POSTURE_EVERY_N = 3            # Run MediaPipe posture every Nth processed frame (cache between)


@dataclass
class PersonDetection:
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    posture: str = "unknown"   # "sitting" | "standing" | "unknown"

    @property
    def bottom_center(self) -> tuple[int, int]:
        return (self.x1 + self.x2) // 2, self.y2

    @property
    def center(self) -> tuple[int, int]:
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    @property
    def is_sitting(self) -> bool:
        return self.posture == "sitting"


@dataclass
class ChairDetection:
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    chair_id: str = ""         # assigned after clustering

    @property
    def center(self) -> tuple[int, int]:
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2


class PostureAnalyzer:
    """
    MediaPipe Pose-based sitting vs standing classifier.

    Sitting logic:
      When a person is sitting, the hip and knee landmarks are vertically
      close together (both near the seat level), while the ankles drop lower.

      hip_knee_gap  < 0.18  → hips and knees at similar height = sitting
      knee_ankle_gap > 0.08 → ankles well below knees = legs hanging = sitting

    We use NORMALIZED y-coordinates (0 = top, 1 = bottom of frame).
    Normalized coords are robust to camera distance/zoom changes.

    Fallback: if landmarks are not visible (low visibility score), returns "unknown".
    """

    def __init__(self):
        self._pose = None
        self._available = False
        self._init_mediapipe()

    def _init_mediapipe(self):
        try:
            import mediapipe as mp
            self._mp_pose = mp.solutions.pose
            self._pose = self._mp_pose.Pose(
                static_image_mode=False,
                model_complexity=0,       # 0=Lite (fastest), 1=Full, 2=Heavy
                enable_segmentation=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._available = True
            print("[Posture] MediaPipe Pose initialized (model_complexity=0 Lite).")
        except Exception as e:
            print(f"[Posture] MediaPipe unavailable: {e}. Posture will be 'unknown'.")
            self._available = False

    def analyze(self, frame, person: PersonDetection) -> str:
        """
        Run pose estimation on the cropped person bounding box.
        Returns "sitting", "standing", or "unknown".
        """
        if not self._available or self._pose is None:
            return "unknown"

        import mediapipe as mp
        import cv2

        # Crop with padding so pose model has context
        h, w = frame.shape[:2]
        pad = 20
        x1 = max(0, person.x1 - pad)
        y1 = max(0, person.y1 - pad)
        x2 = min(w, person.x2 + pad)
        y2 = min(h, person.y2 + pad)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return "unknown"

        # MediaPipe needs RGB
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

        try:
            results = self._pose.process(rgb)
        except Exception:
            return "unknown"

        if not results.pose_landmarks:
            return "unknown"

        lm = results.pose_landmarks.landmark
        PL = mp.solutions.pose.PoseLandmark

        # Pick the side with better visibility
        try:
            l_hip    = lm[PL.LEFT_HIP]
            l_knee   = lm[PL.LEFT_KNEE]
            l_ankle  = lm[PL.LEFT_ANKLE]
            r_hip    = lm[PL.RIGHT_HIP]
            r_knee   = lm[PL.RIGHT_KNEE]
            r_ankle  = lm[PL.RIGHT_ANKLE]
        except (IndexError, AttributeError):
            return "unknown"

        # Use the side with higher combined visibility
        left_vis  = l_hip.visibility + l_knee.visibility + l_ankle.visibility
        right_vis = r_hip.visibility + r_knee.visibility + r_ankle.visibility

        if max(left_vis, right_vis) < 1.2:   # need at least ~0.4 avg visibility
            return "unknown"

        if left_vis >= right_vis:
            hip, knee, ankle = l_hip, l_knee, l_ankle
        else:
            hip, knee, ankle = r_hip, r_knee, r_ankle

        # Normalized y increases downward (0=top, 1=bottom of crop)
        hip_y   = hip.y
        knee_y  = knee.y
        ankle_y = ankle.y

        hip_knee_gap   = abs(hip_y - knee_y)
        knee_ankle_gap = abs(knee_y - ankle_y)

        # Sitting: hip and knee are at similar height, ankle is much lower
        if hip_knee_gap < 0.18 and knee_ankle_gap > 0.08:
            return "sitting"
        else:
            return "standing"

    @property
    def available(self) -> bool:
        return self._available


class PersonDetector:
    """
    YOLOv8 detector for persons and chairs, with integrated posture analysis.
    Falls back gracefully to mock mode if YOLO is unavailable.
    """

    def __init__(self, model_size: str = "yolov8n", confidence: float = CONFIDENCE_THRESHOLD):
        self.confidence = confidence
        self.chair_confidence = CHAIR_CONFIDENCE
        self.model = None
        self._mock_mode = MOCK_MODE
        self._frame_count = 0
        self._mock_state = {}

        self.posture = PostureAnalyzer()
        self._posture_cache: dict[tuple, str] = {}   # (cx, cy) → posture
        self._posture_frame_counter = 0

        if not self._mock_mode:
            self._load_model(model_size)

    def _load_model(self, model_size: str):
        try:
            from ultralytics import YOLO
            self.model = YOLO(f"{model_size}.pt")
            print(f"[Detector] YOLOv8 loaded: {model_size}.pt | conf={self.confidence} | chair_conf={self.chair_confidence}")
        except ImportError:
            print("[Detector] ultralytics not installed — MOCK MODE.")
            self._mock_mode = True
        except Exception as e:
            print(f"[Detector] Load error: {e} — MOCK MODE.")
            self._mock_mode = True

    def detect(self, frame) -> tuple[list[PersonDetection], list[ChairDetection]]:
        """
        Detect persons and chairs in a frame.
        Also runs posture analysis on each person.
        Returns: (persons, chairs)
        """
        if self._mock_mode:
            return self._mock_detect(frame)

        try:
            # Use the LOWER threshold so both person and chair detections pass YOLO filtering
            min_conf = min(self.confidence, self.chair_confidence)
            results = self.model.predict(
                frame,
                classes=[0, 56],          # 0=person, 56=chair (COCO)
                conf=min_conf,
                iou=0.45,
                verbose=False,
            )
            persons: list[PersonDetection] = []
            chairs:  list[ChairDetection]  = []

            for box in results[0].boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf = float(box.conf[0])
                cls  = int(box.cls[0])

                if cls == 0 and conf >= self.confidence:
                    p = PersonDetection(x1, y1, x2, y2, conf)
                    # Posture analysis — run every Nth frame, cache results
                    self._posture_frame_counter += 1
                    if self.posture.available:
                        cx, cy = p.center
                        cache_key = (cx // 40, cy // 40)  # quantize to 40px grid for cache
                        if self._posture_frame_counter % POSTURE_EVERY_N == 0:
                            p.posture = self.posture.analyze(frame, p)
                            self._posture_cache[cache_key] = p.posture
                        else:
                            p.posture = self._posture_cache.get(cache_key, "unknown")
                    persons.append(p)

                elif cls == 56 and conf >= self.chair_confidence:
                    # Filter out tiny false detections (e.g. wall patterns, small objects)
                    w = x2 - x1
                    h = y2 - y1
                    if w >= MIN_CHAIR_WIDTH and h >= MIN_CHAIR_HEIGHT:
                        chairs.append(ChairDetection(x1, y1, x2, y2, conf))

            return persons, chairs

        except Exception as e:
            print(f"[Detector] Inference error: {e}")
            return [], []

    # ─── Mock Mode ───────────────────────────────────────────────────────────

    def _mock_detect(self, frame) -> tuple[list[PersonDetection], list[ChairDetection]]:
        """Simulate persons sitting in chairs for testing."""
        import numpy as np
        import random

        self._frame_count += 1
        try:
            h, w = frame.shape[:2]
        except Exception:
            h, w = 480, 640

        if not self._mock_state:
            self._init_mock(w, h)

        # Occasionally stand someone up temporarily
        if self._frame_count % 120 == 0:
            self._shuffle_mock()

        persons: list[PersonDetection] = []
        chairs:  list[ChairDetection]  = []

        for i, state in self._mock_state.items():
            cx, cy = state["chair_x"], state["chair_y"]
            pw, ph = 45, 30

            # Always generate chairs
            chairs.append(ChairDetection(
                x1=cx - pw, y1=cy - ph//2, x2=cx + pw, y2=cy + ph//2,
                confidence=0.82
            ))

            # Only generate person if seat is occupied
            if state["occupied"]:
                posture = state["posture"]
                person_h = 90 if posture == "sitting" else 140
                jx, jy = random.randint(-4, 4), random.randint(-3, 3)
                persons.append(PersonDetection(
                    x1=cx - 35 + jx, y1=cy - person_h + jy,
                    x2=cx + 35 + jx, y2=cy + jy,
                    confidence=round(random.uniform(0.70, 0.92), 2),
                    posture=posture,
                ))

        return persons, chairs

    def _init_mock(self, w: int, h: int):
        import random
        cols, rows = 5, 3
        cw = w // (cols + 1)
        ch = h // (rows + 1)
        positions = [(c * cw, r * ch) for r in range(1, rows+1) for c in range(1, cols+1)]
        occupied = set(random.sample(range(15), 10))
        for i, (cx, cy) in enumerate(positions[:15]):
            self._mock_state[i] = {
                "chair_x": cx, "chair_y": cy,
                "occupied": i in occupied,
                "posture": "sitting",
                "reappear_at": 0,
            }

    def _shuffle_mock(self):
        import random
        occupied = [k for k, v in self._mock_state.items() if v["occupied"]]
        if occupied:
            k = random.choice(occupied)
            self._mock_state[k]["occupied"] = False
            self._mock_state[k]["reappear_at"] = self._frame_count + random.randint(30, 90)
        for k, v in self._mock_state.items():
            if not v["occupied"] and self._frame_count >= v.get("reappear_at", 1e9):
                self._mock_state[k]["occupied"] = True

    @property
    def is_mock(self) -> bool:
        return self._mock_mode


if __name__ == "__main__":
    import numpy as np
    d = PersonDetector()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    persons, chairs = d.detect(frame)
    print(f"Mock={d.is_mock} | Persons={len(persons)} | Chairs={len(chairs)}")
    for p in persons:
        print(f"  Person posture={p.posture} bc={p.bottom_center}")
