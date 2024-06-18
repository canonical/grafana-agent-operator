from unittest.mock import patch

import pytest
import snap_management
from snap_management import _install_snap, install_ga_snap

snap_spec = {
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
    "classic": {
        "some-arch": {
            "name": "some-charm",
            "revision": "123",
        },
    },
}


class TestSnapInstall:

    @patch("snap_management.snap_lib.SnapCache")
    def test_install_snap(self, mocked_cache):
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

    @patch("snap_management._grafana_agent_snap_spec", snap_spec)
    @patch("snap_management.get_system_arch")
    @patch("snap_management._install_snap")
    @pytest.mark.parametrize(
        "classic, arch, expected",
        [
            (False, "amd64", snap_spec["strict"]["amd64"]),
            (False, "arm64", snap_spec["strict"]["arm64"]),
            (True, "some-arch", snap_spec["classic"]["some-arch"]),
        ],
    )
    def test_install_ga_snap(
        self, mocked_install_snap, mocked_get_system_arch, classic, arch, expected
    ):
        # Arrange
        mocked_get_system_arch.return_value = arch

        # Act
        install_ga_snap(classic=classic)

        # Assert
        mocked_get_system_arch.assert_called_once()
        mocked_install_snap.assert_called_once_with(
            name=expected["name"], revision=expected["revision"], classic=classic
        )
