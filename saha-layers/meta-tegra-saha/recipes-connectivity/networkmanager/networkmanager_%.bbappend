FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " file://99-saha-unmanaged-devices.conf"

SYSTEMD_AUTO_ENABLE:${PN}-daemon = "enable"

do_install:append() {
    install -d ${D}${sysconfdir}/NetworkManager/conf.d
    install -m 0644 ${UNPACKDIR}/99-saha-unmanaged-devices.conf \
        ${D}${sysconfdir}/NetworkManager/conf.d/
}

FILES:${PN}-daemon += "${sysconfdir}/NetworkManager/conf.d/99-saha-unmanaged-devices.conf"
