SUMMARY = "Home Assistant MCP board service configuration"
DESCRIPTION = "Installs persistent MCP credential generation and board service defaults."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://home-assistant-mcp.env \
    file://saha-homeassistant-mcp-credentials.sh \
    file://saha-homeassistant-mcp-credentials.service \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-homeassistant-mcp-credentials.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"
RDEPENDS:${PN} = "iproute2 python3-core"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-homeassistant-mcp-credentials.sh \
        ${D}${bindir}/saha-homeassistant-mcp-credentials

    install -d ${D}${sysconfdir}/default
    install -m 0644 ${UNPACKDIR}/home-assistant-mcp.env \
        ${D}${sysconfdir}/default/home-assistant-mcp

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-homeassistant-mcp-credentials.service \
        ${D}${systemd_system_unitdir}/
}

FILES:${PN} += "${sysconfdir}/default/home-assistant-mcp"
