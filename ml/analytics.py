"""
ml/analytics.py  (v2 — Workspace Allocation Engine)

Analytics modules:
  1. peak_hour_detection      — busiest hours of the day
  2. day_of_week_patterns     — which days are consistently underutilized
  3. workspace_utilization    — per-workspace hours/day + status classification
  4. startup_efficiency       — how efficiently each startup uses its allocated spaces
  5. full_analytics_report    — combined payload for /api/analytics
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import numpy as np
from core import database as db


# ─── 1. Peak Hour Detection ───────────────────────────────────────────────────

def peak_hour_detection(days: int = 7) -> list[dict]:
    """Return average occupancy per hour of the day with category labels."""
    hourly = db.get_hourly_avg_occupancy(days=days)
    for h in hourly:
        occ = h["avg_occupancy"]
        h["category"]   = "peak" if occ >= 0.75 else ("off_peak" if occ <= 0.30 else "moderate")
        h["hour_label"] = f"{h['hour']:02d}:00"
    return hourly


# ─── 2. Day of Week Patterns ─────────────────────────────────────────────────

def day_of_week_patterns(days: int = 30) -> list[dict]:
    """Return average occupancy per day of week with utilization label."""
    data = db.get_day_of_week_avg(days=days)
    for d in data:
        occ = d["avg_occupancy"]
        d["utilization"] = "high" if occ >= 0.70 else ("low" if occ <= 0.40 else "medium")
    return data


# ─── 3. Workspace Utilization Table ──────────────────────────────────────────

def workspace_utilization_table(days: int = 7) -> list[dict]:
    """
    Return per-workspace utilization for the Analytics tab table.

    Desk Space | Today hrs | 7-day avg | Utilization % | Status
    """
    ws_utils = db.get_all_workspace_utilizations(days=days)
    result   = []

    for ws in ws_utils:
        util = ws.get("utilization_rate", 0)
        avg_hrs = ws.get("avg_daily_hours", 0)

        # Status classification
        if util >= 0.50:
            status      = "active"
            status_icon = "Active"
        elif util >= 0.25:
            status      = "underused"
            status_icon = "Underused"
        else:
            status      = "reassignable"
            status_icon = "Reassignable"

        result.append({
            "ws_id":                    ws["ws_id"],
            "label":                    ws["label"],
            "startup_id":               ws["allocated_to"],
            "startup_name":             ws.get("startup_name", ws["allocated_to"]),
            "avg_daily_hours":          round(avg_hrs, 1),
            "utilization_rate":         round(util, 3),
            "utilization_pct":          f"{util * 100:.1f}%",
            "consecutive_vacant_days":  ws.get("consecutive_vacant_days", 0),
            "status":                   status,
            "status_icon":              status_icon,
        })

    return sorted(result, key=lambda x: x["utilization_rate"], reverse=True)


# ─── 4. Startup Efficiency ────────────────────────────────────────────────────

def startup_efficiency_report(days: int = 7) -> list[dict]:
    """Return per-startup space efficiency — how much of allocated space is used."""
    return db.get_startup_efficiency(days=days)


# ─── 5. Full Analytics Report ─────────────────────────────────────────────────

def full_analytics_report(days: int = 7) -> dict:
    """
    Generate the complete analytics payload for /api/analytics.
    Matches the dashboard's expected schema.
    """
    return {
        "peak_hours":            peak_hour_detection(days=days),
        "day_of_week":           day_of_week_patterns(days=min(days, 30)),
        "workspace_utilization": workspace_utilization_table(days=days),
        "startup_efficiency":    startup_efficiency_report(days=days),
        "analysis_days":         days,
    }


if __name__ == "__main__":
    db.init_db()
    print("\n=== Analytics Report ===")
    report = full_analytics_report(days=7)

    print("\nPeak hours:")
    for h in report["peak_hours"][:4]:
        print(f"  {h['hour_label']}: {h['avg_occupancy']*100:.0f}% ({h['category']})")

    print("\nWorkspace utilization (top 5):")
    for ws in report["workspace_utilization"][:5]:
        print(f"  {ws['label']:20s} {ws['utilization_pct']:6s}  {ws['status_icon']}")

    print("\nStartup efficiency:")
    for e in report["startup_efficiency"]:
        print(f"  {e['startup']}: {e['avg_used']}/{e['allocated']} spaces @ {e['utilization_pct']}")
