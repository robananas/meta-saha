SUMMARY = "Default Home Assistant configuration for Saha devices"
DESCRIPTION = "Installs a first-boot Home Assistant config template with \
SmartIR, Xiaomi Home, and HACS custom components plus Matter integration defaults."
LICENSE = "MIT & Apache-2.0"
LIC_FILES_CHKSUM = " \
    file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302 \
    file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10 \
"

PV = "1.0"

SMARTIR_REPO ?= "git://github.com/smartHomeHub/SmartIR.git;protocol=https;nobranch=1;name=smartir;destsuffix=git/smartir"
XIAOMI_HOME_REPO ?= "git://github.com/XiaoMi/ha_xiaomi_home.git;protocol=https;nobranch=1;name=xiaomi;destsuffix=git/xiaomi_home"
HACS_REPO ?= "git://github.com/hacs/integration.git;protocol=https;nobranch=1;name=hacs;destsuffix=git/hacs"
SMARTIR_SRCREV ?= "878df57d82cca1a458fab2de491de3dd6e670771"
XIAOMI_HOME_SRCREV ?= "001af5384a66dddb6e45f60bbeee6e536c236af4"
HACS_SRCREV ?= "c0dfd8b44297c3673c21973e2539375a53687a9c"
SRCREV_FORMAT = "smartir_xiaomi_hacs"

SRC_URI = " \
    ${SMARTIR_REPO} \
    ${XIAOMI_HOME_REPO} \
    ${HACS_REPO} \
    file://configuration.yaml \
    file://ui-lovelace.yaml \
    file://automations.yaml \
    file://scenes.yaml \
    file://scripts.yaml \
    file://secrets.yaml \
    file://packages/tv_power.yaml \
    file://smartir-codes/climate/1084.json \
    file://smartir-codes/media_player/1380.json \
    file://install-custom-components.sh \
"

SRCREV_smartir = "${SMARTIR_SRCREV}"
SRCREV_xiaomi = "${XIAOMI_HOME_SRCREV}"
SRCREV_hacs = "${HACS_SRCREV}"

DEPENDS += "git-native"

S = "${UNPACKDIR}"

do_install() {
    config_dir=${D}${datadir}/saha/homeassistant/config-default

    install -d "${config_dir}/packages"
    install -m 0644 ${UNPACKDIR}/configuration.yaml ${config_dir}/configuration.yaml
    install -m 0644 ${UNPACKDIR}/ui-lovelace.yaml ${config_dir}/ui-lovelace.yaml
    install -m 0644 ${UNPACKDIR}/automations.yaml ${config_dir}/automations.yaml
    install -m 0644 ${UNPACKDIR}/scenes.yaml ${config_dir}/scenes.yaml
    install -m 0644 ${UNPACKDIR}/scripts.yaml ${config_dir}/scripts.yaml
    install -m 0644 ${UNPACKDIR}/secrets.yaml ${config_dir}/secrets.yaml
    install -m 0644 ${UNPACKDIR}/packages/tv_power.yaml ${config_dir}/packages/tv_power.yaml

    install -d ${config_dir}/custom_components
    sh ${UNPACKDIR}/install-custom-components.sh \
        ${UNPACKDIR}/git \
        ${config_dir}/custom_components \
        ${UNPACKDIR}/smartir-codes
}

FILES:${PN} = " \
    ${datadir}/saha/homeassistant/config-default \
"
