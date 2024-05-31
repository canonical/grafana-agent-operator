#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://juju.is/docs/sdk

"""Snap Installation Module.

Modified from https://github.com/canonical/k8s-operator/blob/main/charms/worker/k8s/src/snap.py
"""

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union

import charms.operator_libs_linux.v2.snap as snap_lib
import yaml
from pydantic import BaseModel, Field, ValidationError, parse_obj_as
from typing_extensions import Annotated

# Log messages can be retrieved using juju debug-log
log = logging.getLogger(__name__)


class SnapFileArgument(BaseModel):
    """Structure to install a snap by file.

    Attributes:
        install_type (str): literal string defining this type
        name (str): The name of the snap after installed
        filename (Path): Path to the snap to locally install
        classic (bool): If it should be installed as a classic snap
        dangerous (bool): If it should be installed as a dangerouse snap
        devmode (bool): If it should be installed as with dev mode enabled
    """

    install_type: Literal["file"] = Field("file", alias="install-type", exclude=True)
    name: str = Field(exclude=True)
    filename: Optional[Path] = None
    classic: Optional[bool] = None
    devmode: Optional[bool] = None
    dangerous: Optional[bool] = None


class SnapStoreArgument(BaseModel):
    """Structure to install a snap by snapstore.

    Attributes:
        install_type (str): literal string defining this type
        name (str): The type of the request.
        state (SnapState): a `SnapState` to reconcile to.
        classic (bool): If it should be installed as a classic snap
        devmode (bool): If it should be installed as with dev mode enabled
        channel (bool): the channel to install from
        cohort (str): the key of a cohort that this snap belongs to
        revision (str): the revision of the snap to install
    """

    install_type: Literal["store"] = Field("store", alias="install-type", exclude=True)
    name: str = Field(exclude=True)
    classic: Optional[bool] = None
    devmode: Optional[bool] = None
    state: Optional[snap_lib.SnapState] = Field(snap_lib.SnapState.Present)
    channel: Optional[str] = None
    cohort: Optional[str] = None
    revision: Optional[str] = None


SnapArgument = Annotated[
    Union[SnapFileArgument, SnapStoreArgument], Field(discriminator="install_type")
]


class SnapManifestError(Exception):
    """Base class for snap management errors."""

    pass


class SnapManifest:
    """Manager for a manifest of snaps to install."""

    def __init__(self, manifest_path: Union[Path, str], arch: Optional[str] = None):
        """Initialize the snap manifest manager.

        Args:
            manifest_path: Path to the manifest file
            arch: The architecture to use for snap installation.  If omitted, the system arch will
                  be inferred.
        """
        if arch is None:
            arch = self._get_system_arch()
        self.arch = arch

        self._manifest_path = Path(manifest_path)
        self._manifest = self._get_parsed_manifest()

    @staticmethod
    def _get_system_arch():
        """Returns the architecture of this machine, using dpkg."""
        dpkg_arch = ["dpkg", "--print-architecture"]
        return subprocess.check_output(dpkg_arch).decode("UTF-8").strip()

    def _get_parsed_manifest(self) -> Dict[str, SnapArgument]:
        """Loads and parses the manifest file.

        Raises:
            SnapManifestError: when the manifest file cannot be loaded or parsed.

        Returns:
            A dict of SnapArguments keyed by their snap name
        """
        manifest_raw = self._get_manifest()
        return self._parse_manifest(manifest_raw)

    def _get_manifest(self) -> List[Dict]:
        """Loads the snap manifest file, returning the manifest for this architecture.

        Raises:
            SnapManifestError: when the manifest file cannot be loaded or parsed.

        Returns:
            A list of dicts describing snaps
        """
        if not self._manifest_path.exists():
            raise SnapManifestError(f"Failed to find file={self._manifest_path}")
        try:
            with self._manifest_path.open() as f:
                manifest = yaml.safe_load(f)
        except yaml.YAMLError as e:
            log.error("Failed to load manifest file=%s, %s", self._manifest_path, e)
            raise SnapManifestError(f"Failed to load manifest file={self._manifest_path}")

        manifest_this_arch = manifest.get(self.arch)
        if not (isinstance(manifest, dict) and manifest_this_arch):
            log.warning("Failed to find revision for arch=%s", self.arch)
            raise SnapManifestError(f"Failed to find revision for arch={self.arch}")

        return manifest_this_arch

    def _parse_manifest(self, manifest: List[Dict]) -> Dict[str, SnapArgument]:
        """Parses a manifest defined by a list of snap dicts, rendering them to SnapArguments."""
        try:
            manifest_parsed = {
                arg["name"]: parse_obj_as(SnapArgument, arg) for arg in manifest  # pyright: ignore
            }
        except (ValidationError, KeyError) as e:
            log.warning("Failed to validate args=%s (%s)", self.arch, e)
            raise SnapManifestError("Failed to validate snap args")

        return manifest_parsed

    def get_snap_arguments(self, name: str):
        """Returns a SnapArgument for the given snap name."""
        return self._manifest[name]


def install_snap(snap_arguments: SnapArgument):
    """Install the snap defined by a SnapArgument."""
    cache = snap_lib.SnapCache()
    snap = cache[snap_arguments.name]
    if isinstance(snap_arguments, SnapFileArgument) and snap.revision != "x1":
        snap_lib.install_local(**snap_arguments.dict(exclude_none=True))
    elif isinstance(snap_arguments, SnapStoreArgument):
        log.info(
            "Ensuring %s snap is installed with channel=%s, revision=%s",
            snap_arguments.name,
            snap_arguments.channel,
            snap_arguments.revision,
        )
        snap.ensure(**snap_arguments.dict(exclude_none=True))
        # TODO: should hold be an argument in the yaml?
        if snap_arguments.revision:
            log.info(
                "Setting snap refresh for %s to hold=forever because revision is defined",
                snap_arguments.name,
            )
            snap.hold()
