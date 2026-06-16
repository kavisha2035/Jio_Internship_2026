"""
setup_workspaces.py - One-time database initialization tool

Run this ONCE before starting the application:
    python setup_workspaces.py

What it does:
  1. Deletes the existing occupancy.db (optional - prompts user)
  2. Calls init_db() which reads workspaces.json + startups.json
  3. Seeds 7 days of synthetic historical data
  4. Verifies everything is correct

After this script completes, run:
    python app.py
"""
import io
import sys
# Force UTF-8 output on Windows so print() doesn't fail on box-drawing chars
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys
import shutil
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

DB_PATH = Path(__file__).parent / "data" / "logs" / "occupancy.db"


def main():
    print("=" * 60)
    print("  OccuSense AI — Workspace Database Setup")
    print("=" * 60)
    print()

    # Optional: wipe existing DB
    if DB_PATH.exists():
        size_kb = DB_PATH.stat().st_size / 1024
        print(f"  Existing database found: {DB_PATH}")
        print(f"  Size: {size_kb:.1f} KB")
        print()
        resp = input("  Wipe and re-seed? (y/N): ").strip().lower()
        if resp == 'y':
            DB_PATH.unlink()
            print("  ✅ Old database deleted.")
        else:
            print("  ℹ️  Keeping existing database. Running init_db() to add missing tables...")
    else:
        print("  No existing database found — creating fresh.")

    print()
    print("  Loading config files...")

    from core import database as db

    # Verify config files exist
    ws_config  = Path(__file__).parent / "data" / "config" / "workspaces.json"
    st_config  = Path(__file__).parent / "data" / "config" / "startups.json"
    cam_config = Path(__file__).parent / "data" / "config" / "camera_config.json"

    for p in [ws_config, st_config, cam_config]:
        if p.exists():
            print(f"    ✅ {p.name}")
        else:
            print(f"    ❌ MISSING: {p}")
            print(f"       Please create this file before running setup.")
            sys.exit(1)

    print()
    print("  Initializing database...")
    db.init_db()

    print()
    print("  Verifying data...")
    startups   = db.get_all_startups()
    workspaces = db.get_all_workspaces()

    print(f"  ✅ Startups:    {len(startups)}")
    for s in startups:
        print(f"     - {s['startup_id']}: {s['name']} ({s['allocated_spaces']} spaces)")

    print(f"  ✅ Workspaces:  {len(workspaces)}")
    for ws in workspaces[:3]:
        print(f"     - {ws['ws_id']}: {ws['label']} → {ws['startup_name']}")
    if len(workspaces) > 3:
        print(f"     ... and {len(workspaces)-3} more")

    print()
    print("  Testing assignment engine...")
    from core.assignment_engine import WorkspaceAssignmentEngine
    engine = WorkspaceAssignmentEngine()
    result = engine.analyze_startup("startup_a", days=7)
    s      = result["summary"]
    print(f"  ✅ Startup Alpha analysis:")
    print(f"     - Active (keep):      {s['keep_count']} spaces")
    print(f"     - Borderline:         {s['borderline_count']} spaces")
    print(f"     - Reassignable:       {s['reassignable_count']} spaces")
    print(f"     - Effective usage:    {s['effective_usage']}")

    if s['reassignable_count'] > 0:
        rec = engine.recommend_assignment("startup_b", spaces_needed=5)
        print(f"\n  ✅ Recommendation for Startup Beta (needs 5 spaces):")
        print(f"     Match: {rec['match_status']} | Found: {rec['spaces_found']}/{rec['spaces_needed']}")
        for ws in rec['recommendation'][:3]:
            print(f"     → {ws['label']} ({ws['utilization_pct']})")

    print()
    print("=" * 60)
    print("  ✅ Setup complete!")
    print(f"  Database: {DB_PATH}")
    print()
    print("  Start the application with:")
    print("    python app.py")
    print()
    print("  Then open:")
    print("    http://localhost:8000")
    print("=" * 60)


if __name__ == "__main__":
    main()
