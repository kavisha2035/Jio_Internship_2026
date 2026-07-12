from datetime import datetime
import sqlite3

class DwellTimeTracker:
    """
    Tracks how long each chair has been continuously occupied.
    Logs sessions to DB when chair becomes vacant.
    """
    
    def __init__(self, db_path):
        self.db_path      = db_path
        self.session_start = {}   # chair_index → datetime
        self.current_state = {}   # chair_index → "occupied"/"vacant"
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dwell_sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                chair_index  INTEGER,
                start_time   TEXT,
                end_time     TEXT,
                duration_min INTEGER,
                recorded_at  TEXT
            )
        """)
        conn.commit()
        conn.close()
    
    def update(self, chair_results):
        now = datetime.now()
        
        for chair in chair_results:
            idx   = chair["index"]
            state = chair["state"]
            prev  = self.current_state.get(idx, "vacant")
            
            # Vacant → Occupied: start session
            if state == "occupied" and prev == "vacant":
                self.session_start[idx] = now
            
            # Occupied → Vacant: end session, log it
            if state == "vacant" and prev == "occupied":
                if idx in self.session_start:
                    duration = int(
                        (now - self.session_start[idx])
                        .total_seconds() / 60
                    )
                    if duration >= 1:  # ignore < 1 min
                        self._log(idx, self.session_start[idx], now, duration)
                    del self.session_start[idx]
            
            self.current_state[idx] = state
    
    def get_current_dwell(self):
        """How long has each currently occupied chair been in use?"""
        now = datetime.now()
        result = {}
        for idx, start in self.session_start.items():
            mins = int((now - start).total_seconds() / 60)
            result[idx] = f"{mins}m"
        return result
    
    def _log(self, idx, start, end, duration):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO dwell_sessions 
            (chair_index, start_time, end_time, duration_min, recorded_at)
            VALUES (?,?,?,?,?)
        """, (idx, start.isoformat(), end.isoformat(), 
              duration, datetime.now().isoformat()))
        conn.commit()
        conn.close()
