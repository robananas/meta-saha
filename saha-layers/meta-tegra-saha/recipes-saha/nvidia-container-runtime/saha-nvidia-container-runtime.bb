SUMMARY = "Docker registration for the optional NVIDIA container runtime"
DESCRIPTION = "Registers the NVIDIA runtime with Docker without making it the default runtime."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://saha-nvidia-container-runtime.service"

inherit systemd

SYSTEMD_SERVICE:${PN} = "saha-nvidia-container-runtime.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

RDEPENDS:${PN} = "nvidia-container-toolkit"

do_install() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/saha-nvidia-container-runtime.service \
        ${D}${systemd_system_unitdir}/saha-nvidia-container-runtime.service
}
