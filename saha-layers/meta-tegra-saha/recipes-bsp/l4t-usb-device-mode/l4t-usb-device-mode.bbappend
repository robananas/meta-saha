FILESEXTRAPATHS:prepend := "${THISDIR}/${BPN}:"

SRC_URI += " \
    file://00-saha-usb-role.conf \
    file://saha-usb-role-device \
"

do_install:append() {
    install -d ${D}${sysconfdir}/systemd/system/multi-user.target.wants
    ln -sf ${systemd_system_unitdir}/usb-gadget.target \
        ${D}${sysconfdir}/systemd/system/multi-user.target.wants/usb-gadget.target

    install -d ${D}${sysconfdir}/systemd/system/usbgx.service.d
    install -m 0644 ${UNPACKDIR}/00-saha-usb-role.conf \
        ${D}${sysconfdir}/systemd/system/usbgx.service.d/

    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-usb-role-device ${D}${bindir}/
}

FILES:${PN}:append = " \
    ${bindir}/saha-usb-role-device \
    ${sysconfdir}/systemd/system/multi-user.target.wants/usb-gadget.target \
    ${sysconfdir}/systemd/system/usbgx.service.d/00-saha-usb-role.conf \
"
