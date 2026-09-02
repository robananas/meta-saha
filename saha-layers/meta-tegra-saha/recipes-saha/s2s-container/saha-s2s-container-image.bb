SUMMARY = "Preloaded local Roban S2S container image"
DESCRIPTION = "Packages the validated local roban-s2s:20260902-catalog-primary-fix-arm64 Docker archive for offline first boot."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "1.0"

S2S_IMAGE ?= "roban-s2s:20260902-catalog-primary-fix-arm64"
S2S_IMAGE_ARCH ?= "arm64"
S2S_LOCAL_TAR ?= "${DL_DIR}/roban-s2s.tar"

SRC_URI = "file://fetch-image.sh"
DEPENDS = "ca-certificates-native"
PACKAGE_ARCH = "${MACHINE_ARCH}"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INSANE_SKIP:${PN} += "already-stripped ldflags dev-so"

addtask fetch_image after do_unpack before do_patch
do_fetch_image[network] = "0"
do_fetch_image[nostamp] = "1"

do_fetch_image() {
    S2S_IMAGE="${S2S_IMAGE}" \
    S2S_IMAGE_ARCH="${S2S_IMAGE_ARCH}" \
    S2S_LOCAL_TAR="${S2S_LOCAL_TAR}" \
    DL_DIR="${DL_DIR}" \
    sh ${UNPACKDIR}/fetch-image.sh "${WORKDIR}/roban-s2s.tar"
}

do_install() {
    install -d ${D}${datadir}/saha/s2s
    install -m 0644 ${WORKDIR}/roban-s2s.tar ${D}${datadir}/saha/s2s/image.tar
}

FILES:${PN} = "${datadir}/saha/s2s/image.tar"
