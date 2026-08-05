SUMMARY = "Independent Roban S2S container runtime"
DESCRIPTION = "Installs the isolated S2S Compose project, configuration, launcher, and systemd service."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://compose.yaml \
    file://saha-s2s.env \
    file://saha-s2s.service \
    file://saha-s2s.sh \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-s2s.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

RDEPENDS:${PN} = "bash curl docker docker-compose"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-s2s.sh ${D}${bindir}/saha-s2s

    install -d ${D}${sysconfdir}/default
    install -m 0644 ${UNPACKDIR}/saha-s2s.env ${D}${sysconfdir}/default/saha-s2s

    install -d ${D}/opt/roban/s2s
    install -m 0644 ${UNPACKDIR}/compose.yaml ${D}/opt/roban/s2s/compose.yaml

    install -d ${D}${localstatedir}/lib/saha/s2s/models
    install -d ${D}${localstatedir}/cache/saha/s2s
    install -d ${D}/data/model-config/s2s/voices

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-s2s.service ${D}${systemd_system_unitdir}/saha-s2s.service
}

FILES:${PN} += " \
    /opt/roban/s2s/compose.yaml \
    ${sysconfdir}/default/saha-s2s \
    ${localstatedir}/lib/saha/s2s/models \
    ${localstatedir}/cache/saha/s2s \
    /data/model-config/s2s/voices \
"
