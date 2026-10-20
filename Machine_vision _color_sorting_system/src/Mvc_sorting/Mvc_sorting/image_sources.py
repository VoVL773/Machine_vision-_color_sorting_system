"""Synthetic camera frames for demos and headless integration tests."""

from __future__ import annotations

import math

import cv2
import numpy as np

SYNTHETIC_COLORS = {
    'red': (0, 0, 255),
    'green': (0, 255, 0),
    'blue': (255, 0, 0),
    'yellow': (0, 255, 255),
}


class SyntheticScene:
    """
    Generate a moving multi-colour scene without a camera.

    Four colours are provided with two blobs each, so the server publishes
    eight targets. Small speckles are added to exercise morphology filtering.
    """

    def __init__(self, width: int = 640, height: int = 480, seed: int = 7) -> None:
        """Create the scene with two blobs per colour."""
        if width < 320 or height < 240:
            raise ValueError('synthetic frame size must be at least 320x240')
        self.width = int(width)
        self.height = int(height)
        self._scale_x = self.width / 640.0
        self._scale_y = self.height / 480.0
        self._scale = min(self._scale_x, self._scale_y)
        self._rng = np.random.default_rng(seed)
        self._frame_index = 0
        self._blobs = self._make_blobs()

    def _make_blobs(self) -> list[dict]:
        """Lay out eight blobs with non-overlapping base positions."""
        layouts = [
            ('red', (110, 105), 30),
            ('red', (530, 105), 20),
            ('green', (110, 375), 20),
            ('green', (530, 375), 30),
            ('blue', (320, 105), 30),
            ('blue', (110, 240), 20),
            ('yellow', (320, 375), 20),
            ('yellow', (530, 240), 30),
        ]
        blobs = []
        for index, (color, (base_x, base_y), radius) in enumerate(layouts):
            blobs.append({
                'color': color,
                'base_x': int(round(base_x * self._scale_x)),
                'base_y': int(round(base_y * self._scale_y)),
                'radius': max(8, int(round(radius * self._scale))),
                'phase': index * 0.79,
            })
        return blobs

    def read(self) -> np.ndarray:
        """Return the next synthetic BGR frame."""
        self._frame_index += 1
        frame = self._background()

        for blob in self._blobs:
            phase = blob['phase']
            offset_x = int(
                22.0 * self._scale_x
                * math.sin(self._frame_index * 0.030 + phase))
            offset_y = int(
                12.0 * self._scale_y
                * math.cos(self._frame_index * 0.024 + phase * 1.7))
            center = (
                int(blob['base_x'] + offset_x),
                int(blob['base_y'] + offset_y),
            )
            color = SYNTHETIC_COLORS[blob['color']]
            radius = int(blob['radius'])
            cv2.circle(frame, center, radius + 2, (245, 245, 245),
                       cv2.FILLED, cv2.LINE_AA)
            cv2.circle(frame, center, radius, color, cv2.FILLED, cv2.LINE_AA)
            highlight = (center[0] - radius // 3, center[1] - radius // 3)
            cv2.circle(frame, highlight, max(3, radius // 5),
                       (255, 255, 255), cv2.FILLED, cv2.LINE_AA)

        self._draw_speckles(frame)
        cv2.putText(
            frame, f'SYNTHETIC #{self._frame_index}',
            (max(8, int(12 * self._scale)), self.height - max(10, int(16 * self._scale))),
            cv2.FONT_HERSHEY_SIMPLEX, max(0.4, 0.5 * self._scale),
            (180, 180, 180), max(1, int(self._scale)), cv2.LINE_AA)
        return frame

    def _background(self) -> np.ndarray:
        """Build a dark conveyor-like background with a subtle gradient."""
        ramp = np.linspace(26, 62, self.width, dtype=np.float32)
        frame = np.tile(ramp, (self.height, 1))
        frame = cv2.merge([frame * 0.85, frame, frame * 1.10])
        frame = np.clip(frame, 0, 255).astype(np.uint8)
        grid = max(40, int(80 * self._scale))
        for x in range(0, self.width, grid):
            cv2.line(frame, (x, 0), (x, self.height), (48, 48, 48), 1)
        for y in range(0, self.height, grid):
            cv2.line(frame, (0, y), (self.width, y), (48, 48, 48), 1)
        band_top = int(198 * self._scale_y)
        band_bottom = int(292 * self._scale_y)
        cv2.rectangle(
            frame, (0, band_top), (self.width, band_bottom),
            (58, 58, 58), cv2.FILLED)
        thickness = max(1, int(2 * self._scale))
        cv2.line(
            frame, (0, band_top), (self.width, band_top),
            (95, 95, 95), thickness)
        cv2.line(
            frame, (0, band_bottom - 2), (self.width, band_bottom - 2),
            (95, 95, 95), thickness)
        return frame

    def _draw_speckles(self, frame: np.ndarray) -> None:
        """Draw small colour speckles that must not survive area filtering."""
        count = max(30, int(70 * self._scale_x * self._scale_y))
        for _ in range(count):
            x = int(self._rng.integers(0, self.width))
            y = int(self._rng.integers(0, self.height))
            radius = max(1, int(self._rng.integers(1, 4) * self._scale))
            color = tuple(int(value) for value in self._rng.integers(0, 256, 3))
            cv2.circle(frame, (x, y), radius, color, cv2.FILLED)
