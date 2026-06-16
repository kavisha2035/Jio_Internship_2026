"""
calibrate.py
Interactive OpenCV tool for drawing polygon seat zones on a camera frame.

Usage:
  python calibrate.py [--source path/to/video.mp4]

Controls:
  Left click       → Add point to current polygon
  Enter            → Complete current polygon (prompts for seat label + startup)
  R                → Reset current polygon (start over)
  Z                → Undo last point
  S                → Save all zones to zones.json + preview image
  Q / ESC          → Quit without saving
"""

import sys
import json
import argparse
import cv2
import numpy as np
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
CONFIG_DIR = Path(__file__).parent / "data" / "config"
ZONES_FILE = CONFIG_DIR / "zones.json"
PREVIEW_FILE = CONFIG_DIR / "zones_preview.jpg"

# ─── State ────────────────────────────────────────────────────────────────────
current_points: list[tuple[int, int]] = []
zones: dict = {}
seat_counter = [1]  # mutable for use in callbacks


def mouse_callback(event, x, y, flags, param):
    """Add a point to the current polygon on left click."""
    if event == cv2.EVENT_LBUTTONDOWN:
        current_points.append((x, y))
        print(f"  Point added: ({x}, {y}) — total points: {len(current_points)}")


def draw_state(frame: np.ndarray, reference_frame: np.ndarray) -> np.ndarray:
    """Render all completed zones + current in-progress polygon on frame."""
    display = reference_frame.copy()

    # Draw completed zones
    for seat_id, data in zones.items():
        pts = np.array(data["polygon"], dtype=np.int32)
        cv2.fillPoly(display, [pts], (50, 200, 80))
        overlay = display.copy()
        cv2.fillPoly(overlay, [pts], (50, 200, 80))
        cv2.addWeighted(overlay, 0.3, display, 0.7, 0, display)
        cv2.polylines(display, [pts], True, (50, 200, 80), 2)

        # Label
        cx = int(np.mean(pts[:, 0]))
        cy = int(np.mean(pts[:, 1]))
        cv2.putText(display, data["label"], (cx - 20, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(display, data["startup"], (cx - 20, cy + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1, cv2.LINE_AA)

    # Draw current in-progress polygon
    for pt in current_points:
        cv2.circle(display, pt, 5, (0, 200, 255), -1)
    if len(current_points) >= 2:
        for i in range(len(current_points) - 1):
            cv2.line(display, current_points[i], current_points[i + 1], (0, 200, 255), 2)
        # Closing line back to first point (preview)
        cv2.line(display, current_points[-1], current_points[0], (0, 200, 255), 1)

    # Instructions overlay
    h, w = display.shape[:2]
    instructions = [
        "LEFT CLICK: Add polygon point",
        "ENTER: Complete zone",
        "R: Reset current polygon",
        "Z: Undo last point",
        "S: Save all zones",
        "Q/ESC: Quit",
        f"Zones saved: {len(zones)}",
    ]
    cv2.rectangle(display, (0, h - len(instructions) * 18 - 8), (300, h), (20, 22, 30), -1)
    for i, text in enumerate(instructions):
        cv2.putText(display, text, (6, h - (len(instructions) - i) * 18 + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 220, 180), 1)

    return display


def complete_zone() -> bool:
    """Finalize the current polygon and prompt for metadata via console."""
    global current_points

    if len(current_points) < 3:
        print("[Calibrate] Need at least 3 points to define a zone.")
        return False

    seat_id = f"seat_{seat_counter[0]:02d}"
    print(f"\n[Calibrate] Completing zone: {seat_id}")
    label = input(f"  Seat label (default: 'Seat {seat_counter[0]}'): ").strip()
    startup = input("  Startup ID (e.g. 'startup_a'): ").strip()

    if not label:
        label = f"Seat {seat_counter[0]}"
    if not startup:
        startup = "startup_a"

    zones[seat_id] = {
        "polygon": current_points.copy(),
        "label": label,
        "startup": startup,
    }
    current_points.clear()
    seat_counter[0] += 1
    print(f"  ✅ Zone '{seat_id}' ({label}) saved. Total zones: {len(zones)}")
    return True


def save_zones_to_disk():
    """Save all zones to JSON and export a labeled preview image."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    serializable = {
        k: {**v, "polygon": [list(pt) for pt in v["polygon"]]}
        for k, v in zones.items()
    }
    with open(ZONES_FILE, "w") as f:
        json.dump(serializable, f, indent=2)
    print(f"[Calibrate] ✅ Saved {len(zones)} zones to {ZONES_FILE}")


def save_preview(frame: np.ndarray):
    """Save a labeled preview image of all zones."""
    cv2.imwrite(str(PREVIEW_FILE), frame)
    print(f"[Calibrate] Preview saved to {PREVIEW_FILE}")


def open_video_source(preferred_source=None):
    """
    Try to open a video source with fallback chain.
    Raises RuntimeError if no source is available.
    """
    sources_to_try = []

    if preferred_source is not None:
        sources_to_try.append(preferred_source)

    # Default fallback chain
    sample_path = Path(__file__).parent / "data" / "sample_video.mp4"
    if sample_path.exists():
        sources_to_try.append(str(sample_path))
    sources_to_try.append(0)  # webcam

    for src in sources_to_try:
        cap = cv2.VideoCapture(src)
        if cap.isOpened():
            print(f"[Calibrate] Opened source: {src}")
            return cap
        cap.release()

    raise RuntimeError(
        "[Calibrate] No video source found.\n"
        "  Options:\n"
        "    1. Add a video file at: data/sample_video.mp4\n"
        "    2. Connect a webcam\n"
        "    3. Run: python calibrate.py --source <path_to_video>"
    )


def main():
    parser = argparse.ArgumentParser(description="Zone Calibration Tool")
    parser.add_argument("--source", default=None, help="Video source path or webcam index")
    args = parser.parse_args()

    source = args.source
    if source is not None:
        try:
            source = int(source)  # webcam index
        except ValueError:
            pass  # keep as string path

    try:
        cap = open_video_source(source)
    except RuntimeError as e:
        print(str(e))
        sys.exit(1)

    ret, reference_frame = cap.read()
    if not ret:
        print("[Calibrate] Failed to read first frame from source.")
        sys.exit(1)

    cap.release()

    window_name = "Zone Calibration — AI Video Occupancy"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 960, 600)
    cv2.setMouseCallback(window_name, mouse_callback)

    print("\n=== Zone Calibration Tool ===")
    print("Draw polygon zones over each seat in the camera frame.")
    print("See on-screen instructions for controls.\n")

    while True:
        display = draw_state(None, reference_frame)
        cv2.imshow(window_name, display)
        key = cv2.waitKey(30) & 0xFF

        if key == 13:  # Enter
            complete_zone()
        elif key == ord("r"):
            current_points.clear()
            print("[Calibrate] Reset current polygon.")
        elif key == ord("z") and current_points:
            removed = current_points.pop()
            print(f"[Calibrate] Undo last point: {removed}")
        elif key == ord("s"):
            if not zones:
                print("[Calibrate] No zones to save yet.")
            else:
                final_display = draw_state(None, reference_frame)
                save_zones_to_disk()
                save_preview(final_display)
                print("[Calibrate] All done! Run app.py to start the system.")
        elif key in (ord("q"), 27):  # Q or ESC
            print("[Calibrate] Exiting without saving.")
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
