#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://juju.is/docs/sdk

"""Snap Installation Module.

Modified from https://github.com/canonical/k8s-operator/blob/main/charms/worker/k8s/src/snap.py
"""


import logging
import platform

import charms.operator_libs_linux.v2.snap as snap_lib
from charms.operator_libs_linux.v2.snap import SnapState

# Log messages can be retrieved using juju debug-log
log = logging.getLogger(__name__)


def install_snap(
    name: str,
    revision: str,
):
    """Install the given snap revision, holding it so it won't update."""
    cache = snap_lib.SnapCache()
    snap = cache[name]
    log.info(f"Ensuring {name} snap is installed at revision={revision}")
    snap.ensure(state=SnapState.Present, revision=revision)
    # TODO: should hold be an argument in the yaml?
    if revision:
        log.info(
            "Setting snap refresh for %s to hold=forever because revision is defined",
            name,
        )
        snap.hold()


def get_system_arch() -> str:
    """Returns the architecture of this machine, mapping some values to amd64 or arm64.

    If platform is x86_64 or amd64, it returns amd64.
    If platform is aarch64, arm64, armv8b, or armv8l, it returns arm64.
    """
    arch = platform.processor()
    if arch in ["x86_64", "amd64"]:
        arch = "amd64"
    elif arch in ["aarch64", "arm64", "armv8b", "armv8l"]:
        arch = "arm64"
    return arch
