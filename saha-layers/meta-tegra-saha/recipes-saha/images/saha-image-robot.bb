DESCRIPTION = "Saha robot image for tegra"

require saha-image-base.bb

CORE_IMAGE_BASE_INSTALL += "packagegroup-saha-ros2"
