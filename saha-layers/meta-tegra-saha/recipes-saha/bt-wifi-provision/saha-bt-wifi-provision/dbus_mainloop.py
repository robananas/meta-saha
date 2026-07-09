#!/usr/bin/env python3
"""dbus-python main loop helpers without requiring python3-pygobject."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import time
from typing import Callable

import dbus

logger = logging.getLogger("saha-bt-wifi-provision")

_glib = None


def _load_glib() -> ctypes.CDLL:
    global _glib
    if _glib is not None:
        return _glib

    lib_name = ctypes.util.find_library("glib-2.0")
    if not lib_name:
        raise RuntimeError("glib-2.0 library not found")

    _glib = ctypes.CDLL(lib_name)
    _glib.g_main_context_default.restype = ctypes.c_void_p
    _glib.g_main_context_pending.argtypes = [ctypes.c_void_p]
    _glib.g_main_context_pending.restype = ctypes.c_int
    _glib.g_main_context_iteration.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _glib.g_main_context_iteration.restype = ctypes.c_int
    return _glib


def setup_dbus_main_loop() -> str:
    """Attach dbus-python to a supported main loop before exporting objects."""
    try:
        from dbus.mainloop.glib import DBusGMainLoop

        DBusGMainLoop(set_as_default=True)
        logger.info("using DBusGMainLoop (dbus-glib)")
        return "glib"
    except Exception as exc:
        logger.warning("DBusGMainLoop unavailable (%s), falling back to NULL_MAIN_LOOP", exc)

    dbus.set_default_main_loop(dbus.mainloop.NULL_MAIN_LOOP)
    logger.info("using NULL_MAIN_LOOP with manual dbus dispatch")
    return "null"


def _connection_candidates(bus: dbus.SystemBus) -> list[object]:
    candidates: list[object] = []
    for attr in ("connection", "_connection", "_dbus_connection"):
        value = getattr(bus, attr, None)
        if value is not None and value is not bus and value not in candidates:
            candidates.append(value)
    if bus not in candidates:
        candidates.append(bus)
    return candidates


def dispatch_dbus(bus: dbus.SystemBus, timeout_ms: int = 200) -> None:
    for candidate in _connection_candidates(bus):
        dispatch = getattr(candidate, "read_write_dispatch", None)
        if callable(dispatch):
            dispatch(timeout_ms)
            return
        flush = getattr(candidate, "flush", None)
        if callable(flush):
            flush()
            return
    raise RuntimeError("unable to dispatch dbus events on this python-dbus version")


def iterate_main_loop(bus: dbus.SystemBus, mode: str, timeout_ms: int = 200) -> None:
    if mode == "glib":
        glib = _load_glib()
        context = glib.g_main_context_default()
        while glib.g_main_context_pending(context):
            glib.g_main_context_iteration(context, False)
        time.sleep(timeout_ms / 1000.0)
        return

    dispatch_dbus(bus, timeout_ms)


def run_until(bus: dbus.SystemBus, mode: str, should_continue: Callable[[], bool]) -> None:
    while should_continue():
        iterate_main_loop(bus, mode)
