"""Colour blob detection, contour filtering and simple ID tracking."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Dict, List, Tuple

import cv2
import numpy as np

from .hsv_config import HSVConfig


@dataclass
class Detection:
    """One filtered colour blob in image coordinates."""

    id: int  # noqa: A003
    color: str
    x: float
    y: float
    area: float
    bbox: Tuple[int, int, int, int]  # x, y, width, height


@dataclass
class _Track:
    """Internal state for one tracked blob."""

    id: int  # noqa: A003
    color: str
    x: float
    y: float
    area: float
    last_seen: int
    hits: int


def _odd_kernel(size: int) -> int:
    """Return an odd morphology/blur kernel size, or 0 when disabled."""
    if size <= 1:
        return 0
    if size % 2 == 0:
        size += 1
    return size


class ColorDetector:
    """Detect coloured blobs and optionally keep stable IDs between frames."""

    def __init__(
        self,
        config: HSVConfig,
        enable_tracking: bool = True,
        track_max_distance: float = 80.0,
        track_max_age: int = 15,
        min_hits: int = 1,
    ) -> None:
        """Create a detector for the given configuration."""
        if not isinstance(config, HSVConfig):
            raise TypeError('config must be an HSVConfig instance')
        if track_max_distance < 0:
            raise ValueError('track_max_distance must be >= 0')
        if track_max_age < 0:
            raise ValueError('track_max_age must be >= 0')
        if min_hits < 1:
            raise ValueError('min_hits must be >= 1')
        self.config = config
        self.enable_tracking = bool(enable_tracking)
        self.track_max_distance = float(track_max_distance)
        self.track_max_age = int(track_max_age)
        self.min_hits = int(min_hits)
        self._tracks: Dict[int, _Track] = {}
        self._frame_number = 0
        self._next_id = 1

    def set_config(self, config: HSVConfig) -> None:
        """Replace the active threshold configuration."""
        if not isinstance(config, HSVConfig):
            raise TypeError('config must be an HSVConfig instance')
        self.config = config

    def reset_tracking(self) -> None:
        """Drop all track state and restart IDs at 1."""
        self._tracks.clear()
        self._frame_number = 0
        self._next_id = 1

    def detect(self, frame: np.ndarray) -> Tuple[List[Detection], Dict[str, np.ndarray]]:
        """
        Detect colour blobs in a BGR frame.

        Returns a list of detections and a dictionary containing one binary
        mask per configured colour (disabled colours get an empty mask).
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            raise ValueError('frame must be a non-empty numpy array')
        bgr = self._as_bgr(frame)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        blur_kernel = _odd_kernel(self.config.blur_kernel)
        if blur_kernel:
            hsv = cv2.GaussianBlur(hsv, (blur_kernel, blur_kernel), 0)

        masks: Dict[str, np.ndarray] = {}
        detections: List[Detection] = []
        for color_name, threshold in self.config.colors.items():
            if not threshold.enabled:
                masks[color_name] = np.zeros(bgr.shape[:2], dtype=np.uint8)
                continue
            mask = self._threshold_mask(hsv, threshold.mask_ranges())
            mask = self._clean_mask(mask)
            masks[color_name] = mask
            contours, _hierarchy = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                detection = self._contour_to_detection(contour, color_name)
                if detection is not None:
                    detections.append(detection)

        order = {name: index for index, name in enumerate(self.config.colors)}
        detections.sort(key=lambda item: (
            order.get(item.color, len(order)), item.color, item.x, item.y))

        if self.enable_tracking:
            self._update_tracks(detections)
            if self.min_hits > 1:
                detections = [
                    detection for detection in detections
                    if detection.id in self._tracks
                    and self._tracks[detection.id].hits >= self.min_hits]
        else:
            for index, detection in enumerate(detections, start=1):
                detection.id = index
        return detections, masks

    @staticmethod
    def _as_bgr(frame: np.ndarray) -> np.ndarray:
        """Convert supported frame layouts to 8-bit BGR."""
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        if frame.ndim == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if frame.ndim != 3:
            raise ValueError(f'unsupported frame shape: {frame.shape}')
        channels = frame.shape[2]
        if channels == 3:
            return frame
        if channels == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        raise ValueError(f'unsupported frame channel count: {channels}')

    @staticmethod
    def _threshold_mask(
        hsv: np.ndarray,
        ranges: List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]],
    ) -> np.ndarray:
        """Apply one or more inRange intervals and merge them with OR."""
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lower, upper in ranges:
            lower_array = np.array(lower, dtype=np.uint8)
            upper_array = np.array(upper, dtype=np.uint8)
            mask = cv2.bitwise_or(
                mask, cv2.inRange(hsv, lower_array, upper_array))
        return mask

    def _clean_mask(self, mask: np.ndarray) -> np.ndarray:
        """Remove speckles with open/close morphology."""
        kernel_size = _odd_kernel(self.config.morph_kernel)
        if not kernel_size or self.config.morph_iterations <= 0:
            return mask
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        cleaned = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, kernel,
            iterations=self.config.morph_iterations)
        cleaned = cv2.morphologyEx(
            cleaned, cv2.MORPH_CLOSE, kernel,
            iterations=self.config.morph_iterations)
        return cleaned

    def _contour_to_detection(
        self, contour: np.ndarray, color_name: str,
    ) -> Detection | None:
        """Filter one contour and convert it to a detection."""
        area = float(cv2.contourArea(contour))
        if area < self.config.min_area:
            return None
        if self.config.max_area and area > self.config.max_area:
            return None

        x, y, width, height = cv2.boundingRect(contour)
        if width < self.config.min_dimension or height < self.config.min_dimension:
            return None
        box_area = float(width * height)
        if box_area > 0 and area / box_area < self.config.min_fill_ratio:
            return None

        moments = cv2.moments(contour)
        if moments['m00'] > 0:
            center_x = moments['m10'] / moments['m00']
            center_y = moments['m01'] / moments['m00']
        else:
            center_x = x + width / 2.0
            center_y = y + height / 2.0
        return Detection(
            id=0,
            color=color_name,
            x=float(center_x),
            y=float(center_y),
            area=area,
            bbox=(int(x), int(y), int(width), int(height)),
        )

    def _update_tracks(self, detections: List[Detection]) -> None:
        """Assign stable IDs using greedy nearest-neighbour matching."""
        self._frame_number += 1
        active = {
            track_id: track for track_id, track in self._tracks.items()
            if self._frame_number - track.last_seen <= self.track_max_age
        }
        unmatched_tracks = set(active)

        for color_name in self.config.colors:
            color_detections = [
                detection for detection in detections
                if detection.color == color_name]
            if not color_detections:
                continue

            candidates = []
            for detection_index, detection in enumerate(color_detections):
                for track_id, track in active.items():
                    if track.color != color_name or track_id not in unmatched_tracks:
                        continue
                    distance = hypot(
                        detection.x - track.x, detection.y - track.y)
                    if distance <= self.track_max_distance:
                        candidates.append((distance, detection_index, track_id))
            candidates.sort(key=lambda item: (item[0], item[1], item[2]))

            matched_detections = set()
            matched_tracks = set()
            for _distance, detection_index, track_id in candidates:
                if detection_index in matched_detections or track_id in matched_tracks:
                    continue
                detection = color_detections[detection_index]
                track = active[track_id]
                detection.id = track_id
                track.x = detection.x
                track.y = detection.y
                track.area = detection.area
                track.last_seen = self._frame_number
                track.hits += 1
                matched_detections.add(detection_index)
                matched_tracks.add(track_id)
                unmatched_tracks.discard(track_id)

            for detection_index, detection in enumerate(color_detections):
                if detection_index in matched_detections:
                    continue
                track_id = self._next_id
                self._next_id += 1
                detection.id = track_id
                self._tracks[track_id] = _Track(
                    id=track_id,
                    color=color_name,
                    x=detection.x,
                    y=detection.y,
                    area=detection.area,
                    last_seen=self._frame_number,
                    hits=1,
                )

        self._tracks = {
            track_id: track for track_id, track in self._tracks.items()
            if self._frame_number - track.last_seen <= self.track_max_age
        }
