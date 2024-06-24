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

# Log messages can be retrieved using juju debug-log
log = logging.getLogger(__name__)


# Map of the grafana-agent snap revision to install for given architectures and strict mode.
_grafana_agent_snap_spec = {
    "strict": {
        "amd64": {
            "name": "grafana-agent",
            "revision": "16",  # 0.35.0
        },
        "arm64": {
            "name": "grafana-agent",
            "revision": "23",  # 0.39.2
        },
    },
}


class SnapSpecError(Exception):
    """Custom exception type for errors related to the snap spec."""

    pass


def install_ga_snap(classic: bool = False):
    """Looks up system details and installs the appropriate grafana-agent snap revision."""
    arch = get_system_arch()
    confinement = "classic" if classic else "strict"
    try:
        snap_spec = _grafana_agent_snap_spec[confinement][arch]
    except KeyError as e:
        raise SnapSpecError(f"Snap spec not found for arch={arch} and confinement={confinement}") from e
    _install_snap(name=snap_spec["name"], revision=snap_spec["revision"], classic=classic)


def _install_snap(
    name: str,
    revision: str,
    classic: bool = False,
):
    """Install the given snap revision, holding it so it won't update."""
    cache = snap_lib.SnapCache()
    snap = cache[name]
    log.info(
        f"Ensuring {name} snap is installed at revision={revision}"
        f" with classic confinement={classic}"
    )
    snap.ensure(state=snap_lib.SnapState.Present, revision=revision, classic=classic)
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
