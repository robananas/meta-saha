SUMMARY = "Saha board boot and service status aggregator"
DESCRIPTION = "Collects bounded, current-boot board status events for diagnostics."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://saha-board-status.py \
    file://saha-board-status.service \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-board-status.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

RDEPENDS:${PN} = "python3-core python3-json python3-subprocess python3-threading curl networkmanager-nmcli"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-board-status.py ${D}${bindir}/saha-board-status

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-board-status.service ${D}${systemd_system_unitdir}/
}
