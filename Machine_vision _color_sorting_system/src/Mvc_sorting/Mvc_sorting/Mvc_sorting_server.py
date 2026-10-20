"""
ROS 2 colour sorting vision server.

The node reads a camera, a video file, a ROS image topic or a synthetic scene,
detects red/green/blue/yellow blobs and publishes ColorTargetArray messages.
"""

from __future__ import annotations

import os
import sys
import time

from color_sorting_interfaces.msg import ColorTarget, ColorTargetArray
import cv2
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_srvs.srv import Trigger

from .color_detector import ColorDetector, Detection
from .gui import HSVTrackbarPanel, TRACKBAR_HELP
from .hsv_config import HSVConfig
from .image_sources import SyntheticScene
from .visualization import (
    annotate_frame,
    gui_is_available,
    make_mask_montage,
    sharpen_frame,
)

try:
    from cv_bridge import CvBridge
except ImportError:  # pragma: no cover - only when cv_bridge is not installed
    CvBridge = None

VALID_INPUT_TYPES = ('camera', 'video', 'topic', 'synthetic')


class MvcSortingServer(Node):
    """Vision server that publishes detected colour targets."""

    def __init__(self) -> None:
        """Declare parameters, open the input source and start processing."""
        super().__init__('Mvc_sorting_server')
        self._shutdown_requested = False
        self._shutdown_done = False
        self._frame_count = 0
        self._fps = 0.0
        self._last_frame_time = None
        self._last_log_time = 0.0
        self._consecutive_failures = 0
        self._config_changed_at = 0.0

        self._input_type = self._string_param('input_type', 'camera').lower()
        if self._input_type not in VALID_INPUT_TYPES:
            raise ValueError(
                f'input_type must be one of {VALID_INPUT_TYPES}, got {self._input_type!r}')
        self._camera_index = self._int_param('camera_index', 0)
        self._video_path = os.path.expanduser(self._string_param('video_path', ''))
        self._image_topic = self._string_param('image_topic', '/camera/image_raw')
        self._targets_topic = self._string_param('targets_topic', '/color_targets')
        self._debug_image_topic = self._string_param(
            'debug_image_topic', '/color_sorting/debug_image')
        self._frame_id = self._string_param('frame_id', 'camera_optical_frame')
        self._frame_width = max(1, self._int_param('frame_width', 1280))
        self._frame_height = max(1, self._int_param('frame_height', 720))
        self._fps_limit = max(1.0, self._float_param('fps', 30.0))
        self._camera_backend = self._string_param(
            'camera_backend', 'auto').strip().lower()
        if self._camera_backend not in ('auto', 'v4l2'):
            raise ValueError("camera_backend must be 'auto' or 'v4l2'")
        self._camera_fourcc = self._string_param(
            'camera_fourcc', '').strip().upper()
        self._camera_autofocus = self._bool_param('camera_autofocus', True)
        self._camera_focus = self._int_param('camera_focus', -1)
        self._camera_sharpness = self._int_param('camera_sharpness', -1)
        self._camera_warmup_frames = max(
            0, self._int_param('camera_warmup_frames', 5))
        self._display_sharpen = max(
            0.0, self._float_param('display_sharpen', 0.35))
        self._loop_video = self._bool_param('loop_video', False)
        self._max_frames = max(0, self._int_param('max_frames', 0))
        self._max_targets = max(0, self._int_param('max_targets', 20))
        self._publish_empty = self._bool_param('publish_empty', True)
        self._publish_debug_image = self._bool_param('publish_debug_image', False)
        self._print_targets = self._bool_param('print_targets', True)
        self._log_period = max(0.1, self._float_param('log_period', 1.0))
        self._auto_save = self._bool_param('auto_save', False)
        self._enable_tracking = self._bool_param('enable_tracking', True)
        self._track_max_distance = max(
            0.0, self._float_param('track_max_distance', 80.0))
        self._track_max_age = max(0, self._int_param('track_max_age', 15))
        self._min_hits = max(1, self._int_param('min_hits', 2))

        self._config_path, self._config = self._load_initial_config()
        min_area_override = self._int_param('initial_min_area', -1)
        morph_override = self._int_param('initial_morph_kernel', -1)
        if min_area_override >= 0:
            self._config.min_area = min_area_override
        if morph_override >= 0:
            self._config.morph_kernel = morph_override
        self._config.validate()

        self._detector = ColorDetector(
            self._config,
            enable_tracking=self._enable_tracking,
            track_max_distance=self._track_max_distance,
            track_max_age=self._track_max_age,
            min_hits=self._min_hits,
        )

        self._targets_publisher = self.create_publisher(
            ColorTargetArray, self._targets_topic, 10)

        self._bridge = None
        if self._publish_debug_image or self._input_type == 'topic':
            if CvBridge is None:
                if self._input_type == 'topic':
                    raise RuntimeError(
                        'input_type=topic requires cv_bridge (ros-jazzy-cv-bridge)')
                self.get_logger().warning(
                    'cv_bridge is not available; debug image publishing disabled')
                self._publish_debug_image = False
            else:
                self._bridge = CvBridge()

        self._debug_publisher = None
        if self._publish_debug_image:
            self._debug_publisher = self.create_publisher(
                Image, self._debug_image_topic, qos_profile_sensor_data)

        self._save_service = self.create_service(
            Trigger, '~/save_config', self._on_save_config)
        self._load_service = self.create_service(
            Trigger, '~/load_config', self._on_load_config)

        self._capture = None
        self._synthetic = None
        self._subscription = None
        self._timer = None
        if self._input_type == 'topic':
            self._subscription = self.create_subscription(
                Image, self._image_topic, self._on_image, qos_profile_sensor_data)
        else:
            self._open_input_source()
            self._timer = self.create_timer(1.0 / self._fps_limit, self._on_timer)

        self._window_name = 'Color Sorting'
        self._control_window_name = 'HSV Controls'
        self._mask_window_name = 'HSV Masks'
        self._gui_requested = self._bool_param('show_window', True)
        self._show_masks = self._bool_param('show_masks', True)
        self._show_trackbars = self._bool_param('show_trackbars', True)
        self._gui_enabled = self._gui_requested and gui_is_available()
        self._panel = None
        self._masks_visible = False
        self._mask_window_was_shown = False
        self._window_was_shown = False
        self._display_size = None
        if self._gui_requested and not self._gui_enabled:
            self.get_logger().warning(
                'show_window=True but no usable display was found; running headless')
        self._setup_gui()

        self.get_logger().info(
            f'vision server ready: input={self._input_type}, '
            f'targets={self._targets_topic}, config={self._config_path}, '
            f'gui={self._gui_enabled}, tracking={self._enable_tracking}, '
            f'min_hits={self._min_hits}')
        if self._input_type == 'synthetic':
            self.get_logger().info(
                'synthetic scene: 8 moving blobs (2 per colour), '
                f'{self._frame_width}x{self._frame_height}')
        if self._gui_enabled:
            self.get_logger().info(TRACKBAR_HELP)

    # ------------------------------------------------------------------ params
    def _string_param(self, name: str, default: str) -> str:
        """Declare and read a string parameter."""
        return str(self.declare_parameter(name, default).value)

    def _int_param(self, name: str, default: int) -> int:
        """Declare and read an integer parameter."""
        value = self.declare_parameter(name, default).value
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'parameter {name} must be an integer') from exc

    def _float_param(self, name: str, default: float) -> float:
        """Declare and read a floating point parameter."""
        value = self.declare_parameter(name, default).value
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'parameter {name} must be a number') from exc

    def _bool_param(self, name: str, default: bool) -> bool:
        """Declare and read a boolean parameter, accepting string values."""
        value = self.declare_parameter(name, default).value
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'on')
        return bool(value)

    # ------------------------------------------------------------------ config
    def _load_initial_config(self) -> tuple[str, HSVConfig]:
        """Resolve config_path and load or create the initial configuration."""
        default_path = os.path.expanduser('~/.ros/color_sorting_hsv.json')
        raw_path = self._string_param('config_path', '').strip()
        if raw_path:
            config_path = os.path.abspath(os.path.expanduser(raw_path))
            if not os.path.isfile(config_path):
                raise FileNotFoundError(
                    f'config_path does not exist: {config_path}')
            config = HSVConfig.load(config_path)
            self.get_logger().info(f'loaded HSV config: {config_path}')
            return config_path, config

        if os.path.isfile(default_path):
            config = HSVConfig.load(default_path)
            self.get_logger().info(f'loaded HSV config: {default_path}')
            return default_path, config
        return default_path, HSVConfig.default()

    def _apply_config(self, config: HSVConfig, reset_tracking: bool = True) -> None:
        """Apply a new configuration to the detector and GUI."""
        config.validate()
        self._config = config
        self._detector.set_config(config)
        if reset_tracking:
            self._detector.reset_tracking()
        if self._panel is not None:
            self._panel.set_config(config)

    def _save_config(self, quiet: bool = False) -> tuple[bool, str]:
        """Save the current configuration to ``config_path``."""
        if not self._config_path:
            return False, 'config_path is empty'
        try:
            saved_path = self._config.save(self._config_path)
        except (OSError, ValueError) as exc:
            message = f'failed to save HSV config: {exc}'
            if not quiet:
                self.get_logger().error(message)
            return False, message
        message = f'saved HSV config to {saved_path}'
        if not quiet:
            self.get_logger().info(message)
        return True, message

    def _load_config(self, quiet: bool = False) -> tuple[bool, str]:
        """Load the configuration from ``config_path``."""
        if not self._config_path:
            return False, 'config_path is empty'
        if not os.path.isfile(self._config_path):
            message = f'config file does not exist: {self._config_path}'
            if not quiet:
                self.get_logger().warning(message)
            return False, message
        try:
            config = HSVConfig.load(self._config_path)
        except (OSError, ValueError) as exc:
            message = f'failed to load HSV config: {exc}'
            if not quiet:
                self.get_logger().error(message)
            return False, message
        self._apply_config(config)
        message = f'loaded HSV config from {self._config_path}'
        if not quiet:
            self.get_logger().info(message)
        return True, message

    def _reset_config(self) -> None:
        """Restore the built-in default HSV configuration."""
        self._apply_config(HSVConfig.default())
        self.get_logger().info('restored default HSV configuration')

    def _on_save_config(self, _request, response):
        """Handle the ~/save_config Trigger service."""
        success, message = self._save_config()
        response.success = success
        response.message = message
        return response

    def _on_load_config(self, _request, response):
        """Handle the ~/load_config Trigger service."""
        success, message = self._load_config()
        response.success = success
        response.message = message
        return response

    # ------------------------------------------------------------------- input
    @staticmethod
    def _decode_fourcc(value: float) -> str:
        """Decode an OpenCV FOURCC numeric value into four ASCII characters."""
        code = int(value)
        characters = [chr((code >> (8 * index)) & 0xFF) for index in range(4)]
        return ''.join(char if 32 <= ord(char) < 127 else '.' for char in characters)

    def _set_camera_property(
        self, capture, prop: int, value, label: str, warn: bool = True,
    ) -> bool:
        """Set one camera property, optionally logging unsupported values."""
        try:
            accepted = bool(capture.set(prop, value))
        except cv2.error as exc:
            if warn:
                self.get_logger().warning(f'camera setting {label} failed: {exc}')
            return False
        if not accepted and warn:
            self.get_logger().warning(
                f'camera did not accept {label}={value}; keeping current value')
        return accepted

    def _try_camera(
        self,
        backend: str,
        width: int,
        height: int,
        fourcc_text: str,
        autofocus: bool,
        focus: int,
        sharpness: int,
    ):
        """
        Open and validate one camera configuration.

        Returns ``(capture, backend_label)`` on success or ``(None, reason)``.
        A frame is read before accepting the configuration so a broken
        GStreamer/V4L2 pipeline cannot be mistaken for a working camera.
        """
        if backend == 'v4l2' and sys.platform.startswith('linux'):
            capture = cv2.VideoCapture(self._camera_index, cv2.CAP_V4L2)
            backend_label = 'V4L2'
        else:
            capture = cv2.VideoCapture(self._camera_index)
            backend_label = 'auto'

        if not capture.isOpened():
            capture.release()
            return None, f'{backend_label} could not open camera {self._camera_index}'

        if fourcc_text:
            if len(fourcc_text) == 4:
                fourcc = cv2.VideoWriter_fourcc(*fourcc_text)
                self._set_camera_property(
                    capture, cv2.CAP_PROP_FOURCC, fourcc,
                    f'fourcc {fourcc_text}')
            else:
                self.get_logger().warning(
                    'camera_fourcc must contain exactly four characters; ignoring')

        self._set_camera_property(
            capture, cv2.CAP_PROP_FRAME_WIDTH, width, 'width', warn=False)
        self._set_camera_property(
            capture, cv2.CAP_PROP_FRAME_HEIGHT, height, 'height', warn=False)
        self._set_camera_property(
            capture, cv2.CAP_PROP_FPS, self._fps_limit, 'fps', warn=False)

        if focus >= 0:
            self._set_camera_property(
                capture, cv2.CAP_PROP_AUTOFOCUS, 0, 'autofocus')
            self._set_camera_property(
                capture, cv2.CAP_PROP_FOCUS, focus, 'focus')
        elif autofocus:
            self._set_camera_property(
                capture, cv2.CAP_PROP_AUTOFOCUS, 1, 'autofocus')

        if sharpness >= 0:
            self._set_camera_property(
                capture, cv2.CAP_PROP_SHARPNESS, sharpness, 'sharpness')

        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except cv2.error:
            pass

        attempts = max(1, self._camera_warmup_frames)
        successful_reads = 0
        for _ in range(attempts):
            try:
                ok, _frame = capture.read()
            except cv2.error as exc:
                capture.release()
                return None, f'{backend_label} read failed: {exc}'
            if ok:
                successful_reads += 1

        if successful_reads > 0:
            return capture, backend_label

        capture.release()
        return None, f'{backend_label} opened but returned no frames'

    def _log_opened_camera(self, capture, backend_label: str) -> None:
        """Log the actual resolution, FOURCC and focus values."""
        actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        actual_fps = capture.get(cv2.CAP_PROP_FPS)
        actual_fourcc = self._decode_fourcc(capture.get(cv2.CAP_PROP_FOURCC))
        focus = capture.get(cv2.CAP_PROP_FOCUS)
        fps_text = f'{actual_fps:.1f}' if actual_fps > 0.0 else 'unknown'
        self.get_logger().info(
            f'opened camera {self._camera_index} '
            f'({actual_width}x{actual_height} @ {fps_text} fps, '
            f'fourcc={actual_fourcc}, focus={focus:.0f}, backend={backend_label})')

    def _open_camera(self):
        """Open the camera with the requested settings and safe fallbacks."""
        preferred = 'auto'
        if sys.platform.startswith('linux') and self._camera_backend in ('auto', 'v4l2'):
            preferred = 'v4l2'

        capture, reason = self._try_camera(
            preferred,
            self._frame_width,
            self._frame_height,
            self._camera_fourcc,
            self._camera_autofocus,
            self._camera_focus,
            self._camera_sharpness,
        )
        if capture is not None:
            self._log_opened_camera(capture, reason)
            return capture

        self.get_logger().warning(
            f'{reason}; retrying camera with safe 640x480 defaults '
            '(no MJPG, no autofocus)')
        capture, safe_reason = self._try_camera(
            'auto', 640, 480, '', False, -1, -1)
        if capture is not None:
            self.get_logger().warning(
                'using safe camera fallback; set frame_width/frame_height/'
                'camera_fourcc explicitly if you need another mode')
            self._log_opened_camera(capture, safe_reason)
            return capture

        raise RuntimeError(
            f'camera {self._camera_index} could not provide frames: {safe_reason}; '
            'try another camera_index, close other camera applications, or use '
            'input_type:=topic/synthetic')

    def _open_input_source(self) -> None:
        """Open a camera, video file or synthetic scene."""
        if self._input_type == 'synthetic':
            self._synthetic = SyntheticScene(
                width=self._frame_width, height=self._frame_height)
            return
        if self._input_type == 'video':
            if not self._video_path:
                raise ValueError('input_type=video requires video_path')
            if not os.path.isfile(self._video_path):
                raise FileNotFoundError(
                    f'video_path does not exist: {self._video_path}')
            capture = cv2.VideoCapture(self._video_path)
            if not capture.isOpened():
                capture.release()
                raise RuntimeError(
                    f'could not open video: {self._video_path}')
            self._capture = capture
            actual_width = int(
                capture.get(cv2.CAP_PROP_FRAME_WIDTH) or self._frame_width)
            actual_height = int(
                capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or self._frame_height)
            self.get_logger().info(
                f'opened {self._video_path} ({actual_width}x{actual_height})')
            return

        self._capture = self._open_camera()

    def _read_frame(self):
        """Read the next frame, handling video loop and end of stream."""
        if self._synthetic is not None:
            return self._synthetic.read()
        if self._capture is None:
            return None
        ok, frame = self._capture.read()
        if ok:
            return frame
        if self._input_type == 'video' and self._loop_video:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._capture.read()
            if ok:
                return frame
        return None

    def _on_timer(self) -> None:
        """Capture and process one frame on a timer."""
        if self._shutdown_requested:
            return
        try:
            frame = self._read_frame()
        except cv2.error as exc:
            self.get_logger().error(f'frame capture failed: {exc}')
            frame = None
        if frame is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 10:
                self._request_shutdown('input stream ended or is unavailable')
            return
        self._consecutive_failures = 0
        self._process_frame(
            frame, self.get_clock().now().to_msg(), self._frame_id)

    def _on_image(self, message: Image) -> None:
        """Process a frame received from a ROS image topic."""
        if self._shutdown_requested:
            return
        if self._bridge is None:
            self._request_shutdown('cv_bridge is not available')
            return
        try:
            frame = self._bridge.imgmsg_to_cv2(message, desired_encoding='bgr8')
        except Exception as exc:  # cv_bridge raises various exceptions
            self.get_logger().error(
                f'failed to convert image: {exc}', throttle_duration_sec=5.0)
            return
        stamp = message.header.stamp
        if stamp.sec == 0 and stamp.nanosec == 0:
            stamp = self.get_clock().now().to_msg()
        frame_id = message.header.frame_id or self._frame_id
        self._process_frame(frame, stamp, frame_id)

    # --------------------------------------------------------------- processing
    def _process_frame(self, frame, stamp, frame_id: str) -> None:
        """Detect targets, publish messages and update the display."""
        try:
            detections, masks = self._detector.detect(frame)
        except (ValueError, cv2.error) as exc:
            self.get_logger().error(f'detection failed: {exc}')
            return

        self._frame_count += 1
        now = time.monotonic()
        if self._last_frame_time is not None:
            delta = now - self._last_frame_time
            if delta > 0.0:
                instantaneous = 1.0 / delta
                self._fps = (instantaneous if self._fps <= 0.0
                             else 0.9 * self._fps + 0.1 * instantaneous)
        self._last_frame_time = now

        if self._max_targets > 0:
            detections = detections[:self._max_targets]
        self._publish_targets(detections, stamp, frame_id)

        needs_image = self._publish_debug_image or self._gui_enabled
        annotated = None
        if needs_image:
            status_parts = []
            if self._panel is not None:
                status_parts.append(f'edit {self._panel.current_color_name}')
            if not self._enable_tracking:
                status_parts.append('tracking off')
            view_frame = sharpen_frame(frame, self._display_sharpen)
            annotated = annotate_frame(
                view_frame, detections, self._config, fps=self._fps,
                frame_index=self._frame_count, status=' | '.join(status_parts))

        if self._publish_debug_image and annotated is not None:
            self._publish_debug(annotated, stamp, frame_id)
        if self._gui_enabled and annotated is not None:
            self._show_frame(annotated, masks)

        if self._print_targets and now - self._last_log_time >= self._log_period:
            self._last_log_time = now
            self.get_logger().info(self._format_targets(detections))

        if self._max_frames > 0 and self._frame_count >= self._max_frames:
            self._request_shutdown(
                f'max_frames={self._max_frames} reached')

    @staticmethod
    def _format_targets(detections: list[Detection]) -> str:
        """Format a compact one-line target summary for logging."""
        if not detections:
            return 'no colour targets'
        parts = [
            f'{item.color}#{item.id}'
            f'({item.x:.0f},{item.y:.0f},a={item.area:.0f})'
            for item in detections[:12]
        ]
        suffix = '' if len(detections) <= 12 else f' ... (+{len(detections) - 12})'
        return f'{len(detections)} target(s): ' + ', '.join(parts) + suffix

    def _publish_targets(self, detections, stamp, frame_id: str) -> None:
        """Publish the target list as a ColorTargetArray message."""
        message = ColorTargetArray()
        message.header.stamp = stamp
        message.header.frame_id = frame_id
        for detection in detections:
            target = ColorTarget()
            target.id = int(detection.id)
            target.color = detection.color
            target.x = float(detection.x)
            target.y = float(detection.y)
            target.area = float(detection.area)
            message.targets.append(target)
        if self._publish_empty or message.targets:
            self._targets_publisher.publish(message)

    def _publish_debug(self, annotated, stamp, frame_id: str) -> None:
        """Publish the annotated frame on the optional debug image topic."""
        if self._debug_publisher is None or self._bridge is None:
            return
        try:
            image_message = self._bridge.cv2_to_imgmsg(annotated, encoding='bgr8')
        except Exception as exc:  # cv_bridge raises various exceptions
            self.get_logger().error(
                f'failed to convert debug image: {exc}', throttle_duration_sec=5.0)
            return
        image_message.header.stamp = stamp
        image_message.header.frame_id = frame_id
        self._debug_publisher.publish(image_message)

    # --------------------------------------------------------------------- GUI
    def _setup_gui(self) -> None:
        """Create the video, control and mask windows."""
        if not self._gui_enabled:
            return
        try:
            cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
            if self._show_trackbars:
                self._panel = HSVTrackbarPanel(
                    self._control_window_name, self._config,
                    self._on_config_changed)
            if self._show_masks:
                cv2.namedWindow(self._mask_window_name, cv2.WINDOW_NORMAL)
                self._masks_visible = True
        except cv2.error as exc:
            self.get_logger().warning(f'failed to create GUI windows: {exc}')
            self._disable_gui()

    def _on_config_changed(self) -> None:
        """Record live threshold edits from the Trackbar panel."""
        self._config_changed_at = time.monotonic()

    def _show_frame(self, annotated, masks) -> None:
        """Display the annotated frame, masks and process keyboard input."""
        if not self._gui_enabled:
            return
        try:
            if self._window_was_shown and cv2.getWindowProperty(
                    self._window_name, cv2.WND_PROP_VISIBLE) < 1:
                self.get_logger().info('display window closed; continuing headless')
                self._disable_gui()
                return
            cv2.imshow(self._window_name, annotated)
            display_size = (annotated.shape[1], annotated.shape[0])
            if display_size != self._display_size:
                cv2.resizeWindow(
                    self._window_name, display_size[0], display_size[1])
                self._display_size = display_size
            self._window_was_shown = True
            if self._masks_visible and self._mask_window_was_shown:
                try:
                    if cv2.getWindowProperty(
                            self._mask_window_name, cv2.WND_PROP_VISIBLE) < 1:
                        self._masks_visible = False
                except cv2.error:
                    self._masks_visible = False
            if self._masks_visible:
                canvas_width = min(800, annotated.shape[1])
                canvas_height = min(600, annotated.shape[0])
                montage = make_mask_montage(
                    masks, self._config,
                    canvas_width=canvas_width, canvas_height=canvas_height)
                cv2.imshow(self._mask_window_name, montage)
                self._mask_window_was_shown = True
            key = cv2.waitKey(1) & 0xFF
            self._handle_key(key)
        except cv2.error as exc:
            self.get_logger().warning(f'GUI disabled after error: {exc}')
            self._disable_gui()

    def _handle_key(self, key: int) -> None:
        """Process a single OpenCV keyboard event."""
        if key in (255, 0):
            return
        if key in (27, ord('q')):
            self._request_shutdown('quit requested from GUI')
        elif key == ord('s'):
            self._save_config()
        elif key == ord('l'):
            self._load_config()
        elif key == ord('r'):
            self._reset_config()
        elif key == ord('m'):
            self._toggle_masks()
        elif key == ord('h'):
            self.get_logger().info(TRACKBAR_HELP)

    def _toggle_masks(self) -> None:
        """Show or hide the mask preview window."""
        if not self._gui_enabled:
            return
        if self._masks_visible:
            try:
                cv2.destroyWindow(self._mask_window_name)
            except cv2.error:
                pass
            self._masks_visible = False
            self._mask_window_was_shown = False
            return
        try:
            cv2.namedWindow(self._mask_window_name, cv2.WINDOW_NORMAL)
            self._masks_visible = True
            self._mask_window_was_shown = False
        except cv2.error as exc:
            self.get_logger().warning(f'could not open mask window: {exc}')

    def _disable_gui(self) -> None:
        """Disable all GUI output and close OpenCV windows."""
        self._gui_enabled = False
        self._masks_visible = False
        self._mask_window_was_shown = False
        self._display_size = None
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass

    # ----------------------------------------------------------------- shutdown
    def _request_shutdown(self, reason: str) -> None:
        """Stop the ROS executor after logging the reason."""
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        self.get_logger().info(f'stopping vision server: {reason}')
        if rclpy.ok():
            rclpy.shutdown()

    def shutdown(self) -> None:
        """Release capture, optionally save config and close windows."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._shutdown_requested = True
        if self._timer is not None:
            self._timer.cancel()
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        if self._auto_save and self._config_path:
            success, message = self._save_config(quiet=True)
            if success:
                self.get_logger().info(message)
            else:
                self.get_logger().warning(message)
        if self._gui_enabled:
            self._disable_gui()


def main(args=None) -> int:
    """Run the colour sorting server node."""
    rclpy.init(args=args)
    node = None
    exit_code = 0
    try:
        node = MvcSortingServer()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
        if node is None:
            print(f'[Mvc_sorting_server] {exc}', file=sys.stderr)
        else:
            node.get_logger().fatal(str(exc))
        exit_code = 1
    finally:
        if node is not None:
            node.shutdown()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
