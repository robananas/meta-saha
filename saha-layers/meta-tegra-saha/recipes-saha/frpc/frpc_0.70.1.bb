SUMMARY = "FRP reverse proxy client"
DESCRIPTION = "Installs the ARM64 frpc client and a disabled-by-default systemd service for manually managed reverse tunnels."
HOMEPAGE = "https://github.com/fatedier/frp"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=fa818a259cbed7ce8bc2a22d35a464fc"

SRC_URI = " \
    https://github.com/fatedier/frp/releases/download/v${PV}/frp_${PV}_linux_arm64.tar.gz;name=frp \
    file://frpc.toml \
    file://frpc.service \
"
SRC_URI[frp.sha256sum] = "3990f396a9a490ee7f0e5f355287750ed41520064ed999eab443b5e9a78d773d"

S = "${UNPACKDIR}/frp_${PV}_linux_arm64"
COMPATIBLE_HOST = "aarch64.*-linux"
INHIBIT_DEFAULT_DEPS = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_PACKAGE_STRIP = "1"

inherit systemd

SYSTEMD_SERVICE:${PN} = "frpc.service"
SYSTEMD_AUTO_ENABLE:${PN} = "disable"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/frpc ${D}${bindir}/frpc

    install -d ${D}${sysconfdir}/frp
    install -m 0600 ${UNPACKDIR}/frpc.toml ${D}${sysconfdir}/frp/frpc.toml

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/frpc.service ${D}${systemd_system_unitdir}/frpc.service
}

FILES:${PN} += "${sysconfdir}/frp/frpc.toml"
CONFFILES:${PN} += "${sysconfdir}/frp/frpc.toml"
INSANE_SKIP:${PN} += "already-stripped"
