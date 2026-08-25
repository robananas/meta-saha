SUMMARY = "Workflow control MCP board service configuration"
DESCRIPTION = "Installs persistent workflow MCP credential generation and fixed board service defaults."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://workflow-mcp.env \
    file://saha-workflow-mcp-credentials.sh \
    file://saha-workflow-mcp-credentials.service \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-workflow-mcp-credentials.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"
RDEPENDS:${PN} = "python3-core"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-workflow-mcp-credentials.sh \
        ${D}${bindir}/saha-workflow-mcp-credentials

    install -d ${D}${sysconfdir}/default
    install -m 0644 ${UNPACKDIR}/workflow-mcp.env \
        ${D}${sysconfdir}/default/workflow-mcp

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-workflow-mcp-credentials.service \
        ${D}${systemd_system_unitdir}/
}

FILES:${PN} += "${sysconfdir}/default/workflow-mcp"
