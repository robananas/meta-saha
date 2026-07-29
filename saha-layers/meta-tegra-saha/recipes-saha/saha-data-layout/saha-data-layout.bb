SUMMARY = "Saha persistent DATA filesystem policy and failure protection"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"
SRC_URI = " file://data.mount file://saha-data-prepare.service file://saha-data-prepare file://saha-data-layout.service file://saha-data-layout.sh file://var-log-journal.mount file://docker.conf file://daemon.json file://journald-data.conf file://saha-preload-sync file://saha-verify-data file://fstab "
inherit systemd
S = "${UNPACKDIR}"
SYSTEMD_SERVICE:${PN} = "data.mount saha-data-prepare.service saha-data-layout.service var-log-journal.mount"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"
RDEPENDS:${PN} = "e2fsprogs-e2fsck e2fsprogs-resize2fs util-linux-findmnt util-linux-mountpoint coreutils"
do_install() {
 install -d ${D}${systemd_system_unitdir} ${D}${libexecdir} ${D}${bindir} ${D}${sysconfdir}/docker ${D}${sysconfdir}/systemd/journald.conf.d ${D}${sysconfdir}/systemd/system/docker.service.d
 for unit in data.mount saha-data-prepare.service saha-data-layout.service var-log-journal.mount; do install -m 0644 ${UNPACKDIR}/$unit ${D}${systemd_system_unitdir}/$unit; done
 install -m 0755 ${UNPACKDIR}/saha-data-prepare ${D}${libexecdir}/saha-data-prepare
 install -m 0755 ${UNPACKDIR}/saha-data-layout.sh ${D}${libexecdir}/saha-data-layout
 install -m 0755 ${UNPACKDIR}/saha-preload-sync ${D}${bindir}/saha-preload-sync
 install -m 0755 ${UNPACKDIR}/saha-verify-data ${D}${bindir}/saha-verify-data
 install -m 0644 ${UNPACKDIR}/daemon.json ${D}${sysconfdir}/docker/daemon.json
 install -m 0644 ${UNPACKDIR}/docker.conf ${D}${sysconfdir}/systemd/system/docker.service.d/10-saha-data.conf
 install -m 0644 ${UNPACKDIR}/journald-data.conf ${D}${sysconfdir}/systemd/journald.conf.d/10-saha-data.conf
 install -d ${D}/data ${D}${localstatedir}/volatile/log/journal
 install -d ${D}${sysconfdir}
 cat ${UNPACKDIR}/fstab >> ${D}${sysconfdir}/fstab
}
FILES:${PN} += "/data ${sysconfdir}/systemd/system/docker.service.d ${localstatedir}/volatile/log/journal"
