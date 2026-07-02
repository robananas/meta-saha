# Lyrical blacklists launch-testing-ros when zenoh is skipped, but the
# generated ros-core variant still depends on it. Keep this conditional so
# Jazzy's already-validated image contents do not change.
ROS_EXEC_DEPENDS:remove = "${@'launch-testing-ros' if d.getVar('ROS_DISTRO') == 'lyrical' else ''}"
