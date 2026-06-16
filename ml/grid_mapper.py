"""
ml/grid_mapper.py  — Person-Position to Workspace Cell Mapper

Replaces the chair-based seat association in zones.py.

Core concept:
  Instead of detecting chairs and matching people to chairs,
  we define a fixed grid of workspace cells that covers the camera frame.
  When a sitting person is detected, we find which grid cell their
  bottom-center point falls into, and mark that workspace as occupied.

Grid layout (example for cam_floor2, 3 rows × 5 cols):
  ┌──────────┬──────────┬──────────┬──────────┬──────────┐
  │  ws_001  │  ws_002  │  ws_003  │  ws_004  │  ws_005  │  row 0
  ├──────────┼──────────┼──────────┼──────────┼──────────┤
  │  ws_006  │  ws_007  │  ws_008  │  ws_009  │  ws_010  │  row 1
  ├──────────┼──────────┼──────────┼──────────┼──────────┤
  │  ws_011  │  ws_012  │  ws_013  │  ws_014  │  ws_015  │  row 2
  └──────────┴──────────┴──────────┴──────────┴──────────┘

This gives each workspace a fixed pixel bounding box in the frame,
making occupancy detection independent of chair visibility.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ─── Config ───────────────────────────────────────────────────────────────────
CONFIG_DIR   = Path(__file__).parent.parent / "data" / "config"
WS_CONFIG    = CONFIG_DIR / "workspaces.json"
CAM_CONFIG   = CONFIG_DIR / "camera_config.json"

# Person's bottom-center must be within this fraction of cell width/height
# to be considered "inside" a workspace cell.
# 1.0 = must be strictly inside  |  1.3 = 30% margin tolerance
CELL_TOLERANCE = 1.15


@dataclass
class WorkspaceCell:
    """A single workspace cell in the camera frame."""
    ws_id:      str
    label:      str
    camera_id:  str
    grid_row:   int
    grid_col:   int
    startup_id: str

    # Pixel bounding box in the camera frame (computed from grid position)
    px1: int = 0
    py1: int = 0
    px2: int = 0
    py2: int = 0

    @property
    def center(self) -> tuple[int, int]:
        return (self.px1 + self.px2) // 2, (self.py1 + self.py2) // 2

    @property
    def cell_w(self) -> int:
        return self.px2 - self.px1

    @property
    def cell_h(self) -> int:
        return self.py2 - self.py1

    def contains_point(self, x: int, y: int, tolerance: float = CELL_TOLERANCE) -> bool:
        """Return True if (x, y) is inside this cell (with tolerance margin)."""
        cx, cy   = self.center
        half_w   = (self.cell_w / 2) * tolerance
        half_h   = (self.cell_h / 2) * tolerance
        return (cx - half_w) <= x <= (cx + half_w) and (cy - half_h) <= y <= (cy + half_h)

    def distance_to_point(self, x: int, y: int) -> float:
        """Euclidean distance from (x, y) to the cell center."""
        cx, cy = self.center
        return math.hypot(x - cx, y - cy)


class WorkspaceGridMapper:
    """
    Maps detected persons in a camera frame to workspace cells.

    Usage:
        mapper = WorkspaceGridMapper(camera_id="cam_floor2",
                                     frame_w=640, frame_h=480)

        # Each frame:
        occupancy = mapper.map_persons_to_workspaces(persons)
        # Returns: {"ws_001": True, "ws_002": False, ...}

        # For annotation:
        cells = mapper.get_cells()
    """

    def __init__(self,
                 camera_id: str = "cam_floor2",
                 frame_w:   int = 640,
                 frame_h:   int = 480):
        self.camera_id = camera_id
        self.frame_w   = frame_w
        self.frame_h   = frame_h
        self.cells:    list[WorkspaceCell] = []
        self._load_and_compute()

    # ─── Setup ────────────────────────────────────────────────────────────────

    def _load_and_compute(self):
        """Load workspace definitions and compute pixel bounding boxes."""
        grid_rows, grid_cols = self._get_camera_grid()

        # Cell pixel dimensions
        cell_w = self.frame_w // grid_cols
        cell_h = self.frame_h // grid_rows

        # Load workspace configs
        if WS_CONFIG.exists():
            with open(WS_CONFIG) as f:
                data = json.load(f)
            wss = [w for w in data["workspaces"] if w["camera_id"] == self.camera_id]
        else:
            wss = self._fallback_workspaces(grid_rows, grid_cols)

        for ws in wss:
            row = ws["grid_row"]
            col = ws["grid_col"]
            px1 = col * cell_w
            py1 = row * cell_h
            px2 = px1 + cell_w
            py2 = py1 + cell_h

            self.cells.append(WorkspaceCell(
                ws_id      = ws["id"],
                label      = ws["label"],
                camera_id  = ws["camera_id"],
                grid_row   = row,
                grid_col   = col,
                startup_id = ws.get("allocated_to", "startup_a"),
                px1 = px1, py1 = py1,
                px2 = px2, py2 = py2,
            ))

        print(f"[GridMapper] Loaded {len(self.cells)} workspace cells "
              f"for {self.camera_id} ({grid_rows}×{grid_cols} grid, "
              f"{self.frame_w}×{self.frame_h} frame)")

    def _get_camera_grid(self) -> tuple[int, int]:
        """Read grid dimensions from camera_config.json."""
        if CAM_CONFIG.exists():
            with open(CAM_CONFIG) as f:
                data = json.load(f)
            for cam in data.get("cameras", []):
                if cam["id"] == self.camera_id:
                    return cam["grid_rows"], cam["grid_cols"]
        return 3, 5   # default fallback

    def _fallback_workspaces(self, rows: int, cols: int) -> list[dict]:
        """Generate workspace definitions programmatically if JSON is missing."""
        result = []
        for r in range(rows):
            for c in range(cols):
                idx = r * cols + c + 1
                result.append({
                    "id": f"ws_{idx:03d}",
                    "label": f"Desk Space A{idx}",
                    "camera_id": self.camera_id,
                    "grid_row": r,
                    "grid_col": c,
                    "allocated_to": "startup_a",
                })
        return result

    # ─── Core Mapping ─────────────────────────────────────────────────────────

    def map_persons_to_workspaces(self,
                                   persons: list,
                                   require_sitting: bool = True) -> dict[str, bool]:
        """
        Determine which workspace cells are occupied by sitting persons.

        Args:
            persons:         list[PersonDetection] from detector.py
            require_sitting: If True, only "sitting" posture counts as occupying.
                             If False, any person in the cell counts.

        Returns:
            {ws_id: is_occupied (bool)}  — all cells, True/False, no unknown
        """
        # Start: all workspaces vacant
        occupancy = {cell.ws_id: False for cell in self.cells}

        # Filter: only count sitting persons (or all if posture unavailable)
        eligible = []
        for p in persons:
            if require_sitting:
                if p.posture in ("sitting", "unknown"):
                    eligible.append(p)
            else:
                eligible.append(p)

        if not eligible or not self.cells:
            return occupancy

        # For each eligible person, find the nearest workspace cell
        # Use bottom-center of their bounding box (hip/feet position)
        assigned_cells = set()

        # Build (distance, person_idx, cell_idx) pairs
        pairs = []
        for pi, person in enumerate(eligible):
            px, py = person.bottom_center
            for ci, cell in enumerate(self.cells):
                if cell.contains_point(px, py):
                    dist = cell.distance_to_point(px, py)
                    pairs.append((dist, pi, ci))

        # Sort by closest match first, greedy assignment
        pairs.sort(key=lambda x: x[0])
        assigned_persons = set()

        for dist, pi, ci in pairs:
            if pi in assigned_persons or ci in assigned_cells:
                continue
            assigned_persons.add(pi)
            assigned_cells.add(ci)
            occupancy[self.cells[ci].ws_id] = True

        return occupancy

    # ─── Accessors ────────────────────────────────────────────────────────────

    def get_cells(self) -> list[WorkspaceCell]:
        """Return all workspace cells (for frame annotation)."""
        return self.cells

    def get_cell_by_id(self, ws_id: str) -> Optional[WorkspaceCell]:
        for cell in self.cells:
            if cell.ws_id == ws_id:
                return cell
        return None

    @property
    def workspace_ids(self) -> list[str]:
        return [c.ws_id for c in self.cells]

    def update_frame_size(self, frame_w: int, frame_h: int):
        """Recompute cell pixel bounds if the frame size changes."""
        if frame_w != self.frame_w or frame_h != self.frame_h:
            self.frame_w = frame_w
            self.frame_h = frame_h
            self.cells.clear()
            self._load_and_compute()

    def map_chairs_to_cells(self, chairs: list) -> dict[str, bool]:
        """
        Map detected chairs to their nearest grid cell.
        Returns {ws_id: has_chair_in_cell (bool)} for all cells.
        """
        cell_has_chair = {cell.ws_id: False for cell in self.cells}
        assigned_cells = set()

        # Build (distance, chair_idx, cell_idx) pairs
        pairs = []
        for chi, chair in enumerate(chairs):
            cx, cy = chair.center
            for ci, cell in enumerate(self.cells):
                if cell.contains_point(cx, cy, tolerance=1.3):
                    dist = cell.distance_to_point(cx, cy)
                    pairs.append((dist, chi, ci))

        pairs.sort(key=lambda x: x[0])
        assigned_chairs = set()

        for dist, chi, ci in pairs:
            if chi in assigned_chairs or ci in assigned_cells:
                continue
            assigned_chairs.add(chi)
            assigned_cells.add(ci)
            cell_has_chair[self.cells[ci].ws_id] = True

        return cell_has_chair

    def map_persons_to_cells_by_posture(self, persons: list) -> dict[str, str]:
        """
        Posture-first occupancy: map each person to their nearest grid cell.
        Sitting person → occupied, standing → vacant.
        Returns {ws_id: "occupied" | "vacant"} for all cells.
        """
        occupancy = {cell.ws_id: "vacant" for cell in self.cells}
        assigned_cells = set()

        # Build (distance, person_idx, cell_idx) pairs
        pairs = []
        for pi, person in enumerate(persons):
            px, py = person.bottom_center
            for ci, cell in enumerate(self.cells):
                if cell.contains_point(px, py, tolerance=1.3):
                    dist = cell.distance_to_point(px, py)
                    pairs.append((dist, pi, ci))

        pairs.sort(key=lambda x: x[0])
        assigned_persons = set()

        for dist, pi, ci in pairs:
            if pi in assigned_persons or ci in assigned_cells:
                continue
            person = persons[pi]
            # Posture-based: sitting or unknown → occupied, standing → not
            if person.posture in ("sitting", "unknown"):
                assigned_persons.add(pi)
                assigned_cells.add(ci)
                occupancy[self.cells[ci].ws_id] = "occupied"

        return occupancy


# ─── Annotation Helper ─────────────────────────────────────────────────────────

def annotate_workspaces(frame,
                         cells: list[WorkspaceCell],
                         occupancy: dict[str, str],
                         overlay_alpha: float = 0.30) -> None:
    """
    Draw workspace cell grid overlay on the frame (in-place).

    Args:
        frame:         BGR numpy array (modified in-place)
        cells:         list of WorkspaceCell objects
        occupancy:     {ws_id: "occupied" | "vacant"}
        overlay_alpha: transparency of cell fill (0=transparent, 1=opaque)
    """
    import cv2
    import numpy as np

    COLOR_OCCUPIED = (0, 107, 255)    # Orange (BGR) — matches dashboard accent
    COLOR_VACANT   = (60,  60,  60)   # Dim grey (BGR) — subtle for vacant
    BORDER_W       = 2

    overlay = frame.copy()

    for cell in cells:
        state = occupancy.get(cell.ws_id, "vacant")
        color = COLOR_OCCUPIED if state == "occupied" else COLOR_VACANT

        # Semi-transparent fill
        cv2.rectangle(overlay, (cell.px1, cell.py1), (cell.px2, cell.py2), color, -1)

    # Blend overlay with original frame
    cv2.addWeighted(overlay, overlay_alpha, frame, 1 - overlay_alpha, 0, frame)

    # Draw borders and labels on top (no blending)
    for cell in cells:
        state = occupancy.get(cell.ws_id, "vacant")
        color = COLOR_OCCUPIED if state == "occupied" else COLOR_VACANT

        # Cell border
        cv2.rectangle(frame, (cell.px1, cell.py1), (cell.px2, cell.py2), color, BORDER_W)

        # Label: workspace ID + status
        short_label = cell.label.replace("Desk Space ", "")   # "A1", "A2" etc.
        status_text = "OCC" if state == "occupied" else "VAC"
        lx = cell.px1 + 4
        ly = cell.py1 + 14
        cv2.putText(frame, short_label, (lx, ly),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, status_text, (lx, ly + 13),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.30, color, 1, cv2.LINE_AA)


if __name__ == "__main__":
    # Quick self-test
    mapper = WorkspaceGridMapper(camera_id="cam_floor2", frame_w=640, frame_h=480)
    print(f"\nCells: {len(mapper.cells)}")
    for c in mapper.cells:
        print(f"  {c.ws_id}: {c.label} | grid({c.grid_row},{c.grid_col}) "
              f"| px({c.px1},{c.py1})→({c.px2},{c.py2})")

    # Simulate a person sitting at (320, 320) — should map to row=2, col=2 = ws_013
    from dataclasses import dataclass as dc

    @dc
    class FakePerson:
        x1: int = 290; y1: int = 250; x2: int = 350; y2: int = 330
        posture: str = "sitting"

        @property
        def bottom_center(self):
            return (self.x1 + self.x2) // 2, self.y2

    occ = mapper.map_persons_to_workspaces([FakePerson()])
    occupied = [ws_id for ws_id, v in occ.items() if v]
    print(f"\nOccupied workspaces: {occupied}")
