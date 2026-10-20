"""Drawing helpers for the annotated camera view and colour masks."""

from __future__ import annotations

import math
import os
import sys
from typing import Dict, List

import cv2
import numpy as np

from .color_detector import Detection
from .hsv_config import HSVConfig

COLOR_BGR = {
    'red': (0, 0, 255),
    'green': (0, 255, 0),
    'blue': (255, 0, 0),
    'yellow': (0, 255, 255),
}


def bgr_for_color(name: str) -> tuple[int, int, int]:
    """Return a deterministic BGR draw colour for a class name."""
    known = COLOR_BGR.get(name.lower())
    if known is not None:
        return known
    hue = sum((index + 1) * ord(char) for index, char in enumerate(name)) % 180
    hsv = np.uint8([[[hue, 230, 255]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return (int(bgr[0]), int(bgr[1]), int(bgr[2]))


def gui_is_available() -> bool:
    """Return True when OpenCV highgui can plausibly open a window."""
    if os.environ.get('CV2_HEADLESS', '').lower() in ('1', 'true', 'yes', 'on'):
        return False
    if not hasattr(cv2, 'imshow') or not hasattr(cv2, 'namedWindow'):
        return False
    if sys.platform.startswith('linux'):
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            return False
    return True


def _put_label(
    image: np.ndarray,
    text: str,
    origin: tuple[int, int],
    color: tuple[int, int, int],
    scale: float = 0.45,
) -> None:
    """Draw text with a filled background for readability."""
    thickness = 1
    (text_width, text_height), baseline = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    x, y = origin
    max_x = max(0, image.shape[1] - text_width - 6)
    x = min(max(0, x), max_x)
    top = max(0, y - text_height - baseline - 4)
    bottom = top + text_height + baseline + 4
    right = x + text_width + 6
    cv2.rectangle(image, (x, top), (right, bottom), (0, 0, 0), cv2.FILLED)
    cv2.rectangle(image, (x, top), (right, bottom), color, 1)
    cv2.putText(
        image, text, (x + 3, bottom - baseline - 2),
        cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def annotate_frame(
    frame: np.ndarray,
    detections: List[Detection],
    config: HSVConfig,
    fps: float = 0.0,
    frame_index: int = 0,
    status: str = '',
) -> np.ndarray:
    """Return a copy of ``frame`` with boxes, centres, labels and a HUD."""
    annotated = frame.copy()
    for detection in detections:
        color = bgr_for_color(detection.color)
        x, y, width, height = detection.bbox
        cv2.rectangle(annotated, (x, y), (x + width, y + height), color, 2)

        center = (int(round(detection.x)), int(round(detection.y)))
        cv2.circle(annotated, center, 4, color, cv2.FILLED)
        cv2.circle(annotated, center, 8, (255, 255, 255), 1)
        cv2.line(annotated, (center[0] - 11, center[1]),
                 (center[0] + 11, center[1]), color, 1)
        cv2.line(annotated, (center[0], center[1] - 11),
                 (center[0], center[1] + 11), color, 1)

        label = f'{detection.color.upper()} #{detection.id}'
        label_y = y - 6 if y > 24 else y + height + 18
        _put_label(annotated, label, (x, label_y), color)

    header = (
        f'FPS {fps:5.1f} | targets {len(detections):2d} | '
        f'min_area {config.min_area} | morph {config.morph_kernel} | frame {frame_index}')
    if status:
        header = f'{header} | {status}'
    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (annotated.shape[1], 30), (0, 0, 0), cv2.FILLED)
    annotated = cv2.addWeighted(overlay, 0.65, annotated, 0.35, 0.0)
    cv2.putText(
        annotated, header, (8, 21), cv2.FONT_HERSHEY_SIMPLEX,
        0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return annotated


def make_mask_montage(
    masks: Dict[str, np.ndarray],
    config: HSVConfig,
    canvas_width: int = 640,
    canvas_height: int = 480,
) -> np.ndarray:
    """Build a labelled grid preview from the per-colour binary masks."""
    names = list(masks.keys())
    if not names:
        canvas = np.zeros((canvas_height, canvas_width, 3), dtype=np.uint8)
        cv2.putText(canvas, 'No colour masks', (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
        return canvas

    columns = 2 if len(names) > 1 else 1
    rows = int(math.ceil(len(names) / columns))
    tile_width = max(1, canvas_width // columns)
    tile_height = max(1, canvas_height // rows)
    canvas = np.zeros((tile_height * rows, tile_width * columns, 3),
                      dtype=np.uint8)

    for index, name in enumerate(names):
        mask = masks[name]
        if mask is None or mask.size == 0:
            mask = np.zeros((480, 640), dtype=np.uint8)
        color = bgr_for_color(name)
        color_layer = np.zeros((mask.shape[0], mask.shape[1], 3), dtype=np.uint8)
        color_layer[:] = color
        colored = cv2.bitwise_and(color_layer, color_layer, mask=mask)
        tile = cv2.resize(colored, (tile_width, tile_height),
                          interpolation=cv2.INTER_NEAREST)

        row = index // columns
        column = index % columns
        origin_x = column * tile_width
        origin_y = row * tile_height
        canvas[origin_y:origin_y + tile_height,
               origin_x:origin_x + tile_width] = tile
        cv2.rectangle(
            canvas, (origin_x + 1, origin_y + 1),
            (origin_x + tile_width - 2, origin_y + tile_height - 2),
            (80, 80, 80), 1)
        threshold = config.colors.get(name)
        detail = ''
        if threshold is not None:
            detail = f' H{threshold.lower[0]}-{threshold.upper[0]}'
        _put_label(
            canvas, f'{name.upper()} px={int(cv2.countNonZero(mask))}{detail}',
            (origin_x + 6, origin_y + 24), color, 0.42)
    return canvas


def sharpen_frame(frame: np.ndarray, amount: float) -> np.ndarray:
    """Apply a mild unsharp mask for the display/debug view only."""
    if amount <= 0.0:
        return frame
    blurred = cv2.GaussianBlur(frame, (0, 0), 1.2)
    return cv2.addWeighted(
        frame, 1.0 + amount, blurred, -amount, 0.0)
