FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " file://main.conf"

SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install:append() {
    install -d ${D}${sysconfdir}/bluetooth
    install -m 0644 ${UNPACKDIR}/main.conf ${D}${sysconfdir}/bluetooth/main.conf
}
