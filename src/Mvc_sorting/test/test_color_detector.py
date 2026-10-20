"""Unit tests for colour detection, filtering and tracking."""

import cv2
from Mvc_sorting.color_detector import ColorDetector
from Mvc_sorting.hsv_config import HSVConfig
import numpy as np


def blank_frame() -> np.ndarray:
    """Return a dark 480x640 BGR frame."""
    return np.full((480, 640, 3), 35, dtype=np.uint8)


def test_detects_four_colours():
    """One circle per colour yields four detections with known centres."""
    frame = blank_frame()
    expected = {
        'red': (100, 100),
        'green': (250, 100),
        'blue': (400, 100),
        'yellow': (550, 100),
    }
    colours = {
        'red': (0, 0, 255),
        'green': (0, 255, 0),
        'blue': (255, 0, 0),
        'yellow': (0, 255, 255),
    }
    for name, centre in expected.items():
        cv2.circle(frame, centre, 30, colours[name], cv2.FILLED)

    detector = ColorDetector(HSVConfig.default(), enable_tracking=False)
    detections, masks = detector.detect(frame)

    assert len(detections) == 4
    assert {item.color for item in detections} == set(expected)
    for detection in detections:
        centre = expected[detection.color]
        assert abs(detection.x - centre[0]) < 1.5
        assert abs(detection.y - centre[1]) < 1.5
        assert detection.area > 2400
        assert 55 <= detection.bbox[2] <= 61
        assert 55 <= detection.bbox[3] <= 61
    assert set(masks) == set(expected)
    assert all(int(cv2.countNonZero(mask)) > 0 for mask in masks.values())


def test_small_speckles_are_filtered():
    """Noise specks below min_area do not become targets."""
    frame = blank_frame()
    rng = np.random.default_rng(3)
    for _ in range(40):
        centre = (int(rng.integers(0, 640)), int(rng.integers(0, 480)))
        cv2.circle(frame, centre, 2, (0, 0, 255), cv2.FILLED)

    detector = ColorDetector(HSVConfig.default(), enable_tracking=False)
    detections, _masks = detector.detect(frame)

    assert detections == []


def test_min_area_and_disabled_colour():
    """min_area and enabled flags are respected."""
    frame = blank_frame()
    cv2.circle(frame, (200, 240), 8, (0, 255, 0), cv2.FILLED)
    cv2.circle(frame, (400, 240), 30, (0, 0, 255), cv2.FILLED)

    config = HSVConfig.default()
    config.colors['red'].enabled = False
    detector = ColorDetector(config, enable_tracking=False)
    detections, _masks = detector.detect(frame)

    assert detections == []


def test_tracking_keeps_id_for_moving_blob():
    """The same blob keeps its ID after a small movement."""
    detector = ColorDetector(HSVConfig.default(), enable_tracking=True)
    first = blank_frame()
    cv2.circle(first, (200, 220), 28, (0, 255, 0), cv2.FILLED)
    second = blank_frame()
    cv2.circle(second, (208, 224), 28, (0, 255, 0), cv2.FILLED)

    first_detections, _ = detector.detect(first)
    second_detections, _ = detector.detect(second)

    assert len(first_detections) == 1
    assert len(second_detections) == 1
    assert first_detections[0].id == second_detections[0].id


def test_tracking_assigns_new_id_to_far_blob():
    """A blob farther than track_max_distance gets a new ID."""
    detector = ColorDetector(
        HSVConfig.default(), enable_tracking=True, track_max_distance=10.0)
    first = blank_frame()
    cv2.circle(first, (100, 240), 28, (255, 0, 0), cv2.FILLED)
    second = blank_frame()
    cv2.circle(second, (400, 240), 28, (255, 0, 0), cv2.FILLED)

    first_detections, _ = detector.detect(first)
    second_detections, _ = detector.detect(second)

    assert first_detections[0].id != second_detections[0].id


def test_red_hue_wrap_detects_high_hue():
    """Red hues near 179 are detected by the wrapped red threshold."""
    hsv = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(hsv, (320, 240), 30, (175, 255, 255), cv2.FILLED)
    frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    detector = ColorDetector(HSVConfig.default(), enable_tracking=False)
    detections, _masks = detector.detect(frame)

    assert len(detections) == 1
    assert detections[0].color == 'red'


def test_non_hsv_frame_is_converted():
    """A grayscale frame is accepted and produces no colour targets."""
    frame = np.full((240, 320), 120, dtype=np.uint8)
    detector = ColorDetector(HSVConfig.default(), enable_tracking=False)
    detections, _masks = detector.detect(frame)
    assert detections == []


def test_yellow_golden_hue_is_detected():
    """Golden/orange-yellow hues around 17 are still classified as yellow."""
    hsv = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(hsv, (200, 240), 30, (17, 180, 200), cv2.FILLED)
    frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    detector = ColorDetector(HSVConfig.default(), enable_tracking=False)
    detections, _masks = detector.detect(frame)

    assert len(detections) == 1
    assert detections[0].color == 'yellow'


def test_yellow_upper_hue_is_detected():
    """Yellow hues near the upper edge 37 are detected."""
    hsv = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(hsv, (320, 240), 30, (37, 180, 200), cv2.FILLED)
    frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    detector = ColorDetector(HSVConfig.default(), enable_tracking=False)
    detections, _masks = detector.detect(frame)

    assert len(detections) == 1
    assert detections[0].color == 'yellow'


def test_min_hits_requires_two_frames():
    """min_hits suppresses a target until it has been seen twice."""
    detector = ColorDetector(
        HSVConfig.default(), enable_tracking=True, min_hits=2)
    frame = blank_frame()
    cv2.circle(frame, (300, 240), 30, (0, 0, 255), cv2.FILLED)

    first_detections, _ = detector.detect(frame)
    second_detections, _ = detector.detect(frame)

    assert first_detections == []
    assert len(second_detections) == 1
    assert second_detections[0].color == 'red'
