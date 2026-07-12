"""
core/database.py  (v2 — Workspace Space Allocation Engine)

Schema:
  startups          — registered companies with allocated desk space counts
  workspaces        — permanent desk space definitions (replaces 'seats')
  occupancy_logs    — per-frame occupancy snapshots (ws_id, is_occupied)
  occupancy_sessions— session-level time records (start→end per workspace)

Database location: data/logs/occupancy.db

Key design decisions:
  - No "unknown" state — every workspace is either occupied (1) or vacant (0)
  - Sessions track contiguous blocks of occupancy for hours-per-day analytics
  - Workspaces are permanent definitions loaded from data/config/workspaces.json
  - The assignment engine queries workspace_stats() to compute utilization
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import random

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent.parent
DB_DIR        = BASE_DIR / "data" / "logs"
DB_PATH       = DB_DIR / "occupancy.db"
CONFIG_DIR    = BASE_DIR / "data" / "config"
WS_CONFIG     = CONFIG_DIR / "workspaces.json"
ST_CONFIG     = CONFIG_DIR / "startups.json"


def get_connection() -> sqlite3.Connection:
    """Return a thread-safe SQLite connection with row factory."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─── Schema ───────────────────────────────────────────────────────────────────

def init_db():
    """Create tables, load config files, seed historical data if empty."""
    conn = get_connection()
    cur  = conn.cursor()

    cur.executescript("""
        -- Startup registry
        CREATE TABLE IF NOT EXISTS startups (
            startup_id       TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            allocated_spaces INTEGER DEFAULT 0,
            contact_email    TEXT,
            contract_start   TEXT,
            contract_end     TEXT,
            color            TEXT DEFAULT '#4a9eff'
        );

        -- Workspace definitions (permanent desk spaces)
        CREATE TABLE IF NOT EXISTS workspaces (
            ws_id            TEXT PRIMARY KEY,
            label            TEXT NOT NULL,
            camera_id        TEXT NOT NULL,
            grid_row         INTEGER NOT NULL,
            grid_col         INTEGER NOT NULL,
            allocated_to     TEXT NOT NULL,
            allocation_start TEXT,
            allocation_end   TEXT,
            FOREIGN KEY (allocated_to) REFERENCES startups(startup_id)
        );

        -- Per-frame occupancy snapshots
        CREATE TABLE IF NOT EXISTS occupancy_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ws_id        TEXT NOT NULL,
            startup_id   TEXT NOT NULL,
            is_occupied  INTEGER NOT NULL CHECK(is_occupied IN (0,1)),
            recorded_at  TEXT NOT NULL,
            FOREIGN KEY (ws_id) REFERENCES workspaces(ws_id)
        );

        -- Session-level time records (contiguous occupancy blocks)
        CREATE TABLE IF NOT EXISTS occupancy_sessions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ws_id            TEXT NOT NULL,
            startup_id       TEXT NOT NULL,
            session_start    TEXT NOT NULL,
            session_end      TEXT,
            duration_minutes INTEGER DEFAULT 0,
            FOREIGN KEY (ws_id) REFERENCES workspaces(ws_id)
        );

        -- Indices for fast time-range queries
        CREATE INDEX IF NOT EXISTS idx_logs_ws_time
            ON occupancy_logs(ws_id, recorded_at);
        CREATE INDEX IF NOT EXISTS idx_logs_startup_time
            ON occupancy_logs(startup_id, recorded_at);
        CREATE INDEX IF NOT EXISTS idx_sessions_ws
            ON occupancy_sessions(ws_id, session_start);

        -- Chair occupancy count logs
        CREATE TABLE IF NOT EXISTS chair_occupancy_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            total        INTEGER,
            occupied     INTEGER,
            vacant       INTEGER,
            recorded_at  TEXT NOT NULL
        );

        -- Chair dwell sessions
        CREATE TABLE IF NOT EXISTS dwell_sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chair_index  INTEGER,
            start_time   TEXT,
            end_time     TEXT,
            duration_min INTEGER,
            recorded_at  TEXT
        );
    """)
    conn.commit()

    # Seed from config files if tables are empty
    existing_startups = cur.execute("SELECT COUNT(*) FROM startups").fetchone()[0]
    if existing_startups == 0:
        _seed_from_config(cur, conn)

    conn.close()
    print(f"[DB] Ready at: {DB_PATH}")
    print(f"[DB] Workspaces: {get_workspace_count()}")


def _seed_from_config(cur, conn):
    """Load workspaces.json and startups.json, then generate 7 days of historical data."""

    # ── Load startups ──────────────────────────────────────────────────────────
    if ST_CONFIG.exists():
        with open(ST_CONFIG) as f:
            st_data = json.load(f)
        for s in st_data["startups"]:
            cur.execute(
                """INSERT OR IGNORE INTO startups
                   (startup_id, name, allocated_spaces, contact_email,
                    contract_start, contract_end, color)
                   VALUES (?,?,?,?,?,?,?)""",
                (s["id"], s["name"], s["allocated_spaces"],
                 s.get("contact_email", ""), s.get("contract_start", ""),
                 s.get("contract_end", ""), s.get("color", "#4a9eff"))
            )
        print(f"[DB] Loaded {len(st_data['startups'])} startups from config.")
    else:
        # Fallback hardcoded seed
        cur.executemany(
            "INSERT OR IGNORE INTO startups (startup_id, name, allocated_spaces) VALUES (?,?,?)",
            [("startup_a", "Startup Alpha", 15), ("startup_b", "Startup Beta", 10)]
        )

    # ── Load workspaces ────────────────────────────────────────────────────────
    if WS_CONFIG.exists():
        with open(WS_CONFIG) as f:
            ws_data = json.load(f)
        workspaces = ws_data["workspaces"]
        for ws in workspaces:
            cur.execute(
                """INSERT OR IGNORE INTO workspaces
                   (ws_id, label, camera_id, grid_row, grid_col,
                    allocated_to, allocation_start, allocation_end)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ws["id"], ws["label"], ws["camera_id"],
                 ws["grid_row"], ws["grid_col"], ws["allocated_to"],
                 ws.get("allocation_start", ""), ws.get("allocation_end", ""))
            )
        print(f"[DB] Loaded {len(workspaces)} workspaces from config.")
    else:
        # Fallback: generate 15 workspaces manually
        workspaces = []
        for i in range(15):
            row, col = divmod(i, 5)
            ws = {
                "id": f"ws_{i+1:03d}", "label": f"Desk Space A{i+1}",
                "camera_id": "cam_floor2", "grid_row": row, "grid_col": col,
                "allocated_to": "startup_a"
            }
            workspaces.append(ws)
            cur.execute(
                """INSERT OR IGNORE INTO workspaces
                   (ws_id, label, camera_id, grid_row, grid_col, allocated_to)
                   VALUES (?,?,?,?,?,?)""",
                (ws["id"], ws["label"], ws["camera_id"],
                 ws["grid_row"], ws["grid_col"], ws["allocated_to"])
            )

    conn.commit()

    # ── Generate 7 days of synthetic historical data ───────────────────────────
    _generate_historical_data(cur, workspaces)
    conn.commit()
    print("[DB] Historical data seeded.")


def _generate_historical_data(cur, workspaces: list):
    """
    Generate 7 days of realistic hourly occupancy logs.

    Pattern:
      Workspaces consistently used (Startup A core team) vs
      underutilized workspaces (rarely used, reassignable)
    """
    now  = datetime.now()
    logs = []
    sessions = []

    total_ws = len(workspaces)
    core_limit = max(1, int(total_ws * 0.67))

    for day_offset in range(7, 0, -1):
        day = now - timedelta(days=day_offset)

        for hour in range(8, 20):   # 8am–8pm work hours
            dt = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            ts = dt.isoformat()

            for ws in workspaces:
                ws_id      = ws["id"]
                startup_id = ws.get("allocated_to", "startup_a")
                ws_num     = int(ws_id.split("_")[1])

                # Core team workspaces: heavily used
                if ws_num <= core_limit:
                    base = 0.88 if 9 <= hour <= 18 else 0.25
                else:
                    # Underutilized workspaces: rarely used
                    base = 0.15 if 9 <= hour <= 18 else 0.02

                # Friday drop-off
                if day.weekday() == 4:
                    base *= 0.55
                # Monday slow start
                if day.weekday() == 0 and hour < 10:
                    base *= 0.60

                is_occ = 1 if random.random() < base else 0
                logs.append((ws_id, startup_id, is_occ, ts))

    cur.executemany(
        "INSERT INTO occupancy_logs (ws_id, startup_id, is_occupied, recorded_at) VALUES (?,?,?,?)",
        logs
    )
    print(f"[DB] Generated {len(logs)} historical occupancy records.")

    # ── Generate chair count logs (hourly for 7 days) ──────────────────────
    chair_logs = []
    dwell_records = []
    
    for day_offset in range(7, 0, -1):
        day = now - timedelta(days=day_offset)
        for hour in range(8, 20):
            dt = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            ts = dt.isoformat()
            
            # Base pattern for occupied chairs (peak around 11am and 3pm)
            if 10 <= hour <= 12 or 14 <= hour <= 16:
                occupied = random.randint(6, 10)
            elif 12 < hour < 14:  # lunch dip
                occupied = random.randint(2, 5)
            else:
                occupied = random.randint(1, 4)
                
            total = 12
            # Drop-off on weekends or Friday afternoon
            if day.weekday() in (5, 6):
                occupied = random.randint(0, 1)
            elif day.weekday() == 4 and hour >= 16:
                occupied = max(0, occupied - 3)
                
            chair_logs.append((total, occupied, total - occupied, ts))
            
            # Occasionally generate dwell sessions for occupied chairs
            if occupied > 0 and random.random() < 0.35:
                num_sessions = random.randint(1, min(occupied, 3))
                for _ in range(num_sessions):
                    chair_idx = random.randint(0, 11)
                    duration = random.choice([20, 30, 45, 60, 90, 120, 180, 240])
                    start_dt = dt - timedelta(minutes=duration)
                    dwell_records.append((
                        chair_idx,
                        start_dt.isoformat(),
                        dt.isoformat(),
                        duration,
                        dt.isoformat()
                    ))

    cur.executemany(
        "INSERT INTO chair_occupancy_logs (total, occupied, vacant, recorded_at) VALUES (?,?,?,?)",
        chair_logs
    )
    print(f"[DB] Seeded {len(chair_logs)} historical chair occupancy count logs.")

    cur.executemany(
        """INSERT INTO dwell_sessions 
           (chair_index, start_time, end_time, duration_min, recorded_at)
           VALUES (?,?,?,?,?)""",
        dwell_records
    )
    print(f"[DB] Seeded {len(dwell_records)} historical chair dwell sessions.")



# ─── Write Operations ──────────────────────────────────────────────────────────

def log_occupancy_batch(states: dict[str, bool], workspace_map: dict[str, str]):
    """
    Persist a batch of workspace occupancy states.

    Args:
        states:        {ws_id: is_occupied (bool)}
        workspace_map: {ws_id: startup_id}
    """
    if not states:
        return
    conn  = get_connection()
    cur   = conn.cursor()
    ts    = datetime.now().isoformat()
    rows  = [
        (ws_id, workspace_map.get(ws_id, "unknown"), int(occupied), ts)
        for ws_id, occupied in states.items()
    ]
    cur.executemany(
        "INSERT INTO occupancy_logs (ws_id, startup_id, is_occupied, recorded_at) VALUES (?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def log_session(ws_id: str, startup_id: str, session_start: str,
                session_end: str, duration_minutes: int):
    """Write a completed occupancy session (start → end block) to the DB."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO occupancy_sessions
           (ws_id, startup_id, session_start, session_end, duration_minutes)
           VALUES (?,?,?,?,?)""",
        (ws_id, startup_id, session_start, session_end, duration_minutes)
    )
    conn.commit()
    conn.close()


def update_workspace_allocation(ws_id: str, new_startup_id: str):
    """Reassign a workspace to a different startup (used after confirming recommendation)."""
    conn = get_connection()
    conn.execute(
        "UPDATE workspaces SET allocated_to = ? WHERE ws_id = ?",
        (new_startup_id, ws_id)
    )
    conn.commit()
    conn.close()
    print(f"[DB] Workspace {ws_id} reassigned to {new_startup_id}")


# ─── Read Operations ───────────────────────────────────────────────────────────

def get_all_workspaces() -> list[dict]:
    """Return all workspace definitions with startup name joined."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT w.*, s.name as startup_name
        FROM workspaces w
        LEFT JOIN startups s ON w.allocated_to = s.startup_id
        ORDER BY w.ws_id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_workspace_count() -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
    conn.close()
    return n


def get_all_startups() -> list[dict]:
    """Return all startup records."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM startups").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_workspace_map() -> dict[str, str]:
    """Return {ws_id: startup_id} mapping for all workspaces."""
    wss = get_all_workspaces()
    return {ws["ws_id"]: ws["allocated_to"] for ws in wss}


def get_startup_workspaces(startup_id: str) -> list[dict]:
    """Return all workspaces allocated to a specific startup."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM workspaces WHERE allocated_to = ? ORDER BY ws_id",
        (startup_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_workspace_stats(ws_id: str, days: int = 7) -> dict:
    """
    Return aggregated occupancy stats for a single workspace over N days.

    Returns:
        {
          "occupied_minutes":         int,   # total minutes occupied in work hours
          "peak_hour_utilization":    float, # avg occupancy 9–18h
          "consecutive_vacant_days":  int,
          "avg_daily_hours":          float,
          "utilization_rate":         float  # occupied / total available work hours
        }
    """
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn  = get_connection()

    # Total occupancy rate over all logs
    row = conn.execute("""
        SELECT AVG(CAST(is_occupied AS REAL)) as avg_occ,
               SUM(is_occupied) as occupied_count,
               COUNT(*) as total_count
        FROM occupancy_logs
        WHERE ws_id = ? AND recorded_at >= ?
    """, (ws_id, since)).fetchone()

    avg_occ        = row["avg_occ"] or 0.0
    occupied_count = row["occupied_count"] or 0

    # Assume each log record represents ~1 minute sample interval
    occupied_minutes = occupied_count * 1

    # Peak hour utilization (9am–6pm)
    peak_row = conn.execute("""
        SELECT AVG(CAST(is_occupied AS REAL)) as peak_avg
        FROM occupancy_logs
        WHERE ws_id = ?
          AND recorded_at >= ?
          AND CAST(strftime('%H', recorded_at) AS INTEGER) BETWEEN 9 AND 18
    """, (ws_id, since)).fetchone()
    peak_util = peak_row["peak_avg"] or 0.0

    # Consecutive vacant days (most recent streak of days with avg < 25%)
    day_rows = conn.execute("""
        SELECT date(recorded_at) as day,
               AVG(CAST(is_occupied AS REAL)) as avg_occ
        FROM occupancy_logs
        WHERE ws_id = ?
        GROUP BY day
        ORDER BY day DESC
        LIMIT 14
    """, (ws_id,)).fetchall()

    consecutive_vacant = 0
    for dr in day_rows:
        if (dr["avg_occ"] or 0) < 0.25:
            consecutive_vacant += 1
        else:
            break

    # Avg daily hours  (work hours = 8h/day → 480 min/day)
    total_work_minutes = days * 8 * 60
    avg_daily_hours    = (occupied_minutes / days / 60) if days > 0 else 0.0
    utilization_rate   = (occupied_minutes / total_work_minutes) if total_work_minutes > 0 else 0.0

    conn.close()
    return {
        "occupied_minutes":        occupied_minutes,
        "peak_hour_utilization":   round(peak_util, 3),
        "consecutive_vacant_days": consecutive_vacant,
        "avg_daily_hours":         round(avg_daily_hours, 2),
        "utilization_rate":        round(utilization_rate, 3),
    }


def get_all_workspace_utilizations(days: int = 7) -> list[dict]:
    """
    Return utilization stats for every workspace — used by assignment engine
    and the Analytics tab table.
    """
    workspaces = get_all_workspaces()
    results    = []
    for ws in workspaces:
        stats = get_workspace_stats(ws["ws_id"], days)
        results.append({
            **ws,
            **stats,
        })
    return results


def get_startup_efficiency(days: int = 7) -> list[dict]:
    """Return per-startup space efficiency summary."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn  = get_connection()
    rows  = conn.execute("""
        SELECT o.startup_id, s.name, s.allocated_spaces,
               AVG(CAST(o.is_occupied AS REAL)) as avg_occ,
               COUNT(DISTINCT o.ws_id) as active_ws
        FROM occupancy_logs o
        JOIN startups s ON o.startup_id = s.startup_id
        WHERE o.recorded_at >= ?
        GROUP BY o.startup_id
    """, (since,)).fetchall()
    conn.close()

    result = []
    for r in rows:
        avg  = r["avg_occ"] or 0.0
        eff  = round(avg * r["active_ws"], 1)
        result.append({
            "startup":         r["name"],
            "startup_id":      r["startup_id"],
            "allocated":       r["allocated_spaces"],
            "avg_used":        eff,
            "score":           round(avg, 3),
            "utilization_pct": f"{avg * 100:.1f}%",
        })
    return result


def get_hourly_avg_occupancy(days: int = 7) -> list[dict]:
    """Return average occupancy per hour of the day."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn  = get_connection()
    rows  = conn.execute("""
        SELECT CAST(strftime('%H', recorded_at) AS INTEGER) as hour,
               AVG(CAST(is_occupied AS REAL)) as avg_occ
        FROM occupancy_logs
        WHERE recorded_at >= ?
        GROUP BY hour
        ORDER BY hour
    """, (since,)).fetchall()
    conn.close()
    return [{"hour": r["hour"], "avg_occupancy": round(r["avg_occ"] or 0, 3)} for r in rows]


def get_day_of_week_avg(days: int = 30) -> list[dict]:
    """Return average occupancy per day of the week."""
    since    = (datetime.now() - timedelta(days=days)).isoformat()
    day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    conn     = get_connection()
    rows     = conn.execute("""
        SELECT CAST(strftime('%w', recorded_at) AS INTEGER) as dow,
               AVG(CAST(is_occupied AS REAL)) as avg_occ
        FROM occupancy_logs
        WHERE recorded_at >= ?
        GROUP BY dow
        ORDER BY dow
    """, (since,)).fetchall()
    conn.close()
    return [{"day": day_names[r["dow"]], "avg_occupancy": round(r["avg_occ"] or 0, 3)} for r in rows]


def get_all_reassignable_spaces(days: int = 7,
                                 util_threshold: float = 0.50,
                                 peak_threshold: float = 0.60) -> list[dict]:
    """
    Return all workspaces whose utilization is below util_threshold
    AND peak utilization is below peak_threshold.
    Used by the assignment engine's recommend_assignment() method.
    """
    all_utils = get_all_workspace_utilizations(days=days)
    return [
        ws for ws in all_utils
        if ws["utilization_rate"] < util_threshold
        and ws["peak_hour_utilization"] < peak_threshold
    ]


def log_chair_counts(counts: dict):
    conn = get_connection()
    ts = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO chair_occupancy_logs (total, occupied, vacant, recorded_at) VALUES (?,?,?,?)",
        (counts["total"], counts["occupied"], counts["vacant"], ts)
    )
    conn.commit()
    conn.close()


def get_chair_history(days: int = 7) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_connection()
    rows = conn.execute("""
        SELECT CAST(strftime('%H', recorded_at) AS INTEGER) as hour,
               AVG(occupied) as avg_occupied,
               AVG(total) as avg_total
        FROM chair_occupancy_logs
        WHERE recorded_at >= ?
        GROUP BY hour
        ORDER BY hour
    """, (since,)).fetchall()
    conn.close()
    return [{"hour": r["hour"], "avg_occupied": round(r["avg_occupied"] or 0, 1), "avg_total": round(r["avg_total"] or 0, 1)} for r in rows]


def get_dwell_stats() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT chair_index,
               AVG(duration_min) as avg_duration,
               COUNT(*) as total_sessions
        FROM dwell_sessions
        GROUP BY chair_index
        ORDER BY chair_index
    """).fetchall()
    conn.close()
    return [{"chair_index": r["chair_index"], "avg_duration_min": round(r["avg_duration"] or 0, 1), "total_sessions": r["total_sessions"]} for r in rows]


def get_startup_utilization() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.startup_id, s.name, s.allocated_spaces,
               AVG(CAST(o.is_occupied AS REAL)) as avg_occ
        FROM startups s
        LEFT JOIN occupancy_logs o ON s.startup_id = o.startup_id
        GROUP BY s.startup_id
    """).fetchall()
    conn.close()
    
    result = []
    for r in rows:
        allocated = r["allocated_spaces"] or 0
        avg_occ = r["avg_occ"] or 0.0
        actual_used = round(avg_occ * allocated, 1)
        util_pct = round(avg_occ * 100, 1)
        
        # Renewal recommendation based on utilization
        if util_pct >= 70.0:
            rec = "Renew Contract (High Utilization)"
        elif util_pct >= 40.0:
            rec = "Renew with Downsize Option"
        else:
            rec = "Reduce Allocated Spaces / Do Not Renew"
            
        result.append({
            "startup_id": r["startup_id"],
            "name": r["name"],
            "contracted": allocated,
            "actual_used": actual_used,
            "utilization_pct": f"{util_pct}%",
            "recommendation": rec
        })
def add_startup(name: str, allocated: int) -> dict:
    """Add a new startup, register workspaces, and seed recent occupancy logs."""
    import time
    import random
    from datetime import datetime, timedelta
    
    conn = get_connection()
    cur = conn.cursor()
    
    # Generate unique ID
    startup_id = name.lower().replace(" ", "_")
    exists = cur.execute("SELECT 1 FROM startups WHERE startup_id = ?", (startup_id,)).fetchone()
    if exists:
        startup_id = f"{startup_id}_{int(time.time())}"
        
    cur.execute(
        "INSERT INTO startups (startup_id, name, allocated_spaces) VALUES (?,?,?)",
        (startup_id, name, allocated)
    )
    
    # Create mock workspaces for this startup
    for i in range(allocated):
        ws_id = f"ws_{startup_id}_{i+1}"
        cur.execute(
            """INSERT OR IGNORE INTO workspaces 
               (ws_id, label, camera_id, grid_row, grid_col, allocated_to)
               VALUES (?,?,'cam_floor2',0,0,?)""",
            (ws_id, f"Desk Space {name} #{i+1}", startup_id)
        )
        
        # Seed mock occupancy logs over the last 24 hours
        occ_rate = random.uniform(0.15, 0.85)
        now = datetime.now()
        for hour_offset in range(24):
            log_time = now - timedelta(hours=hour_offset)
            is_occ = 1 if random.random() < occ_rate else 0
            cur.execute(
                """INSERT INTO occupancy_logs (ws_id, startup_id, is_occupied, recorded_at)
                   VALUES (?,?,?,?)""",
                (ws_id, startup_id, is_occ, log_time.isoformat())
            )
            
    conn.commit()
    conn.close()
    return {"startup_id": startup_id, "name": name, "allocated_spaces": allocated}


if __name__ == "__main__":
    init_db()
    print("\n--- Startup list ---")
    for s in get_all_startups():
        print(f"  {s['startup_id']}: {s['name']} ({s['allocated_spaces']} spaces)")

    print("\n--- Workspace sample (first 3) ---")
    for w in get_all_workspaces()[:3]:
        print(f"  {w['ws_id']}: {w['label']} → {w['startup_name']}")

    print("\n--- Workspace stats sample (ws_001) ---")
    stats = get_workspace_stats("ws_001", days=7)
    print(f"  {stats}")

    print("\n--- Startup efficiency ---")
    for e in get_startup_efficiency():
        print(f"  {e['startup']}: {e['avg_used']}/{e['allocated']} | score={e['score']}")
