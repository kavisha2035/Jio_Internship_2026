import json
from pathlib import Path
from typing import Optional, Dict
from core.video_processor import VideoProcessor

class MultiCameraManager:
    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            self.config_path = Path(__file__).parent.parent / "data" / "config" / "camera_config.json"
        else:
            self.config_path = config_path

        self.processors: Dict[str, VideoProcessor] = {}
        self.camera_configs: list = []
        self._load_configs()

    def _load_configs(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                    self.camera_configs = data.get("cameras", [])
            else:
                self.camera_configs = [{
                    "id": "cam_floor2",
                    "label": "Floor 2 — Main Zone",
                    "floor": "Floor 2"
                }]
        except Exception as e:
            print(f"[MultiCameraManager] Load config error: {e}")
            self.camera_configs = [{
                "id": "cam_floor2",
                "label": "Floor 2 — Main Zone",
                "floor": "Floor 2"
            }]

    def start(self):
        print(f"[MultiCameraManager] Starting camera pipelines...")
        for cam in self.camera_configs:
            cam_id = cam["id"]
            if cam_id not in self.processors:
                print(f"[MultiCameraManager] Initializing pipeline for camera: {cam_id}")
                proc = VideoProcessor(camera_id=cam_id)
                self.processors[cam_id] = proc
                proc.start()

    def stop(self):
        print("[MultiCameraManager] Stopping camera pipelines...")
        for cam_id, proc in self.processors.items():
            proc.stop()
        self.processors.clear()

    def get_processor(self, camera_id: str) -> Optional[VideoProcessor]:
        return self.processors.get(camera_id)

    def get_all_processors(self) -> Dict[str, VideoProcessor]:
        return self.processors

# Global singleton
camera_manager = MultiCameraManager()
