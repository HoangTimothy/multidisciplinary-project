from __future__ import annotations

from collections import deque
from typing import Optional

from decision_engine import ScoredObstacle


class AlertSmoother:
    def __init__(
        self,
        *,
        hold_frames: int = 2,
        hold_seconds: float = 0.8,
    ) -> None:
        self.hold_frames = hold_frames
        self.hold_seconds = hold_seconds
        self._recent: deque[tuple[int, float, ScoredObstacle]] = deque(maxlen=max(hold_frames, 1))

    def reset(self) -> None:
        self._recent.clear()

    def update(
        self,
        alert: Optional[ScoredObstacle],
        *,
        frame_index: int,
        now_seconds: float,
    ) -> Optional[ScoredObstacle]:
        if alert is not None:
            self._recent.append((frame_index, now_seconds, alert))
            return alert

        fallback = self._fallback(frame_index=frame_index, now_seconds=now_seconds)
        return fallback

    def _fallback(self, *, frame_index: int, now_seconds: float) -> Optional[ScoredObstacle]:
        if not self._recent:
            return None
        last_frame_index, last_time, last_alert = self._recent[-1]
        if frame_index - last_frame_index > self.hold_frames:
            return None
        if now_seconds - last_time > self.hold_seconds:
            return None
        return last_alert
