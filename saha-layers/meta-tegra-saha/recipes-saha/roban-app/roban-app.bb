SUMMARY = "Preloaded Roban workflow API container image for Jetson (arm64)"
DESCRIPTION = "Installs the local roban-workflow-api:arm64 container image as a \
docker-archive tarball for offline docker load on first boot."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "1.0"

ROBAN_WORKFLOW_IMAGE ?= "roban-workflow-api:arm64"
ROBAN_WORKFLOW_IMAGE_OS ?= "linux"
ROBAN_WORKFLOW_IMAGE_ARCH ?= "arm64"
ROBAN_WORKFLOW_IMAGE_BASENAME ?= "roban-workflow-api"
ROBAN_WORKFLOW_LOCAL_TAR ?= "${DL_DIR}/roban-workflow-api.tar"

SRC_URI = "file://fetch-image.sh"

DEPENDS = "ca-certificates-native"
PACKAGE_ARCH = "${MACHINE_ARCH}"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INSANE_SKIP:${PN} += "already-stripped ldflags dev-so"

addtask fetch_image after do_unpack before do_patch
do_fetch_image[network] = "1"

do_fetch_image() {
    ROBAN_WORKFLOW_IMAGE="${ROBAN_WORKFLOW_IMAGE}" \
    ROBAN_WORKFLOW_IMAGE_OS="${ROBAN_WORKFLOW_IMAGE_OS}" \
    ROBAN_WORKFLOW_IMAGE_ARCH="${ROBAN_WORKFLOW_IMAGE_ARCH}" \
    ROBAN_WORKFLOW_LOCAL_TAR="${ROBAN_WORKFLOW_LOCAL_TAR}" \
    DL_DIR="${DL_DIR}" \
    sh ${UNPACKDIR}/fetch-image.sh "${WORKDIR}/${ROBAN_WORKFLOW_IMAGE_BASENAME}.tar"
}

do_install() {
    install -d ${D}${datadir}/saha/roban-workflow-api
    install -m 0644 ${WORKDIR}/${ROBAN_WORKFLOW_IMAGE_BASENAME}.tar \
        ${D}${datadir}/saha/roban-workflow-api/image.tar
}

FILES:${PN} = "${datadir}/saha/roban-workflow-api/image.tar"
