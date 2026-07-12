import cv2
import numpy as np

class OccupancyHeatmap:
    """
    Accumulates where sitting persons are detected over time.
    High heat near a chair = someone sitting there recently.
    Used as fallback when person is occluded.
    """
    
    def __init__(self, frame_w, frame_h, decay=0.97):
        self.heatmap = np.zeros((frame_h, frame_w), dtype=np.float32)
        self.decay   = decay
    
    def update(self, sitting_persons):
        # Decay existing heat
        self.heatmap *= self.decay
        
        # Add heat at each sitting person's position
        for person in sitting_persons:
            cx = (person.x1 + person.x2) // 2
            cy = person.y2  # bottom center
            cv2.circle(self.heatmap, (cx, cy), 
                      radius=70, color=3.0, thickness=-1)
    
    def get_chair_heat(self, chair, radius=50):
        """Check heat level at a specific chair position"""
        cx = (chair["cx"])
        cy = (chair["cy"])
        
        region = self.heatmap[
            max(0, cy-radius):cy+radius,
            max(0, cx-radius):cx+radius
        ]
        return float(np.mean(region)) if region.size > 0 else 0.0
    
    def is_occupied_by_heat(self, chair, threshold=1.5):
        """Fallback: was someone sitting here recently?"""
        return self.get_chair_heat(chair) > threshold
    
    def get_visualization(self, frame):
        """Colored heatmap overlay for dashboard toggle"""
        normalized = cv2.normalize(
            self.heatmap, None, 0, 255, cv2.NORM_MINMAX
        )
        colored = cv2.applyColorMap(
            normalized.astype(np.uint8), cv2.COLORMAP_JET
        )
        return cv2.addWeighted(frame, 0.55, colored, 0.45, 0)
