# Lyrical's generated rmw-implementation depends on rmw-zenoh-cpp, whose
# zenoh-cpp-vendor recipe requires zenoh-c from an extra meta-zenoh layer.
# saha-image-robot keeps the default layer graph small and uses the DDS RMWs.
ROS_BUILD_DEPENDS:remove = "rmw-zenoh-cpp"
