"""OpenCV Trackbar panel used to tune HSV thresholds live."""

from __future__ import annotations

from typing import Callable, Dict

import cv2

from .hsv_config import HSVConfig

COLOR_TRACKBAR = '颜色(0红1绿2蓝3黄)'
ENABLED_TRACKBAR = '启用(1开)'
WRAP_TRACKBAR = '红色环绕(1开)'
H_MIN_TRACKBAR = '色相最小'
H_MAX_TRACKBAR = '色相最大'
S_MIN_TRACKBAR = '饱和度最小'
S_MAX_TRACKBAR = '饱和度最大'
V_MIN_TRACKBAR = '亮度最小'
V_MAX_TRACKBAR = '亮度最大'
AREA_TRACKBAR = '最小面积/100'
MORPH_TRACKBAR = '形态学核(0关)'

TRACKBAR_HELP = (
    '滑块说明：颜色 0红/1绿/2蓝/3黄；启用 1开0关；红色环绕用于红色；'
    '最小面积 = 滑块值 x 100 平方像素；形态学核 0或1表示关闭。'
    '快捷键：s保存 l加载 r恢复默认 m掩码 h帮助 q退出。'
)


class HSVTrackbarPanel:
    """Create and synchronise HSV threshold Trackbars on an OpenCV window."""

    def __init__(
        self,
        window_name: str,
        config: HSVConfig,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        """Attach the panel to ``window_name`` and show the current config."""
        self.window_name = window_name
        self._config = config
        self._on_change = on_change
        self._color_names = list(config.colors)
        self._guard = False
        self._current_color_index = 0

        self._guard = True
        try:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            self._create_trackbars()
            self.sync_from_config()
        finally:
            self._guard = False

    @property
    def current_color_name(self) -> str:
        """Return the colour currently selected in the Trackbar panel."""
        if not self._color_names:
            return ''
        index = min(max(self._current_color_index, 0), len(self._color_names) - 1)
        return self._color_names[index]

    def _create_trackbars(self) -> None:
        """Create every Trackbar with its range and default position."""
        cv2.createTrackbar(
            COLOR_TRACKBAR, self.window_name, 0,
            max(0, len(self._color_names) - 1), self._on_trackbar)
        cv2.createTrackbar(
            ENABLED_TRACKBAR, self.window_name, 1, 1, self._on_trackbar)
        cv2.createTrackbar(
            WRAP_TRACKBAR, self.window_name, 0, 1, self._on_trackbar)
        cv2.createTrackbar(H_MIN_TRACKBAR, self.window_name, 0, 179, self._on_trackbar)
        cv2.createTrackbar(H_MAX_TRACKBAR, self.window_name, 10, 179, self._on_trackbar)
        cv2.createTrackbar(S_MIN_TRACKBAR, self.window_name, 0, 255, self._on_trackbar)
        cv2.createTrackbar(S_MAX_TRACKBAR, self.window_name, 255, 255, self._on_trackbar)
        cv2.createTrackbar(V_MIN_TRACKBAR, self.window_name, 0, 255, self._on_trackbar)
        cv2.createTrackbar(V_MAX_TRACKBAR, self.window_name, 255, 255, self._on_trackbar)
        cv2.createTrackbar(
            AREA_TRACKBAR, self.window_name, 3, 1000, self._on_trackbar)
        cv2.createTrackbar(
            MORPH_TRACKBAR, self.window_name, 5, 31, self._on_trackbar)

    def sync_from_config(self, color_index: int | None = None) -> None:
        """Push the current configuration values into the Trackbars."""
        if not self._color_names:
            return
        if color_index is None:
            color_index = self._current_color_index
        color_index = min(max(color_index, 0), len(self._color_names) - 1)
        self._current_color_index = color_index
        threshold = self._config.colors[self._color_names[color_index]]

        previous_guard = self._guard
        self._guard = True
        try:
            cv2.setTrackbarPos(COLOR_TRACKBAR, self.window_name, color_index)
            cv2.setTrackbarPos(
                ENABLED_TRACKBAR, self.window_name, int(threshold.enabled))
            cv2.setTrackbarPos(
                WRAP_TRACKBAR, self.window_name, int(threshold.wrap_hue))
            positions: Dict[str, int] = {
                H_MIN_TRACKBAR: threshold.lower[0],
                H_MAX_TRACKBAR: threshold.upper[0],
                S_MIN_TRACKBAR: threshold.lower[1],
                S_MAX_TRACKBAR: threshold.upper[1],
                V_MIN_TRACKBAR: threshold.lower[2],
                V_MAX_TRACKBAR: threshold.upper[2],
                AREA_TRACKBAR: min(1000, max(0, self._config.min_area // 100)),
                MORPH_TRACKBAR: min(31, max(0, self._config.morph_kernel)),
            }
            for name, value in positions.items():
                cv2.setTrackbarPos(name, self.window_name, value)
        finally:
            self._guard = previous_guard

    def set_config(self, config: HSVConfig) -> None:
        """Switch the panel to a new configuration object."""
        self._config = config
        self._color_names = list(config.colors)
        cv2.setTrackbarMax(
            COLOR_TRACKBAR, self.window_name,
            max(0, len(self._color_names) - 1))
        self.sync_from_config(min(self._current_color_index,
                                  max(0, len(self._color_names) - 1)))

    def _on_trackbar(self, _value: int = 0) -> None:
        """Read all controls and update the configuration."""
        if self._guard or not self._color_names:
            return

        index = int(cv2.getTrackbarPos(COLOR_TRACKBAR, self.window_name))
        index = min(max(index, 0), len(self._color_names) - 1)
        if index != self._current_color_index:
            self._current_color_index = index
            self.sync_from_config(index)
            self._notify()
            return

        threshold = self._config.colors[self._color_names[index]]
        lower = [
            int(cv2.getTrackbarPos(H_MIN_TRACKBAR, self.window_name)),
            int(cv2.getTrackbarPos(S_MIN_TRACKBAR, self.window_name)),
            int(cv2.getTrackbarPos(V_MIN_TRACKBAR, self.window_name)),
        ]
        upper = [
            int(cv2.getTrackbarPos(H_MAX_TRACKBAR, self.window_name)),
            int(cv2.getTrackbarPos(S_MAX_TRACKBAR, self.window_name)),
            int(cv2.getTrackbarPos(V_MAX_TRACKBAR, self.window_name)),
        ]
        for channel in range(3):
            if lower[channel] > upper[channel]:
                upper[channel] = lower[channel]

        threshold.enabled = bool(
            cv2.getTrackbarPos(ENABLED_TRACKBAR, self.window_name))
        threshold.wrap_hue = bool(
            cv2.getTrackbarPos(WRAP_TRACKBAR, self.window_name))
        threshold.lower = (lower[0], lower[1], lower[2])
        threshold.upper = (upper[0], upper[1], upper[2])
        self._config.min_area = int(
            cv2.getTrackbarPos(AREA_TRACKBAR, self.window_name)) * 100
        self._config.morph_kernel = int(
            cv2.getTrackbarPos(MORPH_TRACKBAR, self.window_name))
        try:
            self._config.validate()
        except ValueError:
            return
        self.sync_from_config(index)
        self._notify()

    def _notify(self) -> None:
        """Invoke the optional change callback."""
        if self._on_change is not None:
            self._on_change()
