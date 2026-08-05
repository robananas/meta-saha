SUMMARY = "Preloaded official CosyVoice ARM64 sidecar image"
DESCRIPTION = "Packages the quality-gated roban-cosyvoice:arm64 archive independently from the S2S image."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"
PV = "1.0"
COSYVOICE_IMAGE ?= "roban-cosyvoice:arm64"
COSYVOICE_IMAGE_ARCH ?= "arm64"
COSYVOICE_LOCAL_TAR ?= "${DL_DIR}/roban-cosyvoice.tar"
SRC_URI = "file://fetch-cosyvoice-image.sh"
DEPENDS = "ca-certificates-native"
PACKAGE_ARCH = "${MACHINE_ARCH}"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INSANE_SKIP:${PN} += "already-stripped ldflags dev-so"
addtask fetch_image after do_unpack before do_patch
do_fetch_image[network] = "0"
do_fetch_image[nostamp] = "1"
do_fetch_image() {
    COSYVOICE_IMAGE="${COSYVOICE_IMAGE}" COSYVOICE_IMAGE_ARCH="${COSYVOICE_IMAGE_ARCH}" \
    COSYVOICE_LOCAL_TAR="${COSYVOICE_LOCAL_TAR}" DL_DIR="${DL_DIR}" \
    sh ${UNPACKDIR}/fetch-cosyvoice-image.sh "${WORKDIR}/roban-cosyvoice.tar"
}
do_install() {
    install -d ${D}${datadir}/saha/cosyvoice
    install -m 0644 ${WORKDIR}/roban-cosyvoice.tar ${D}${datadir}/saha/cosyvoice/image.tar
}
FILES:${PN} = "${datadir}/saha/cosyvoice/image.tar"
