"""Unit tests for HSV configuration handling."""

from Mvc_sorting.hsv_config import ColorThreshold, HSVConfig
import pytest


def test_default_config_has_four_colours():
    """The default configuration contains the four supported colours."""
    config = HSVConfig.default()
    assert list(config.colors) == ['red', 'green', 'blue', 'yellow']
    assert all(threshold.enabled for threshold in config.colors.values())
    assert config.colors['red'].wrap_hue is True
    assert config.colors['yellow'].lower == (15, 80, 80)
    assert config.colors['yellow'].upper == (38, 255, 255)


def test_red_wrap_adds_high_hue_range():
    """Red threshold wraps around the OpenCV hue boundary."""
    threshold = ColorThreshold.from_dict(
        {'lower': [0, 120, 70], 'upper': [10, 255, 255], 'wrap_hue': True},
        'red')
    ranges = threshold.mask_ranges()
    assert ranges[0] == ((0, 120, 70), (10, 255, 255))
    assert ranges[1] == ((170, 120, 70), (179, 255, 255))


def test_json_round_trip(tmp_path):
    """A saved configuration loads back with identical values."""
    config = HSVConfig.default()
    config.min_area = 450
    config.colors['blue'].upper = (145, 250, 240)
    path = tmp_path / 'hsv.json'

    saved_path = config.save(str(path))
    loaded = HSVConfig.load(saved_path)

    assert loaded.min_area == 450
    assert loaded.colors['blue'].upper == (145, 250, 240)
    assert loaded.to_dict() == config.to_dict()


def test_partial_config_uses_defaults():
    """Missing sections and colours fall back to built-in defaults."""
    config = HSVConfig.from_dict({'filter': {'min_area': 50}})
    assert config.min_area == 50
    assert config.colors['green'].lower == (40, 80, 50)
    assert config.morph_kernel == 5


def test_invalid_threshold_rejected():
    """Out-of-range HSV values raise a descriptive ValueError."""
    with pytest.raises(ValueError, match='upper'):
        ColorThreshold.from_dict(
            {'lower': [0, 0, 0], 'upper': [200, 255, 255]}, 'bad')
    with pytest.raises(ValueError, match='greater than upper'):
        ColorThreshold.from_dict(
            {'lower': [20, 0, 0], 'upper': [10, 255, 255]}, 'bad')


def test_invalid_file_json_rejected(tmp_path):
    """Malformed JSON is reported as a configuration error."""
    path = tmp_path / 'broken.json'
    path.write_text('{not valid json', encoding='utf-8')
    with pytest.raises(ValueError, match='invalid JSON'):
        HSVConfig.load(str(path))


def test_validate_rechecks_mutated_threshold():
    """Programmatic threshold changes are validated before use."""
    config = HSVConfig.default()
    config.colors['red'].upper = (200, 255, 255)
    with pytest.raises(ValueError, match='upper'):
        config.validate()


def test_legacy_yellow_default_is_migrated():
    """A version-1 config using the old yellow range gets the new defaults."""
    data = HSVConfig.default().to_dict()
    data['version'] = 1
    data['colors']['yellow']['lower'] = [20, 100, 100]
    data['colors']['yellow']['upper'] = [35, 255, 255]

    loaded = HSVConfig.from_dict(data)

    assert loaded.colors['yellow'].lower == (15, 80, 80)
    assert loaded.colors['yellow'].upper == (38, 255, 255)


def test_custom_yellow_range_is_not_migrated():
    """User-customised yellow values survive the version-1 migration."""
    data = HSVConfig.default().to_dict()
    data['version'] = 1
    data['colors']['yellow']['lower'] = [18, 90, 90]
    data['colors']['yellow']['upper'] = [34, 240, 240]

    loaded = HSVConfig.from_dict(data)

    assert loaded.colors['yellow'].lower == (18, 90, 90)
    assert loaded.colors['yellow'].upper == (34, 240, 240)
