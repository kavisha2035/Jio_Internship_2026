import numpy as np

def get_chair_occupancy(chairs, sitting_persons, match_distance=120):
    """
    For each detected chair, check if a sitting person
    is within match_distance pixels.
    Returns per-chair states + summary counts.
    No IDs. No grid. Just counting.
    """
    results = []
    
    for i, chair in enumerate(chairs):
        chair_cx = (chair.x1 + chair.x2) // 2
        chair_cy = (chair.y1 + chair.y2) // 2
        
        is_occupied = False
        
        for person in sitting_persons:
            person_cx = (person.x1 + person.x2) // 2
            person_cy = person.y2  # bottom center = seat level
            
            # Perspective gate: if person is walking in the aisle in front of the chair,
            # their feet (person.y2) will be significantly lower in the frame than the chair bottom (chair.y2).
            chair_h = chair.y2 - chair.y1
            if person.y2 > chair.y2 + int(chair_h * 0.35):
                continue
                
            dist = ((chair_cx - person_cx)**2 + 
                    (chair_cy - person_cy)**2) ** 0.5
            
            # Dynamic matching distance based on chair size (handles perspective depth scaling)
            chair_w = chair.x2 - chair.x1
            allowed_dist = max(45, int(chair_w * 1.25))
            
            if dist < allowed_dist:
                is_occupied = True
                break
        
        results.append({
            "index":    i,
            "id":       getattr(chair, "chair_id", f"chair_{i}"),
            "cx":       chair_cx,
            "cy":       chair_cy,
            "state":    "occupied" if is_occupied else "vacant",
            "x1": chair.x1, "y1": chair.y1,
            "x2": chair.x2, "y2": chair.y2
        })
    
    total    = len(results)
    occupied = sum(1 for r in results if r["state"] == "occupied")
    
    return results, {
        "total":    total,
        "occupied": occupied,
        "vacant":   total - occupied
    }
