FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " \
    file://main.conf \
    file://bluetooth.service.d/saha-experimental.conf \
"

SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install:append() {
    install -d ${D}${sysconfdir}/bluetooth
    install -m 0644 ${UNPACKDIR}/main.conf ${D}${sysconfdir}/bluetooth/main.conf

    install -d ${D}${systemd_system_unitdir}/bluetooth.service.d
    install -m 0644 ${UNPACKDIR}/bluetooth.service.d/saha-experimental.conf \
        ${D}${systemd_system_unitdir}/bluetooth.service.d/saha-experimental.conf
}

FILES:${PN} += "${systemd_system_unitdir}/bluetooth.service.d/saha-experimental.conf"
