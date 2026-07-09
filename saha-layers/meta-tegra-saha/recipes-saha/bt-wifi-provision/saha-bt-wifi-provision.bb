SUMMARY = "Bluetooth GATT service for WiFi provisioning"
DESCRIPTION = "Exposes a BLE GATT API for phone apps to query WiFi status, \
scan networks, and connect via NetworkManager/nmcli."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://saha-bt-wifi-provision.py \
    file://saha-bt-wifi-provision.sh \
    file://saha-bt-wifi-provision-wait.sh \
    file://dbus_mainloop.py \
    file://gatt_server.py \
    file://wifi_manager.py \
    file://saha-bt-wifi-provision.env \
    file://saha-bt-wifi-provision.service \
    file://GATT.md \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-bt-wifi-provision.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

RDEPENDS:${PN} = " \
    bluez5 \
    dbus-glib \
    networkmanager-nmcli \
    python3-core \
    python3-dbus \
"

do_install() {
    install -d ${D}${libdir}/saha-bt-wifi-provision
    install -m 0644 ${UNPACKDIR}/saha-bt-wifi-provision.py ${D}${libdir}/saha-bt-wifi-provision/
    install -m 0644 ${UNPACKDIR}/dbus_mainloop.py ${D}${libdir}/saha-bt-wifi-provision/
    install -m 0644 ${UNPACKDIR}/gatt_server.py ${D}${libdir}/saha-bt-wifi-provision/
    install -m 0644 ${UNPACKDIR}/wifi_manager.py ${D}${libdir}/saha-bt-wifi-provision/

    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-bt-wifi-provision.sh ${D}${bindir}/saha-bt-wifi-provision
    install -m 0755 ${UNPACKDIR}/saha-bt-wifi-provision-wait.sh ${D}${bindir}/saha-bt-wifi-provision-wait
    sed -i "s,@libdir@,${libdir},g" ${D}${bindir}/saha-bt-wifi-provision

    install -d ${D}${sysconfdir}/default
    install -m 0644 ${UNPACKDIR}/saha-bt-wifi-provision.env ${D}${sysconfdir}/default/saha-bt-wifi-provision

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-bt-wifi-provision.service ${D}${systemd_system_unitdir}

    install -d ${D}${datadir}/doc/${PN}
    install -m 0644 ${UNPACKDIR}/GATT.md ${D}${datadir}/doc/${PN}/GATT.md

    install -d ${D}${sysconfdir}/systemd/system/multi-user.target.wants
    ln -sf ${systemd_system_unitdir}/saha-bt-wifi-provision.service \
        ${D}${sysconfdir}/systemd/system/multi-user.target.wants/saha-bt-wifi-provision.service
}

FILES:${PN} += " \
    ${libdir}/saha-bt-wifi-provision \
    ${datadir}/doc/${PN}/GATT.md \
    ${sysconfdir}/default/saha-bt-wifi-provision \
    ${sysconfdir}/systemd/system/multi-user.target.wants/saha-bt-wifi-provision.service \
"
