DESCRIPTION = "Bluetooth stack and Jetson integrated Bluetooth support"

LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    bluez5 \
    tegra-bluetooth \
    saha-bt-wifi-provision \
"

RDEPENDS:${PN}:append:p3768-0000-p3767-0000 = " kernel-module-rtk-btusb"
