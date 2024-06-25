from contextlib import nullcontext as does_not_raise
from unittest.mock import patch

import pytest
import snap_management
from snap_management import SnapSpecError, _install_snap, install_ga_snap

grafana_agent_snap_name = "grafana-agent"
snap_spec = {
    # (confinement, arch): revision
    ("strict", "amd64"): "16",
    ("strict", "arm64"): 42,  # Can be int or str
    ("classic", "some-arch"): "123",
}

minimal_snap_spec = {
    ("strict", "amd64"): "16",
}


@patch("snap_management.snap_lib.SnapCache")
def test_install_snap(mocked_cache):
    name = "some-charm"
    revision = "123"
    classic = False
    snap = mocked_cache()[name]
    _install_snap(name=name, revision=revision, classic=classic)

    snap.ensure.assert_called_once_with(
        state=snap_management.snap_lib.SnapState.Present,
        revision=str(revision),
        classic=classic,
    )
    snap.hold.assert_called_once()


@patch("snap_management._grafana_agent_snaps", snap_spec)
@patch("snap_management.get_system_arch")
@patch("snap_management._install_snap")
@pytest.mark.parametrize(
    "classic, arch, expected_revision",
    [
        (False, "amd64", snap_spec[("strict", "amd64")]),
        (False, "arm64", snap_spec[("strict", "arm64")]),
        (True, "some-arch", snap_spec[("classic", "some-arch")]),
    ],
)
def test_install_ga_snap(
    mocked_install_snap, mocked_get_system_arch, classic, arch, expected_revision
):
    # Arrange
    mocked_get_system_arch.return_value = arch

    # Act
    install_ga_snap(classic=classic)

    # Assert
    mocked_get_system_arch.assert_called_once()
    mocked_install_snap.assert_called_once_with(
        name=grafana_agent_snap_name, revision=str(expected_revision), classic=classic
    )


@patch("snap_management._grafana_agent_snaps", minimal_snap_spec)
@patch("snap_management.get_system_arch")
@patch("snap_management._install_snap")
@pytest.mark.parametrize(
    "classic, arch, context_raised",
    [
        (True, "amd64", pytest.raises(SnapSpecError)),
        (False, "arm64", pytest.raises(SnapSpecError)),
        (False, "amd64", does_not_raise()),
    ],
)
def test_install_ga_snap_validation_errors(
    mocked_install_snap, mocked_get_system_arch, classic, arch, context_raised
):
    # Arrange
    mocked_get_system_arch.return_value = arch

    # Act
    with context_raised:
        install_ga_snap(classic=classic)
