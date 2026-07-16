SUMMARY = "Persistent BLE static random identity for Saha devices"
DESCRIPTION = "Creates and applies a persistent BLE Static Random Identity Address before BlueZ starts, and provides a factory-reset command."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://saha-ble-identity-init.py \
    file://saha-bluetooth-factory-reset.sh \
    file://saha-ble-identity.service \
"

S = "${UNPACKDIR}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-ble-identity.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

# btmgmt is one of the readline-enabled noinst tools in OE-Core wrynose.
RDEPENDS:${PN} = " \
    bluez5-noinst-tools \
    python3-core \
"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/saha-ble-identity-init.py \
        ${D}${bindir}/saha-ble-identity-init
    install -m 0755 ${UNPACKDIR}/saha-bluetooth-factory-reset.sh \
        ${D}${bindir}/saha-bluetooth-factory-reset

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-ble-identity.service \
        ${D}${systemd_system_unitdir}/saha-ble-identity.service
}

FILES:${PN} += "${systemd_system_unitdir}/saha-ble-identity.service"
