from statistics import mean
from typing import Dict, List


class LatencyTracker:
    """
    Tracks latency for different stages in the session.
    """

    def __init__(self) -> None:
        self._bucket: Dict[str, List[Dict[str, float]]] = {}

    def note(self, stage: str, start_t: float, end_t: float) -> None:
        self._bucket.setdefault(stage, []).append(
            {"start": start_t, "end": end_t, "dur": end_t - start_t}
        )

    def summary(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for stage, samples in self._bucket.items():
            durations = [s["dur"] for s in samples]
            out[stage] = {
                "count": len(durations),
                "avg": mean(durations) if durations else 0.0,
                "min": min(durations) if durations else 0.0,
                "max": max(durations) if durations else 0.0,
            }
        return out
