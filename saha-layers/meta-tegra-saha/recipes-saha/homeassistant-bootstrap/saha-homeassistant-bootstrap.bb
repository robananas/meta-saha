SUMMARY = "Home Assistant board credential bootstrap"
DESCRIPTION = "Idempotently onboards Home Assistant and stores board-owned OAuth credentials."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://saha-homeassistant-bootstrap.py \
    file://saha-homeassistant-bootstrap.service \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-homeassistant-bootstrap.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

RDEPENDS:${PN} = "python3-core python3-json python3-logging python3-netclient"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-homeassistant-bootstrap.py ${D}${bindir}/saha-homeassistant-bootstrap
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-homeassistant-bootstrap.service ${D}${systemd_system_unitdir}/
}
