# Lyrical skips rmw-test-fixture-implementation with the zenoh group because
# that fixture can depend on zenoh-cpp. It is not needed at runtime.
ROS_EXEC_DEPENDS:remove = "${@'rmw-test-fixture-implementation' if d.getVar('ROS_DISTRO') == 'lyrical' else ''}"
