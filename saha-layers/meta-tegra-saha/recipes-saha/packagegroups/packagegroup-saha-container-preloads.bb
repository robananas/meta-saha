DESCRIPTION = "Container archives used only to construct the initial DATA image"
LICENSE = "MIT"
PR = "r1"
inherit packagegroup
RDEPENDS:${PN} = " \
    saha-homeassistant-container-image \
    saha-homeassistant-mcp-container-image \
    saha-workflow-mcp-container-image \
    saha-matter-server-container-image \
    roban-app \
    saha-livekit-server-container-image \
    saha-livekit-agent-image \
    saha-s2s-container-image \
    saha-cosyvoice-container-image \
    saha-s2s-models \
"
