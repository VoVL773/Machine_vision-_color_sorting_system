"""Launch the colour sorting vision server and optional monitor client."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    """Build the launch description."""
    arguments = [
        DeclareLaunchArgument(
            'input_type', default_value='camera',
            description='camera, video, topic or synthetic'),
        DeclareLaunchArgument(
            'camera_index', default_value='0',
            description='OpenCV camera index'),
        DeclareLaunchArgument(
            'camera_backend', default_value='auto',
            description='auto or v4l2 (Linux)'),
        DeclareLaunchArgument(
            'camera_fourcc', default_value='',
            description='Optional camera FOURCC, e.g. MJPG or YUYV; empty lets the driver choose'),
        DeclareLaunchArgument(
            'camera_autofocus', default_value='true',
            description='Enable camera continuous autofocus when supported'),
        DeclareLaunchArgument(
            'camera_focus', default_value='-1',
            description='Manual camera focus value; -1 keeps autofocus'),
        DeclareLaunchArgument(
            'camera_sharpness', default_value='-1',
            description='Camera sharpness value; -1 leaves the driver default'),
        DeclareLaunchArgument(
            'frame_width', default_value='1280',
            description='Requested camera/frame width'),
        DeclareLaunchArgument(
            'frame_height', default_value='720',
            description='Requested camera/frame height'),
        DeclareLaunchArgument(
            'fps', default_value='30.0',
            description='Capture timer rate and requested camera FPS'),
        DeclareLaunchArgument(
            'display_sharpen', default_value='0.35',
            description='Display-only unsharp mask amount (0 disables)'),
        DeclareLaunchArgument(
            'min_hits', default_value='2',
            description='Frames a blob must be seen before it is published'),
        DeclareLaunchArgument(
            'video_path', default_value='',
            description='Video file used when input_type:=video'),
        DeclareLaunchArgument(
            'image_topic', default_value='/camera/image_raw',
            description='ROS image topic used when input_type:=topic'),
        DeclareLaunchArgument(
            'targets_topic', default_value='/color_targets',
            description='Published ColorTargetArray topic'),
        DeclareLaunchArgument(
            'config_path', default_value='',
            description='HSV JSON file; empty uses ~/.ros/color_sorting_hsv.json'),
        DeclareLaunchArgument(
            'show_window', default_value='true',
            description='Show the annotated OpenCV window'),
        DeclareLaunchArgument(
            'show_masks', default_value='true',
            description='Show the per-colour mask preview window'),
        DeclareLaunchArgument(
            'show_trackbars', default_value='true',
            description='Show the Chinese HSV Trackbar window'),
        DeclareLaunchArgument(
            'publish_debug_image', default_value='false',
            description='Publish the annotated frame as sensor_msgs/Image'),
        DeclareLaunchArgument(
            'enable_tracking', default_value='true',
            description='Keep stable IDs between frames'),
        DeclareLaunchArgument(
            'max_frames', default_value='0',
            description='Stop after N frames (0 = unlimited)'),
        DeclareLaunchArgument(
            'with_client', default_value='false',
            description='Also start the console target monitor'),
    ]

    server = Node(
        package='Mvc_sorting',
        executable='Mvc_sorting_server',
        name='Mvc_sorting_server',
        output='screen',
        parameters=[{
            'input_type': LaunchConfiguration('input_type'),
            'camera_index': ParameterValue(
                LaunchConfiguration('camera_index'), value_type=int),
            'camera_backend': LaunchConfiguration('camera_backend'),
            'camera_fourcc': LaunchConfiguration('camera_fourcc'),
            'camera_autofocus': ParameterValue(
                LaunchConfiguration('camera_autofocus'), value_type=bool),
            'camera_focus': ParameterValue(
                LaunchConfiguration('camera_focus'), value_type=int),
            'camera_sharpness': ParameterValue(
                LaunchConfiguration('camera_sharpness'), value_type=int),
            'frame_width': ParameterValue(
                LaunchConfiguration('frame_width'), value_type=int),
            'frame_height': ParameterValue(
                LaunchConfiguration('frame_height'), value_type=int),
            'fps': ParameterValue(
                LaunchConfiguration('fps'), value_type=float),
            'display_sharpen': ParameterValue(
                LaunchConfiguration('display_sharpen'), value_type=float),
            'min_hits': ParameterValue(
                LaunchConfiguration('min_hits'), value_type=int),
            'video_path': LaunchConfiguration('video_path'),
            'image_topic': LaunchConfiguration('image_topic'),
            'targets_topic': LaunchConfiguration('targets_topic'),
            'config_path': LaunchConfiguration('config_path'),
            'show_window': ParameterValue(
                LaunchConfiguration('show_window'), value_type=bool),
            'show_masks': ParameterValue(
                LaunchConfiguration('show_masks'), value_type=bool),
            'show_trackbars': ParameterValue(
                LaunchConfiguration('show_trackbars'), value_type=bool),
            'publish_debug_image': ParameterValue(
                LaunchConfiguration('publish_debug_image'), value_type=bool),
            'enable_tracking': ParameterValue(
                LaunchConfiguration('enable_tracking'), value_type=bool),
            'max_frames': ParameterValue(
                LaunchConfiguration('max_frames'), value_type=int),
        }],
    )

    client = Node(
        package='Mvc_sorting',
        executable='Mvc_sorting_client',
        name='Mvc_sorting_client',
        output='screen',
        condition=IfCondition(LaunchConfiguration('with_client')),
        parameters=[{
            'targets_topic': LaunchConfiguration('targets_topic'),
        }],
    )

    return LaunchDescription(arguments + [server, client])
