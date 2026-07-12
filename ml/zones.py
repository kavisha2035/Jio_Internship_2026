"""
ml/zones.py  (v2 - Chair-Based Seat Association)
Replaces polygon zone approach entirely.

New approach:
  1. YOLO detects chairs as bounding boxes (class 56)
  2. Each detected person is matched to their nearest chair
  3. Only SITTING persons occupy a chair (posture check from detector.py)
  4. Chair IDs are stable across frames via IoU-based tracking

Why this is better than polygons:
  - No manual calibration needed
  - One person's bbox cannot accidentally span multiple seat zones
  - Handles people leaning or partially visible correctly
  - Works regardless of how many chairs are in the frame

Chair Matching Logic:
  - Primary: distance from person's bottom-center to chair center
  - Gate: person must be within MAX_CHAIR_DIST pixels of the chair
  - Posture gate: person must be classified as "sitting" to count as occupying
  - Conflict: if two people closest to same chair, chair is still occupied (take max)
"""

import math
from typing import Optional

# Distance gate: a person's bottom-center must be within this many pixels
# of a chair center for the association to be valid.
# Set large enough to handle CCTV perspective scaling.
MAX_CHAIR_DIST = 200   # pixels (on resized 640px-wide frame)

# Max total seats the system will track (prevents runaway from false detections)
MAX_CHAIRS = 30

# IoU threshold for chair tracking
CHAIR_IOU_THRESHOLD = 0.40



def boxes_overlap(p, c, pad=25) -> bool:
    """Check if person bbox p and chair bbox c overlap in 2D space with a lenient padding."""
    px1, py1, px2, py2 = p.x1 - pad, p.y1 - pad, p.x2 + pad, p.y2 + pad
    cx1, cy1, cx2, cy2 = c.x1 - pad, c.y1 - pad, c.x2 + pad, c.y2 + pad
    
    overlap_x = max(0, min(px2, cx2) - max(px1, cx1))
    overlap_y = max(0, min(py2, cy2) - max(py1, cy1))
    return (overlap_x > 0) and (overlap_y > 0)


def match_persons_to_chairs(
    persons: list,    # list[PersonDetection] from detector.py
    chairs:  list,    # list[ChairDetection] from detector.py
    require_sitting: bool = True,
) -> dict[int, dict]:
    """
    Core seat assignment function.

    For each chair, determine if it is occupied by a sitting person.
    
    Args:
        persons:         Detected person bounding boxes with posture labels.
        chairs:          Detected chair bounding boxes.
        require_sitting: If True, person must be classified as "sitting".
                         If False, any nearby person counts (fallback mode).

    Returns:
        { chair_index: {
            "occupied": bool,
            "person": PersonDetection | None,
            "posture": str,
            "distance": float,
          }
        }
    """
    result = {}

    # Initialize all chairs as vacant
    for i in range(len(chairs)):
        result[i] = {
            "occupied": False,
            "person": None,
            "posture": "vacant",
            "distance": float("inf"),
        }

    if not persons or not chairs:
        return result

    # For each person, find their nearest chair
    person_chair_pairs: list[tuple[float, int, int]] = []  # (dist, person_idx, chair_idx)

    for pi, person in enumerate(persons):
        # Use bottom-center of person bbox (hip/feet position)
        px, py = person.bottom_center

        for ci, chair in enumerate(chairs):
            cx, cy = chair.center
            dist = math.hypot(px - cx, py - cy)

            if dist <= MAX_CHAIR_DIST and boxes_overlap(person, chair):
                person_chair_pairs.append((dist, pi, ci))

    # Sort by distance (closest matches first)
    person_chair_pairs.sort(key=lambda x: x[0])

    # Greedy assignment — each person assigned to one chair, each chair to one person
    assigned_persons = set()
    assigned_chairs  = set()

    for dist, pi, ci in person_chair_pairs:
        # Skip already-assigned entities
        if pi in assigned_persons or ci in assigned_chairs:
            continue

        person = persons[pi]
        posture = person.posture

        # Posture gate
        if require_sitting and posture not in ("sitting", "unknown"):
            # Person is standing — do not count as seat occupant
            continue

        assigned_persons.add(pi)
        assigned_chairs.add(ci)

        result[ci] = {
            "occupied": True,
            "person": person,
            "posture": posture,
            "distance": round(dist, 1),
        }

    return result


class ChairTracker:
    """
    Tracks chair positions across frames using IoU-based matching.
    Assigns stable seat IDs (seat_01, seat_02, ...) to chairs.

    Why: YOLO detects chairs anew every frame — their order can change.
    We need consistent IDs so the DB and dashboard show the same seat
    over time, not randomly reordered.
    """

    def __init__(self):
        self._tracked: list[dict] = []   # [{id, x1,y1,x2,y2, age}]
        self._next_id = 1

    def update(self, chairs: list) -> list:
        """
        Match new detections to existing tracked chairs via IoU.
        Assign stable IDs. Returns list of ChairDetection with .chair_id set.
        """
        if not self._tracked:
            # First frame — initialize all chairs
            for c in chairs:
                c.chair_id = f"seat_{self._next_id:02d}"
                self._tracked.append({
                    "id": c.chair_id,
                    "x1": c.x1, "y1": c.y1, "x2": c.x2, "y2": c.y2,
                    "age": 0,
                })
                self._next_id += 1
            return chairs

        # Match new detections to existing tracks
        matched_new  = set()
        matched_old  = set()
        assignments  = {}   # new_idx → tracked_idx

        iou_matrix = [
            [_box_iou(c, t) for t in self._tracked]
            for c in chairs
        ]

        # Greedy best-IoU matching
        pairs = sorted(
            [(iou_matrix[ni][ti], ni, ti)
             for ni in range(len(chairs))
             for ti in range(len(self._tracked))],
            reverse=True
        )
        for iou, ni, ti in pairs:
            if iou < CHAIR_IOU_THRESHOLD:
                break
            if ni in matched_new or ti in matched_old:
                continue
            assignments[ni] = ti
            matched_new.add(ni)
            matched_old.add(ti)

        # Update matched tracks + assign IDs
        for ni, chair in enumerate(chairs):
            if ni in assignments:
                ti = assignments[ni]
                track = self._tracked[ti]
                track.update({"x1": chair.x1, "y1": chair.y1, "x2": chair.x2, "y2": chair.y2, "age": 0})
                chair.chair_id = track["id"]
            else:
                # New chair not seen before — only add if under the cap
                if len(self._tracked) < MAX_CHAIRS:
                    chair.chair_id = f"seat_{self._next_id:02d}"
                    self._tracked.append({
                        "id": chair.chair_id,
                        "x1": chair.x1, "y1": chair.y1, "x2": chair.x2, "y2": chair.y2,
                        "age": 0,
                    })
                    self._next_id += 1
                else:
                    chair.chair_id = ""   # Over cap — don't track this detection

        # Age out tracks not seen in this frame
        for ti in range(len(self._tracked)):
            if ti not in matched_old:
                self._tracked[ti]["age"] += 1

        # Remove chairs not seen for >3 consecutive frames (fast cleanup of false detections)
        self._tracked = [t for t in self._tracked if t["age"] <= 3]

        return chairs

    def reset(self):
        """Clear all tracked chairs — useful for testing or camera switch."""
        self._tracked.clear()
        self._next_id = 1

    @property
    def known_seat_ids(self) -> list[str]:
        return [t["id"] for t in self._tracked]


def build_occupancy_from_matches(
    chairs: list,           # list[ChairDetection] with chair_id set
    matches: dict,          # output from match_persons_to_chairs()
) -> dict[str, str]:
    """
    Convert match results to { seat_id: state } dict for the tracker and dashboard.

    States:
      "occupied" — sitting person matched to this chair
      "vacant"   — chair detected, no sitting person
    """
    occupancy = {}
    for ci, chair in enumerate(chairs):
        seat_id = chair.chair_id
        if not seat_id:
            continue
        match = matches.get(ci, {})
        occupancy[seat_id] = "occupied" if match.get("occupied") else "vacant"
    return occupancy


def _box_iou(a, b: dict) -> float:
    """Compute IoU between a ChairDetection and a tracked dict."""
    ax1, ay1, ax2, ay2 = a.x1, a.y1, a.x2, a.y2
    bx1, by1, bx2, by2 = b["x1"], b["y1"], b["x2"], b["y2"]

    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)

    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0

    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union  = area_a + area_b - inter

    return inter / union if union > 0 else 0.0
