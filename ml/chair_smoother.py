from collections import deque

class ChairCountSmoother:
    """
    Chairs disappear when person sits on them (occlusion).
    Rolling max of recent frame counts = stable total.
    """
    def __init__(self, window=30):
        self.history = deque(maxlen=window)
    
    def update(self, current_count):
        self.history.append(current_count)
        # True total = max seen recently
        # chairs only disappear due to occlusion, not reality
        return max(self.history) if self.history else current_count
