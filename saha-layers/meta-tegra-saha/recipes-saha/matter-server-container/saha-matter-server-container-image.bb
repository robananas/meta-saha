SUMMARY = "Preloaded python-matter-server container image for Jetson (aarch64)"
DESCRIPTION = "Installs the Matter Server container image as a docker-archive \
tarball tagged ghcr.io/matter-js/python-matter-server:arm64 for docker compose."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "1.0"

MATTER_SERVER_CONTAINER_IMAGE ?= "ghcr.io/matter-js/python-matter-server:stable"
MATTER_SERVER_CONTAINER_RUNTIME_IMAGE ?= "ghcr.io/matter-js/python-matter-server:arm64"
MATTER_SERVER_CONTAINER_IMAGE_OS ?= "linux"
MATTER_SERVER_CONTAINER_IMAGE_ARCH ?= "arm64"
MATTER_SERVER_CONTAINER_IMAGE_BASENAME ?= "matter-server-container"
MATTER_SERVER_CONTAINER_LOCAL_TAR ?= "${DL_DIR}/matter-server-container.tar"

SRC_URI = "file://fetch-image.sh"

DEPENDS = "ca-certificates-native skopeo-native"
PACKAGE_ARCH = "${MACHINE_ARCH}"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INSANE_SKIP:${PN} += "already-stripped ldflags dev-so"

addtask fetch_image after do_unpack before do_patch
do_fetch_image[depends] += "ca-certificates-native:do_populate_sysroot skopeo-native:do_populate_sysroot"
do_fetch_image[network] = "1"
do_fetch_image[prefuncs] = "extend_recipe_sysroot"

do_fetch_image() {
    MATTER_SERVER_CONTAINER_IMAGE="${MATTER_SERVER_CONTAINER_IMAGE}" \
    MATTER_SERVER_CONTAINER_RUNTIME_IMAGE="${MATTER_SERVER_CONTAINER_RUNTIME_IMAGE}" \
    MATTER_SERVER_CONTAINER_IMAGE_OS="${MATTER_SERVER_CONTAINER_IMAGE_OS}" \
    MATTER_SERVER_CONTAINER_IMAGE_ARCH="${MATTER_SERVER_CONTAINER_IMAGE_ARCH}" \
    MATTER_SERVER_CONTAINER_LOCAL_TAR="${MATTER_SERVER_CONTAINER_LOCAL_TAR}" \
    DL_DIR="${DL_DIR}" \
    SKOPEO_BIN="${STAGING_SBINDIR_NATIVE}/skopeo" \
    sh ${UNPACKDIR}/fetch-image.sh "${WORKDIR}/${MATTER_SERVER_CONTAINER_IMAGE_BASENAME}.tar"
}

do_install() {
    install -d ${D}${datadir}/saha/matter-server
    install -m 0644 ${WORKDIR}/${MATTER_SERVER_CONTAINER_IMAGE_BASENAME}.tar \
        ${D}${datadir}/saha/matter-server/image.tar
}

FILES:${PN} = "${datadir}/saha/matter-server/image.tar"
