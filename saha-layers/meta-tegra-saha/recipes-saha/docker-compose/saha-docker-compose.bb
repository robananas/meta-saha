SUMMARY = "Docker Compose launcher for Saha application containers"
DESCRIPTION = "Installs compose.yaml and a systemd-managed wrapper that loads \
prebuilt container images and starts Home Assistant, Matter Server, and the \
Roban workflow API with docker compose."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://compose.yaml \
    file://saha-docker-compose.env \
    file://saha-docker-compose.service \
    file://saha-docker-compose.sh \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-docker-compose.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

RDEPENDS:${PN} = "bash curl docker docker-compose python3-core"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-docker-compose.sh ${D}${bindir}/saha-docker-compose

    install -d ${D}${sysconfdir}/default
    install -m 0644 ${UNPACKDIR}/saha-docker-compose.env ${D}${sysconfdir}/default/saha-docker-compose

    install -d ${D}/opt/roban/compose
    install -m 0644 ${UNPACKDIR}/compose.yaml ${D}/opt/roban/compose/compose.yaml

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-docker-compose.service ${D}${systemd_system_unitdir}

    install -d ${D}${sysconfdir}/systemd/system/multi-user.target.wants
    ln -sf ${systemd_system_unitdir}/saha-docker-compose.service \
        ${D}${sysconfdir}/systemd/system/multi-user.target.wants/saha-docker-compose.service
}

FILES:${PN} += " \
    /opt/roban/compose/compose.yaml \
    ${sysconfdir}/default/saha-docker-compose \
    ${sysconfdir}/systemd/system/multi-user.target.wants/saha-docker-compose.service \
"
