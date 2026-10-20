"""ROS 2 colour target subscriber and console monitor."""

from __future__ import annotations

import json

from color_sorting_interfaces.msg import ColorTargetArray
import rclpy
from rclpy.node import Node


class MvcSortingClient(Node):
    """Subscribe to ColorTargetArray and print the received target list."""

    def __init__(self) -> None:
        """Declare parameters and start the subscription."""
        super().__init__('Mvc_sorting_client')
        self._targets_topic = str(
            self.declare_parameter('targets_topic', '/color_targets').value)
        self._max_messages = max(
            0, int(self.declare_parameter('max_messages', 0).value))
        print_json_value = self.declare_parameter('print_json', False).value
        if isinstance(print_json_value, str):
            self._print_json = print_json_value.strip().lower() in (
                '1', 'true', 'yes', 'on')
        else:
            self._print_json = bool(print_json_value)
        self._message_count = 0
        self._subscription = self.create_subscription(
            ColorTargetArray, self._targets_topic, self._on_targets, 10)
        self.get_logger().info(
            f'listening for colour targets on {self._targets_topic}')

    def _on_targets(self, message: ColorTargetArray) -> None:
        """Print one received target array."""
        self._message_count += 1
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        if self._print_json:
            payload = {
                'sequence': self._message_count,
                'stamp': stamp,
                'frame_id': message.header.frame_id,
                'targets': [
                    {
                        'id': int(target.id),
                        'color': target.color,
                        'x': round(float(target.x), 2),
                        'y': round(float(target.y), 2),
                        'area': round(float(target.area), 2),
                    }
                    for target in message.targets
                ],
            }
            self.get_logger().info(json.dumps(payload, ensure_ascii=False))
        else:
            lines = [
                f'frame {self._message_count}: {len(message.targets)} target(s), '
                f'stamp={stamp:.3f}, frame_id={message.header.frame_id!r}'
            ]
            for target in message.targets:
                lines.append(
                    f'  id={int(target.id):>3d}  {target.color:<6s}  '
                    f'x={float(target.x):8.2f}  y={float(target.y):8.2f}  '
                    f'area={float(target.area):9.2f}')
            self.get_logger().info('\n' + '\n'.join(lines))

        if self._max_messages and self._message_count >= self._max_messages:
            self.get_logger().info(
                f'received max_messages={self._max_messages}; stopping')
            if rclpy.ok():
                rclpy.shutdown()


def main(args=None) -> int:
    """Run the colour target monitor node."""
    rclpy.init(args=args)
    node = None
    try:
        node = MvcSortingClient()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    main()
