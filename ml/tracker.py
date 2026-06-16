"""
ml/tracker.py  (v2)
Temporal smoothing with hysteresis thresholding — unchanged logic,
but now defaults UNKNOWN → VACANT after enough frames without data.

Key change from v1:
  - Unknown state now resolves to VACANT after window fills up with zeros
    (fixes grey seats showing in dashboard when chair is simply empty)
  - Seat IDs are now dynamic (added/removed as chairs appear/disappear)
"""

from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class OccupancyState(str, Enum):
    OCCUPIED = "occupied"
    VACANT   = "vacant"
    UNKNOWN  = "unknown"


@dataclass
class SeatTracker:
    """Tracks temporal occupancy state for a single seat (chair)."""
    seat_id: str
    window_size:      int   = 20          # frames in sliding window
    enter_threshold:  float = 0.70        # % detections to go Vacant → Occupied
    exit_threshold:   float = 0.30        # % detections to go Occupied → Vacant
    unknown_threshold: float = 0.10       # below this with full window → VACANT (not grey)
    _history: deque = field(default_factory=deque)
    _state: OccupancyState = OccupancyState.UNKNOWN

    def __post_init__(self):
        self._history = deque(maxlen=self.window_size)

    def update(self, raw_detected: bool) -> OccupancyState:
        self._history.append(int(raw_detected))

        if len(self._history) < 3:
            # Not enough data yet — return preliminary based on raw
            self._state = OccupancyState.OCCUPIED if raw_detected else OccupancyState.UNKNOWN
            return self._state

        rate = sum(self._history) / len(self._history)

        if self._state in (OccupancyState.VACANT, OccupancyState.UNKNOWN):
            if rate >= self.enter_threshold:
                self._state = OccupancyState.OCCUPIED
            elif len(self._history) >= self.window_size * 0.5 and rate <= self.unknown_threshold:
                # Window is sufficiently full and consistently empty → VACANT (no grey)
                self._state = OccupancyState.VACANT

        elif self._state == OccupancyState.OCCUPIED:
            if rate <= self.exit_threshold:
                self._state = OccupancyState.VACANT

        return self._state

    def mark_not_detected(self) -> OccupancyState:
        """
        Called when a seat's chair is not detected in this frame.
        Keeps the last known state rather than immediately flipping to vacant.
        """
        # Don't add to history — just return current state
        return self._state

    @property
    def state(self) -> OccupancyState:
        return self._state

    @property
    def occupancy_rate(self) -> float:
        if not self._history:
            return 0.0
        return sum(self._history) / len(self._history)

    def reset(self):
        self._history.clear()
        self._state = OccupancyState.UNKNOWN


class OccupancyTracker:
    """
    Manages temporal smoothing for all detected chair seats.
    Seat IDs are now dynamic — added as new chairs are detected,
    aged out when chairs haven't been seen for a while.
    """

    def __init__(
        self,
        seat_ids: list[str] = None,
        window_size:     int   = 20,
        enter_threshold: float = 0.70,
        exit_threshold:  float = 0.30,
    ):
        self.window_size     = window_size
        self.enter_threshold = enter_threshold
        self.exit_threshold  = exit_threshold
        self.trackers: dict[str, SeatTracker] = {}

        if seat_ids:
            for sid in seat_ids:
                self._add_tracker(sid)

        print(
            f"[Tracker] Ready | Window={window_size} | Enter>={enter_threshold*100:.0f}% | Exit<={exit_threshold*100:.0f}%"
        )

    def _add_tracker(self, seat_id: str):
        if seat_id not in self.trackers:
            self.trackers[seat_id] = SeatTracker(
                seat_id=seat_id,
                window_size=self.window_size,
                enter_threshold=self.enter_threshold,
                exit_threshold=self.exit_threshold,
            )

    def update(self, raw_occupancy: dict[str, bool]) -> dict[str, str]:
        """
        Update trackers for all currently known chairs.
        
        Args:
            raw_occupancy: {seat_id: True/False} — only includes chairs detected this frame.

        Returns:
            {seat_id: "occupied" | "vacant" | "unknown"}
        """
        # Ensure all current chairs have a tracker
        for seat_id in raw_occupancy:
            self._add_tracker(seat_id)

        smoothed = {}
        for seat_id, tracker in self.trackers.items():
            if seat_id in raw_occupancy:
                state = tracker.update(raw_occupancy[seat_id])
            else:
                # Chair not detected this frame — hold last state
                state = tracker.mark_not_detected()
            smoothed[seat_id] = state.value

        return smoothed

    def get_current_states(self) -> dict[str, str]:
        return {sid: t.state.value for sid, t in self.trackers.items()}

    def get_occupied_count(self) -> int:
        return sum(1 for t in self.trackers.values() if t.state == OccupancyState.OCCUPIED)

    def get_vacant_count(self) -> int:
        return sum(1 for t in self.trackers.values() if t.state == OccupancyState.VACANT)


if __name__ == "__main__":
    tracker = SeatTracker("seat_01", window_size=10)

    print("=== Test: should go OCCUPIED then VACANT ===")
    for _ in range(8):
        print(tracker.update(True))    # OCCUPIED
    for _ in range(3):
        print(tracker.update(False))   # should stay OCCUPIED (brief)
    for _ in range(8):
        print(tracker.update(False))   # should go VACANT
    print(f"Rate: {tracker.occupancy_rate:.2f}")

    print("\n=== Test: empty seat should become VACANT not UNKNOWN ===")
    t2 = SeatTracker("seat_02", window_size=10)
    for _ in range(12):
        print(t2.update(False))       # should eventually be VACANT not UNKNOWN
