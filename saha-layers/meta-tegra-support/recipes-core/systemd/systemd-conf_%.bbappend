FILESEXTRAPATHS:prepend := "${THISDIR}/${BPN}:"

SRC_URI += "\
    file://skip-dummy-interfaces.conf \
    file://cn-ntp.conf \
"

do_install:append() {
    install -d ${D}${sysconfdir}/systemd/network/80-wired.network.d
    install -m 0644 ${UNPACKDIR}/skip-dummy-interfaces.conf ${D}${sysconfdir}/systemd/network/80-wired.network.d/

    # Prefer mainland China NTP; override systemd's Google FallbackNTP defaults.
    install -d ${D}${sysconfdir}/systemd/timesyncd.conf.d
    install -m 0644 ${UNPACKDIR}/cn-ntp.conf ${D}${sysconfdir}/systemd/timesyncd.conf.d/10-cn-ntp.conf
}

FILES:${PN} += "\
    ${sysconfdir}/systemd/network \
    ${sysconfdir}/systemd/timesyncd.conf.d \
"
