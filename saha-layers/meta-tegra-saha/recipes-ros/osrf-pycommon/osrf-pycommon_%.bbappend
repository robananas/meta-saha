# Lyrical installs the Python modules into the main ROS package, while some
# generated recipes still depend on the Debian-style python3-osrf-pycommon name.
RPROVIDES:${PN} += "${@'python3-osrf-pycommon' if d.getVar('ROS_DISTRO') == 'lyrical' else ''}"
