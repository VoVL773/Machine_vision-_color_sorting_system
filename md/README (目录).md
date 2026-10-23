![项目结构](./assets/image/项目结构.png)

> 按项目结构逐步讲解，先跑通纯 Python 视觉模块，再接入 ROS 2。

教程结合分段源码、中文解释、参数表和验收示例，帮助复刻项目并学习 ROS 2 与 OpenCV。
命令中的 `$WS` 表示工作区根目录；每个新终端先设置工作区路径，再加载 ROS 和构建后的工作区环境。

```bash
export WS="$HOME/color_sorting_ws"
cd "$WS"
source /opt/ros/jazzy/setup.bash
# 首次构建成功后再加载：
source install/setup.bash
```

# 目录

- [一.接口包(color_sorting_interfaces)](<一.接口包(color_sorting_interfaces).md>)
- [二.包骨架创建与 HSV 配置层](<二.包骨架创建与 HSV 配置层.md>)
- [三.检测与跟踪层：color_detector.py](<三.检测与跟踪层：color_detector.py.md>)
- [四.可视化层：visualization.py](<四.可视化层：visualization.py.md>)
- [五.中文调参面板：gui.py](<五.中文调参面板：gui.py.md>)
- [六.合成测试场景：image_sources.py](<六.合成测试场景：image_sources.py.md>)
- [七.ROS 视觉服务端：Mvc_sorting_server.py](<七.ROS视觉服务端：Mvc_sorting_server.py.md>)
- [八.订阅客户端：Mvc_sorting_client.py](<八.订阅客户端：Mvc_sorting_client.py.md>)
- [九.配置、launch 与测试](<九.配置、launch与测试.md>)
