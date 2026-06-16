"""
ml/time_tracker.py  — Workspace Session Time Logger

Converts frame-level occupancy detections into session-level time records.

Why sessions matter:
  The business question is "how many hours per day is this desk used?"
  A session is a contiguous block of occupancy (person arrives → person leaves).
  Tracking sessions lets us answer: "Space A11 was used 0.5 hrs today,
  0.8 hrs 7-day avg" — the data the Analytics tab table needs.

Session lifecycle:
  VACANT  →  person detected  →  OPEN session (record session_start)
  OCCUPIED → person leaves    →  CLOSE session (write to DB with duration)

Minimum session duration = MIN_SESSION_MINUTES to filter out brief false positives.
"""

from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

MIN_SESSION_MINUTES = 2     # ignore sessions shorter than this
MAX_GAP_MINUTES     = 5     # gap within a session (e.g. person steps away briefly)


class WorkspaceSession:
    """Tracks one workspace's current occupancy session."""

    def __init__(self, ws_id: str, startup_id: str):
        self.ws_id:       str              = ws_id
        self.startup_id:  str              = startup_id
        self.session_start: Optional[datetime] = None
        self.last_occupied: Optional[datetime] = None
        self.is_open:       bool               = False

    def open(self, ts: datetime):
        """Person arrives at this workspace — open a session."""
        if not self.is_open:
            self.session_start = ts
            self.is_open       = True
        self.last_occupied = ts

    def update_occupied(self, ts: datetime):
        """Still occupied — update last seen timestamp."""
        self.last_occupied = ts

    def should_close(self, now: datetime) -> bool:
        """
        Return True if the session should be closed.
        Closes after MAX_GAP_MINUTES of no detection.
        """
        if not self.is_open or self.last_occupied is None:
            return False
        elapsed = (now - self.last_occupied).total_seconds() / 60
        return elapsed >= MAX_GAP_MINUTES

    def close(self, ts: datetime) -> Optional[dict]:
        """
        Close this session.
        Returns a session dict if duration >= MIN_SESSION_MINUTES, else None.
        """
        if not self.is_open or self.session_start is None:
            return None

        duration_min = int((ts - self.session_start).total_seconds() / 60)
        self.is_open = False

        if duration_min < MIN_SESSION_MINUTES:
            return None   # Too short — ignore (walking past, false positive)

        return {
            "ws_id":            self.ws_id,
            "startup_id":       self.startup_id,
            "session_start":    self.session_start.isoformat(),
            "session_end":      ts.isoformat(),
            "duration_minutes": duration_min,
        }

    def duration_so_far(self, now: datetime) -> float:
        """Return minutes elapsed in the current open session."""
        if not self.is_open or self.session_start is None:
            return 0.0
        return (now - self.session_start).total_seconds() / 60


class WorkspaceTimeTracker:
    """
    Manages session-level time tracking for all workspaces.

    Usage (in video_processor.py, called each processed frame):

        time_tracker = WorkspaceTimeTracker(workspace_map)

        # Each frame:
        completed_sessions = time_tracker.update(occupancy_states)
        # occupancy_states: {ws_id: "occupied" | "vacant"}

        # Completed sessions are automatically written to the DB.
    """

    def __init__(self, workspace_map: dict[str, str]):
        """
        Args:
            workspace_map: {ws_id: startup_id}
        """
        self._sessions: dict[str, WorkspaceSession] = {}
        for ws_id, startup_id in workspace_map.items():
            self._sessions[ws_id] = WorkspaceSession(ws_id, startup_id)

        print(f"[TimeTracker] Tracking {len(self._sessions)} workspaces.")

    def update(self, occupancy_states: dict[str, str]) -> list[dict]:
        """
        Process one frame's occupancy states.
        Opens/closes sessions as workspaces transition between states.

        Args:
            occupancy_states: {ws_id: "occupied" | "vacant"}

        Returns:
            List of completed session dicts (ready to write to DB).
        """
        now = datetime.now()
        completed = []

        for ws_id, session in self._sessions.items():
            state = occupancy_states.get(ws_id, "vacant")

            if state == "occupied":
                if session.is_open:
                    session.update_occupied(now)
                else:
                    session.open(now)

            else:  # vacant
                if session.is_open and session.should_close(now):
                    result = session.close(now)
                    if result:
                        completed.append(result)

        return completed

    def force_close_all(self) -> list[dict]:
        """
        Close all open sessions — called on shutdown.
        Returns list of completed session dicts.
        """
        now       = datetime.now()
        completed = []
        for session in self._sessions.values():
            if session.is_open:
                result = session.close(now)
                if result:
                    completed.append(result)
        return completed

    def get_open_sessions_summary(self) -> list[dict]:
        """Return a summary of currently open sessions (for real-time display)."""
        now = datetime.now()
        result = []
        for ws_id, session in self._sessions.items():
            if session.is_open:
                result.append({
                    "ws_id":            ws_id,
                    "duration_minutes": round(session.duration_so_far(now), 1),
                    "session_start":    session.session_start.isoformat() if session.session_start else None,
                })
        return result

    def add_workspace(self, ws_id: str, startup_id: str):
        """Register a new workspace mid-runtime (e.g. config reload)."""
        if ws_id not in self._sessions:
            self._sessions[ws_id] = WorkspaceSession(ws_id, startup_id)


# ─── Standalone DB writer ──────────────────────────────────────────────────────

def flush_sessions_to_db(sessions: list[dict]):
    """Write a list of completed sessions to the database."""
    if not sessions:
        return
    from core import database as db
    for s in sessions:
        db.log_session(
            ws_id            = s["ws_id"],
            startup_id       = s["startup_id"],
            session_start    = s["session_start"],
            session_end      = s["session_end"],
            duration_minutes = s["duration_minutes"],
        )
    print(f"[TimeTracker] Flushed {len(sessions)} sessions to DB.")


if __name__ == "__main__":
    # Self-test
    workspace_map = {
        "ws_001": "startup_a",
        "ws_002": "startup_a",
        "ws_011": "startup_a",
    }
    tracker = WorkspaceTimeTracker(workspace_map)

    print("Simulating 10 minutes of occupancy on ws_001...")
    import time

    states = {"ws_001": "occupied", "ws_002": "vacant", "ws_011": "vacant"}
    for i in range(20):
        completed = tracker.update(states)
        if completed:
            print(f"  Session completed: {completed}")
        time.sleep(0.1)

    # Force close
    final = tracker.force_close_all()
    print(f"Force-closed sessions: {final}")
