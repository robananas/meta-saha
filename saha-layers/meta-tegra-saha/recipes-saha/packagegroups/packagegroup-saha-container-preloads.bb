DESCRIPTION = "Container archives used only to construct the initial DATA image"
LICENSE = "MIT"
inherit packagegroup
RDEPENDS:${PN} = " \
    saha-homeassistant-container-image \
    saha-matter-server-container-image \
    roban-app \
    saha-livekit-server-container-image \
    saha-livekit-agent-image \
    saha-s2s-container-image \
"
