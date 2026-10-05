"""Low-light enhancement for detection (night / dusk / tunnel footage).

Detectors trained mostly on daylight images miss dark vehicle bodies at night:
the frame is dominated by a few bright headlights and street lamps. CLAHE
(contrast-limited adaptive histogram equalisation) on the lightness channel
lifts local contrast in dark regions while limiting noise amplification and
not blowing out the lights. It is applied to the detector's input only — the
annotated output keeps the original look.
"""

from __future__ import annotations

import cv2
import numpy as np

MODES = ("auto", "on", "off")


class LowLightEnhancer:
    def __init__(self, mode: str = "auto", dark_threshold: float = 70.0, clip_limit: float = 3.0,
                 tile_grid: int = 8, check_every: int = 15) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode
        self.dark_threshold = dark_threshold
        self.check_every = check_every
        self._clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_grid, tile_grid))
        self._frames = 0
        self._dark = False
        self.frames_enhanced = 0

    @staticmethod
    def brightness(image: np.ndarray) -> float:
        small = cv2.resize(image, (160, 90), interpolation=cv2.INTER_AREA)
        return float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())

    def is_dark(self, image: np.ndarray) -> bool:
        if self.mode != "auto":
            return self.mode == "on"
        if self._frames % self.check_every == 0:  # brightness changes slowly; check periodically
            self._dark = self.brightness(image) < self.dark_threshold
        return self._dark

    def __call__(self, image: np.ndarray) -> np.ndarray:
        dark = self.is_dark(image)
        self._frames += 1
        if not dark:
            return image
        self.frames_enhanced += 1
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        lab[..., 0] = self._clahe.apply(lab[..., 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
