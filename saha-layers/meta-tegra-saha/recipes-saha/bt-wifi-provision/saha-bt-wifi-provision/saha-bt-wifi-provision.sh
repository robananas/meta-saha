#!/bin/sh
set -eu

PYTHONPATH="@libdir@/saha-bt-wifi-provision${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONPATH
exec python3 @libdir@/saha-bt-wifi-provision/saha-bt-wifi-provision.py "$@"
