SUMMARY = "Ollama local model server for Jetson"
DESCRIPTION = "Installs the official ARM64 Ollama runtime, JetPack 6 CUDA runner, allowlisted model manager, and systemd services."
HOMEPAGE = "https://ollama.com"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    https://github.com/ollama/ollama/releases/download/v${PV}/ollama-linux-arm64.tar.zst;name=runtime \
    https://github.com/ollama/ollama/releases/download/v${PV}/ollama-linux-arm64-jetpack6.tar.zst;name=jetpack6 \
    file://ollama.service \
    file://saha-ollama-manager.service \
    file://saha-ollama-manager.py \
    file://test_saha_ollama_manager.py \
    file://ollama-tmpfiles.conf \
"
SRC_URI[runtime.sha256sum] = "aa7e06b5683ee66c4a3ec68ea7236db43b5a5d0821f0dfe2c5a215f4462bddf4"
SRC_URI[jetpack6.sha256sum] = "ed82cb42a215778762bd0927dd34bf222366efd31b25ccde1e1a1ee9a8b942d9"

S = "${UNPACKDIR}"
COMPATIBLE_HOST = "aarch64.*-linux"
INHIBIT_DEFAULT_DEPS = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_PACKAGE_STRIP = "1"
EXCLUDE_FROM_SHLIBS = "1"

inherit systemd

SYSTEMD_SERVICE:${PN} = "ollama.service saha-ollama-manager.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"
RDEPENDS:${PN} = "python3-core python3-json systemd util-linux-setpriv"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/bin/ollama ${D}${bindir}/ollama

    install -d ${D}${libdir}/ollama
    cp -R --no-preserve=ownership ${S}/lib/ollama/. ${D}${libdir}/ollama/
    rm -rf ${D}${libdir}/ollama/cuda_v12

    install -d ${D}${libdir}/saha-ollama-manager
    install -m 0755 ${UNPACKDIR}/saha-ollama-manager.py ${D}${libdir}/saha-ollama-manager/
    install -m 0644 ${UNPACKDIR}/test_saha_ollama_manager.py ${D}${libdir}/saha-ollama-manager/

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/ollama.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${UNPACKDIR}/saha-ollama-manager.service ${D}${systemd_system_unitdir}/

    install -d ${D}${libdir}/tmpfiles.d
    install -m 0644 ${UNPACKDIR}/ollama-tmpfiles.conf ${D}${libdir}/tmpfiles.d/ollama.conf

}

FILES:${PN} += " \
    ${libdir}/ollama \
    ${libdir}/saha-ollama-manager \
    ${libdir}/tmpfiles.d/ollama.conf \
"
INSANE_SKIP:${PN} += "already-stripped dev-so file-rdeps"
