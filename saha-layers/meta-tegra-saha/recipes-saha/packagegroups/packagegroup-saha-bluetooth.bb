DESCRIPTION = "Bluetooth stack and Jetson integrated Bluetooth support"

LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    bluez5 \
    tegra-bluetooth \
    saha-ble-identity \
    saha-bt-wifi-provision \
"
