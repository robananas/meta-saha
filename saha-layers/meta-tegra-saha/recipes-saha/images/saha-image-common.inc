LICENSE = "MIT"

inherit core-image

IMAGE_FEATURES += "ssh-server-openssh"
CORE_IMAGE_BASE_INSTALL += "packagegroup-saha-base"
CORE_IMAGE_BASE_INSTALL += "packagegroup-saha-network"
CORE_IMAGE_BASE_INSTALL += "packagegroup-saha-bluetooth"
CORE_IMAGE_BASE_INSTALL += "${@'packagegroup-saha-systemd' if d.getVar('VIRTUAL-RUNTIME_init_manager') == 'systemd' else ''}"
TOOLCHAIN_HOST_TASK += "nativesdk-packagegroup-cuda-sdk-host"

disable_conflicting_networkd_wait_online() {
    rm -f \
        ${IMAGE_ROOTFS}${sysconfdir}/systemd/system/network-online.target.wants/systemd-networkd-wait-online.service \
        ${IMAGE_ROOTFS}${systemd_system_unitdir}/network-online.target.wants/systemd-networkd-wait-online.service
}
ROOTFS_POSTPROCESS_COMMAND += "disable_conflicting_networkd_wait_online;"

inherit nopackages
