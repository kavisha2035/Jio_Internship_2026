"""Quick setup verification script."""
import sys
import io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).parent))

# Delete old DB
db_path = Path("data/logs/occupancy.db")
if db_path.exists():
    db_path.unlink()
    print("Old database removed.")

from core import database as db
db.init_db()

print("\n--- Startups ---")
for s in db.get_all_startups():
    print(f"  {s['startup_id']}: {s['name']} ({s['allocated_spaces']} spaces)")

print("\n--- Workspaces (first 5) ---")
for w in db.get_all_workspaces()[:5]:
    print(f"  {w['ws_id']}: {w['label']} -> {w['startup_name']}")

print("\n--- Assignment Engine Test ---")
from core.assignment_engine import WorkspaceAssignmentEngine
engine = WorkspaceAssignmentEngine()
result = engine.analyze_startup("startup_a", days=7)
s = result["summary"]
print(f"  Keep:         {s['keep_count']}")
print(f"  Borderline:   {s['borderline_count']}")
print(f"  Reassignable: {s['reassignable_count']}")
print(f"  Usage:        {s['effective_usage']}")

rec = engine.recommend_assignment("startup_b", spaces_needed=5)
print(f"\n  Rec for Startup Beta (5 spaces): {rec['match_status']} match")
for ws in rec["recommendation"]:
    print(f"    -> {ws['label']} ({ws['utilization_pct']})")

print("\n=== SETUP COMPLETE ===")
print("Run:  python app.py")
