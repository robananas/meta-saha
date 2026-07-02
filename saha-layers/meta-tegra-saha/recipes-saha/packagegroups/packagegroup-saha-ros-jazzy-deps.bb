DESCRIPTION = "ROS 2 Jazzy dependencies for Saha images"

LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    ros-base \
    ament-cmake \
    ament-cmake-auto \
    ament-index-python \
    rclcpp \
    rclcpp-components \
    rclcpp-lifecycle \
    rclpy \
    rcutils \
    rcl-interfaces \
    launch \
    launch-ros \
    pluginlib \
    rosidl-default-generators \
    rosidl-default-runtime \
    builtin-interfaces \
    common-interfaces \
    std-msgs \
    std-srvs \
    geometry-msgs \
    nav-msgs \
    sensor-msgs \
    sensor-msgs-py \
    diagnostic-msgs \
    visualization-msgs \
    tf2 \
    tf2-ros \
    tf2-msgs \
    robot-state-publisher \
    xacro \
    urdf \
    rmw-fastrtps-cpp \
    rmw-fastrtps-shared-cpp \
    fastrtps \
    fastcdr \
    rosidl-dynamic-typesupport-fastrtps \
    rosidl-typesupport-fastrtps-c \
    rosidl-typesupport-fastrtps-cpp \
    ros2-control \
    controller-manager \
    controller-manager-msgs \
    hardware-interface \
    diff-drive-controller \
    joint-state-broadcaster \
    pcl-conversions \
    pcl-ros \
    rosbag2 \
    libeigen-dev \
    apr \
    python3-colcon-common-extensions \
    python3-numpy \
    python3-tomli \
"
