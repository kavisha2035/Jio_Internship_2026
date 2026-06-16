"""
core/assignment_engine.py  — Workspace Space Allocation Business Logic

This is the KEY business logic file.

It answers two questions:
  1. "Which of Startup A's spaces can be safely reassigned?"
  2. "Startup B needs N spaces — which specific ones do we give them?"

Classification logic:
  utilization = occupied_minutes / (days × 8hrs × 60min)
  peak_util   = avg occupancy during 9am–6pm

  if util < 0.50 AND peak_util < 0.60:  → "reassignable"
  elif util < 0.65:                       → "borderline"
  else:                                   → "keep"

All thresholds are configurable class constants.
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))
from core import database as db


class WorkspaceAssignmentEngine:
    """
    Analyzes desk space utilization and recommends space reallocations.

    Example usage:
        engine = WorkspaceAssignmentEngine()

        # Analyze a startup's usage
        result = engine.analyze_startup("startup_a", days=7)
        print(result["summary"])

        # Recommend spaces for a new startup
        recs = engine.recommend_assignment("startup_b", spaces_needed=5)
        letter = engine.generate_assignment_letter(recs)
    """

    UTILIZATION_THRESHOLD = 0.50   # below 50% = underutilized
    PEAK_THRESHOLD        = 0.60   # below 60% even at peak = safe to reassign
    BORDERLINE_THRESHOLD  = 0.65   # below 65% = borderline
    MIN_DAYS_DATA         = 3      # minimum days before making recommendations

    def __init__(self):
        self.db = db   # reference to database module

    # ─── Core Analysis ────────────────────────────────────────────────────────

    def analyze_startup(self, startup_id: str, days: int = 7) -> dict:
        """
        Full utilization analysis of all workspaces allocated to a startup.

        Returns:
        {
          "startup":           str,
          "startup_name":      str,
          "total_allocated":   int,
          "analysis_days":     int,
          "workspaces":        [WorkspaceAnalysis, ...],
          "summary": {
            "keep_count":         int,
            "borderline_count":   int,
            "reassignable_count": int,
            "effective_usage":    str,   e.g. "10/15 spaces"
            "reassignable_ids":   [str],
            "borderline_ids":     [str],
          }
        }
        """
        workspaces = self.db.get_startup_workspaces(startup_id)
        startups   = {s["startup_id"]: s for s in self.db.get_all_startups()}
        startup    = startups.get(startup_id, {})

        results = {
            "startup":         startup_id,
            "startup_name":    startup.get("name", startup_id),
            "total_allocated": len(workspaces),
            "analysis_days":   days,
            "workspaces":      [],
            "summary":         {},
        }

        reassignable = []
        borderline   = []
        keep         = []

        for ws in workspaces:
            stats = self.db.get_workspace_stats(ws["ws_id"], days)

            util       = stats["utilization_rate"]
            peak_util  = stats["peak_hour_utilization"]
            vacant_days = stats["consecutive_vacant_days"]
            daily_hrs  = stats["avg_daily_hours"]

            # Classify
            if util < self.UTILIZATION_THRESHOLD and peak_util < self.PEAK_THRESHOLD:
                status = "reassignable"
                reassignable.append(ws["ws_id"])
            elif util < self.BORDERLINE_THRESHOLD:
                status = "borderline"
                borderline.append(ws["ws_id"])
            else:
                status = "keep"
                keep.append(ws["ws_id"])

            results["workspaces"].append({
                "id":                    ws["ws_id"],
                "label":                 ws["label"],
                "utilization":           round(util, 2),
                "utilization_pct":       f"{util * 100:.1f}%",
                "peak_utilization":      round(peak_util, 2),
                "consecutive_vacant_days": vacant_days,
                "avg_daily_hours":       daily_hrs,
                "status":                status,
                "reason":                self._reason(util, peak_util, vacant_days, days),
            })

        results["summary"] = {
            "keep_count":         len(keep),
            "borderline_count":   len(borderline),
            "reassignable_count": len(reassignable),
            "effective_usage":    f"{len(keep)}/{len(workspaces)} spaces",
            "reassignable_ids":   reassignable,
            "borderline_ids":     borderline,
            "keep_ids":           keep,
        }

        return results

    # ─── Recommendation Engine ─────────────────────────────────────────────────

    def recommend_assignment(self,
                              requesting_startup: str,
                              spaces_needed: int,
                              days: int = 7) -> dict:
        """
        Find the best N underutilized spaces to give to a requesting startup.

        Args:
            requesting_startup: startup_id of the company that needs more space
            spaces_needed:      how many spaces they need
            days:               analysis window

        Returns:
        {
          "requesting_startup": str,
          "spaces_needed":      int,
          "spaces_found":       int,
          "match_status":       "exact" | "partial" | "none",
          "recommendation":     [WorkspaceRec, ...],
          "action":             ActionPlan,
        }
        """
        all_reassignable = self.db.get_all_reassignable_spaces(
            days=days,
            util_threshold=self.UTILIZATION_THRESHOLD,
            peak_threshold=self.PEAK_THRESHOLD,
        )

        # Sort by lowest utilization first (most safe to reassign)
        all_reassignable.sort(key=lambda x: x.get("utilization_rate", 1.0))

        # Take top N
        recommended = all_reassignable[:spaces_needed]

        # Determine match status
        if len(recommended) >= spaces_needed:
            match_status = "exact"
        elif len(recommended) > 0:
            match_status = "partial"
        else:
            match_status = "none"

        return {
            "requesting_startup": requesting_startup,
            "spaces_needed":      spaces_needed,
            "spaces_found":       len(recommended),
            "match_status":       match_status,
            "recommendation":     [
                {
                    "ws_id":               ws["ws_id"],
                    "label":               ws["label"],
                    "current_owner":       ws["allocated_to"],
                    "current_owner_name":  ws.get("startup_name", ws["allocated_to"]),
                    "utilization":         round(ws.get("utilization_rate", 0), 2),
                    "utilization_pct":     f"{ws.get('utilization_rate', 0) * 100:.1f}%",
                    "avg_daily_hours":     ws.get("avg_daily_hours", 0),
                    "consecutive_vacant":  ws.get("consecutive_vacant_days", 0),
                    "reason":              self._reason(
                        ws.get("utilization_rate", 0),
                        ws.get("peak_hour_utilization", 0),
                        ws.get("consecutive_vacant_days", 0),
                        days,
                    ),
                }
                for ws in recommended
            ],
            "action": self._generate_action_plan(recommended, requesting_startup),
        }

    def confirm_reassignment(self, ws_ids: list[str], new_startup_id: str) -> dict:
        """
        Execute a confirmed reassignment — update DB and return summary.
        Called when user clicks [Confirm] in the dashboard.
        """
        for ws_id in ws_ids:
            self.db.update_workspace_allocation(ws_id, new_startup_id)

        return {
            "status":          "confirmed",
            "reassigned_count": len(ws_ids),
            "reassigned_ids":  ws_ids,
            "new_owner":       new_startup_id,
            "confirmed_at":    datetime.now().isoformat(),
        }

    # ─── Letter Generator ─────────────────────────────────────────────────────

    def generate_assignment_letter(self, recommendation: dict) -> str:
        """
        Generate a formal space assignment letter for the recommended spaces.
        Used by the [Generate Assignment Letter] button in the dashboard.

        Args:
            recommendation: output of recommend_assignment()

        Returns:
            Formatted letter text (plain text, ready to display/print)
        """
        startups   = {s["startup_id"]: s for s in self.db.get_all_startups()}
        req_id     = recommendation["requesting_startup"]
        req_name   = startups.get(req_id, {}).get("name", req_id)
        spaces     = recommendation["recommendation"]
        action     = recommendation.get("action", {})
        today      = datetime.now().strftime("%B %d, %Y")

        lines = [
            "=" * 60,
            "    CO-WORKING SPACE ALLOCATION NOTICE",
            "=" * 60,
            f"Date:     {today}",
            f"To:       {req_name}",
            f"Subject:  Workspace Assignment — {len(spaces)} Desk Space(s)",
            "",
            "Dear Team,",
            "",
            f"We are pleased to confirm the allocation of {len(spaces)} desk "
            f"workspace(s) to {req_name}, effective immediately.",
            "",
            "ASSIGNED WORKSPACES:",
            "-" * 40,
        ]

        for i, ws in enumerate(spaces, 1):
            owner_name = ws.get("current_owner_name", ws.get("current_owner", ""))
            lines.append(
                f"  {i}. {ws['label']}"
                f"  (Previously: {owner_name} | Utilization: {ws['utilization_pct']})"
            )

        lines += [
            "",
            "TRANSITION DETAILS:",
            f"  Transition Period:  {action.get('suggested_transition_days', 3)} business days",
            f"  Action Required:    {action.get('immediate_action', 'Proceed with reassignment')}",
            "",
            "NOTES:",
            "  - Please coordinate with facilities for access card updates.",
            "  - Previous tenants have been notified per contract terms.",
            "  - Space availability is based on 7-day utilization analysis.",
            "",
            "For questions, contact the Space Management team.",
            "",
            "Regards,",
            "Space Optimization System",
            "Powered by OccuSense AI",
            "=" * 60,
        ]

        return "\n".join(lines)

    # ─── Bulk Report ──────────────────────────────────────────────────────────

    def full_space_optimization_report(self, days: int = 7) -> dict:
        """
        Generate the complete optimization report for the dashboard Tab 3.

        Returns combined analysis for all startups + cross-startup
        recommendation for any startup that needs more space.
        """
        startups = self.db.get_all_startups()
        report   = {
            "generated_at":   datetime.now().isoformat(),
            "analysis_days":  days,
            "startup_reports": [],
            "total_reassignable": 0,
        }

        for s in startups:
            analysis = self.analyze_startup(s["startup_id"], days=days)
            report["startup_reports"].append(analysis)
            report["total_reassignable"] += analysis["summary"]["reassignable_count"]

        return report

    # ─── Private Helpers ──────────────────────────────────────────────────────

    def _reason(self, util: float, peak: float, vacant_days: int, days: int) -> str:
        """Generate human-readable reason text for a workspace classification."""
        if vacant_days >= 5:
            return f"Unused for {vacant_days} consecutive days"
        if util < 0.15:
            return f"Only {int(util * 100)}% utilized over {days} days — essentially idle"
        if util < 0.30:
            return f"Only {int(util * 100)}% utilized over {days} days"
        if peak < 0.40:
            return f"Even at peak hours, only {int(peak * 100)}% occupied"
        if util < self.UTILIZATION_THRESHOLD:
            return f"{int(util * 100)}% utilization — below 50% threshold"
        return f"{int(util * 100)}% utilization — borderline case"

    def _generate_action_plan(self, spaces: list, new_startup: str) -> dict:
        startups  = {s["startup_id"]: s for s in self.db.get_all_startups()}
        new_name  = startups.get(new_startup, {}).get("name", new_startup)

        # Group by current owner for notification list
        owners = {}
        for ws in spaces:
            owner = ws.get("allocated_to", "unknown")
            owners.setdefault(owner, []).append(ws.get("label", ws.get("ws_id")))

        notify = [
            startups.get(owner_id, {}).get("name", owner_id)
            for owner_id in owners
        ]

        return {
            "immediate_action":        f"Reassign {len(spaces)} workspace(s) to {new_name}",
            "notify_current_owners":   notify,
            "suggested_transition_days": 3,
            "spaces_to_reassign":      [s.get("label", s.get("ws_id")) for s in spaces],
            "ws_ids_to_reassign":      [s.get("ws_id", "") for s in spaces],
        }


# ─── Convenience Functions (called from app.py) ───────────────────────────────

_engine = None

def get_engine() -> WorkspaceAssignmentEngine:
    """Return the singleton engine instance."""
    global _engine
    if _engine is None:
        _engine = WorkspaceAssignmentEngine()
    return _engine


if __name__ == "__main__":
    db.init_db()
    engine = WorkspaceAssignmentEngine()

    print("\n=== Startup Alpha Analysis ===")
    result = engine.analyze_startup("startup_a", days=7)
    print(f"Total allocated: {result['total_allocated']}")
    print(f"Summary: {result['summary']}")
    print("\nWorkspace breakdown:")
    for ws in result["workspaces"]:
        icon = "✅" if ws["status"] == "keep" else ("⚠️" if ws["status"] == "borderline" else "🔴")
        print(f"  {icon} {ws['label']:20s} {ws['utilization_pct']:6s} | {ws['avg_daily_hours']:.1f} hrs/day | {ws['reason']}")

    print("\n=== Recommendation for Startup Beta (needs 5 spaces) ===")
    rec = engine.recommend_assignment("startup_b", spaces_needed=5)
    print(f"Match: {rec['match_status']} | Found: {rec['spaces_found']}/{rec['spaces_needed']}")
    for ws in rec["recommendation"]:
        print(f"  → {ws['label']} ({ws['utilization_pct']})")

    print("\n=== Assignment Letter ===")
    print(engine.generate_assignment_letter(rec))
