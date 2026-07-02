do_install:append() {
    install -d ${D}${sysconfdir}/systemd/system/multi-user.target.wants
    ln -sf ${systemd_system_unitdir}/usb-gadget.target \
        ${D}${sysconfdir}/systemd/system/multi-user.target.wants/usb-gadget.target
}

FILES:${PN}:append = " ${sysconfdir}/systemd/system/multi-user.target.wants/usb-gadget.target"
