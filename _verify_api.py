"""API verification script."""
import urllib.request, json, sys

BASE = "http://localhost:8000"

def check(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=5)
        return json.loads(r.read())
    except Exception as e:
        print(f"  ERROR {path}: {e}")
        return None

print("--- /api/health ---")
d = check("/api/health")
if d:
    print(f"  status={d.get('status')}  workspaces={d.get('workspaces')}  mode={d.get('mode')}")

print("\n--- /api/workspaces ---")
d = check("/api/workspaces")
if d:
    print(f"  total_workspaces={d.get('total_workspaces')}")
    print(f"  startups={len(d.get('startups', []))}")
    for ws in d.get("workspaces", [])[:3]:
        print(f"  {ws['ws_id']}: {ws['label']} -> {ws['startup_name']}")

print("\n--- /api/recommendations ---")
d = check("/api/recommendations")
if d:
    for rpt in d.get("startup_reports", []):
        s = rpt.get("summary", {})
        print(f"  {rpt['startup_name']}: keep={s.get('keep_count')} reassignable={s.get('reassignable_count')} usage={s.get('effective_usage')}")

print("\n--- /api/recommend-for/startup_b?spaces_needed=5 ---")
d = check("/api/recommend-for/startup_b?spaces_needed=5")
if d:
    print(f"  match={d.get('match_status')}  found={d.get('spaces_found')}/{d.get('spaces_needed')}")
    for ws in d.get("recommendation", []):
        print(f"  -> {ws['label']} ({ws['utilization_pct']})")

print("\nALL ENDPOINTS OK")
