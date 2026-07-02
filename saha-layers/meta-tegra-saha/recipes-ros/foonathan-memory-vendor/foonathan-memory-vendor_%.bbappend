# Lyrical's foonathan-memory-vendor probes the system package with a nested
# `cmake --find-package` process. That process does not inherit the
# -DCMAKE_PREFIX_PATH passed to the parent configure command, so expose the
# target sysroot prefix through the environment as well.
ROS_BUILD_DEPENDS += " \
    foonathan-memory \
"

do_configure:prepend() {
    export CMAKE_PREFIX_PATH="${RECIPE_SYSROOT}${prefix}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"
}
