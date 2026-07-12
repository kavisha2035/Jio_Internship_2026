# OccuSense AI — Workplace Yield Management & Capacity Analytics

OccuSense AI is a premium, enterprise-grade workplace capacity planning and yield management system powered by AI Computer Vision. Built specifically for co-working environments (like Jio Workspaces), it monitors seat utilization, tracks continuous desk usage, and translates raw visual presence logs into actionable business leasing decisions.

---

## 💡 Executive Product Pitch (Reframing the Project)
*Instead of just a seat occupancy counter, OccuSense AI is a **Yield Management & Product Enablement Platform**.*

### The Real Business Challenges We Solve:
1. **Contract vs. Reality Mismatch**: Co-working operators (like Jio) sell space allocations based on customer self-estimates. If a startup pays for 15 seats but consistently uses only 8, they suffer wasteful expenditure, and Jio loses desk capacity. OccuSense AI provides the usage logs to rightsize contracts to standard allocations at renewal.
2. **Next-Generation Pricing Models (Flex / Hot-Desking)**: Operators currently offer rigid fixed seat packages. OccuSense AI creates the empirical presence logs required to securely price and sell flexible capacity packages (e.g., *"Pay for 10 guaranteed desks + 5 flexible desk accesses"*).
3. **Floor Capacity Optimization (Yield Management)**: Just like airlines and hotels, co-working operators can use historical peak demand metrics (e.g., peak usage never exceeds 70% on a 100-desk floor) to safely oversell desk contracts, design premium lounge areas, or downsize lease sizes.

### Data-to-Decision Mapping:
| What We Detect | Business Decision It Enables |
| :--- | :--- |
| **Startup A uses 10/15 desks daily on average** | **Rightsize Renewals**: Offer a 10-seat package at renewal, saving them money and freeing up desks for new customers. |
| **Peak usage across a 100-seat floor is 70 seats** | **Yield Management**: Safely onboard 2 more startups without expanding physical desk count (overselling). |
| **Startup B uses 100% of allocated desks daily** | **Expansion Upsell**: Proactively pitch a larger dedicated office space. |
| **Floor occupancy drops below 5% every Friday** | **Operational Savings**: Close the wing early, shut down HVAC units, and turn off lighting. |
| **Daily occupancy peaks between 10:00 AM & 2:00 PM** | **Maintenance Planning**: Schedule floor cleaning and device maintenance outside of peak hours. |

---

## 🛠️ System Architecture & Stack

OccuSense AI is divided into three key layers:
1. **AI Computer Vision Engine**: Deploys lightweight YOLOv8 networks, aspect-ratio posture classifiers, and spatial filters running entirely on edge streams.
2. **FastAPI Backend Server**: Exposes REST API endpoints and a low-latency WebSocket broadcaster connected to an SQLite database.
3. **Vite + React Dashboard**: A modern, premium corporate web interface showing real-time streams, pulsing status lists, and SVG analytics reports.

### The Stack:
* **Frontend**: React 18, Vite, WebSockets, Vanilla CSS (Premium corporate light theme design).
* **Backend**: FastAPI, Uvicorn, Python 3.10.
* **Database**: SQLite3.
* **CV & ML**: OpenCV, PyTorch, YOLOv8 (nano).

---

## 🧠 Advanced Computer Vision Algorithms

OccuSense AI incorporates custom algorithms to solve real-world computer vision edge-cases:

* **🚶‍♂️ Aisle Traffic Filtering (Y-Coordinate Perspective Gate)**: Tracks feet coordinates relative to chair bases. Pedestrians walking down workspace aisles are automatically identified as "transit" and excluded from occupancy triggers.
* **🔄 Asymmetric Posture Hysteresis**: Prevents state flickering (vacant/occupied shifting) when employees stretch, lean, or shift positions. Transitioning a seat to **Occupied** requires 3 consecutive positive frames (~0.5s), while releasing a seat to **Vacant** requires 15 consecutive empty frames (~2.5s).
* **📐 Perspective Projection Scaling**: Overhead camera frames compress background details. The matching distance gate scales dynamically based on the chair's bounding box width, preventing background actors from claiming foreground desks.
* **📦 Total Chair Count Smoother**: Applies a rolling queue max filter over the last 30 frames to stabilize total desk counts on the dashboard, preventing counts from fluctuating when passersby temporarily block empty chairs.
* **🔒 GDPR & Privacy Compliant (Volatile Zero-PI Pipeline)**: Visual frames process in local volatile RAM and are instantly discarded. Only anonymous seat numbers and occupancy percentages are logged to the database. Facial images are never stored.

---

## 📊 Database Schema

OccuSense AI utilizes a SQLite database with the following tables:
* **`startups`**: Registers tenant names and contracted desk counts.
* **`chair_occupancy_logs`**: Logs historical seat count stats.
* **`dwell_sessions`**: Logs historical workspace durations, recording starting times, ending times, and elapsed minutes for every sitting session.

---

## 🔌 REST & WebSocket API Endpoints

### REST APIs:
* `GET /api/chairs/summary`: Returns the latest total, occupied, and vacant chair counts.
* `GET /api/chairs/history?days=N`: Returns average occupancy rate logs grouped hourly.
* `POST /api/startups`: Registers a new startup workspace contract.
* `GET /api/startups/utilization`: Aggregates contracted seats against actual desk usage, generating optimization percentages and renewal recommendations.
* `POST /api/heatmap/toggle`: Toggles the BGR color heatmap layer overlay on the live stream.

### WebSockets:
* `WS /ws/live?camera_id=N`: Broadcasters frame payloads:
  ```json
  {
    "type": "frame",
    "data": "data:image/jpeg;base64,...",
    "chairs": {
      "total": 5,
      "occupied": 2,
      "vacant": 3
    }
  }
  ```

---

## 🚀 Setup & Run Instructions

### 1. Prerequisites:
* Python 3.10+
* Node.js 18+

### 2. Install Python Dependencies:
```bash
pip install fastapi uvicorn opencv-python ultralytics numpy torch websockets
```

### 3. Build the React Frontend:
```bash
cd frontend
npm install
npm run build
cd ..
```
*Vite compiles the production bundle and outputs assets directly into the FastAPI `/static` directory.*

### 4. Run the Server:
```bash
python app.py
```
*The application starts at `http://localhost:8000`. Navigate to `http://localhost:8000/static/index.html` to open the web portal.*

### 5. Workspace Calibration (Optional):
To calibrate seat bounds on a new camera feed, run the calibration script:
```bash
python calibrate.py
```
*(Use left-click to define seat bounding boxes, press 'S' to save, and 'Q' to quit).*
