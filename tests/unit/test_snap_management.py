from pathlib import Path
from unittest.mock import patch

import pytest
import snap_management
from snap_management import SnapManifest, SnapManifestError, SnapStoreArgument, install_snap

snap_manifest_file = Path(__file__).parent / "assets/snap_manifest.yaml"

snap_manifest_amd64 = [
    {
        "name": "grafana-agent",
        "install-type": "store",
        "revision": 22,
    },
    {
        "name": "another-snap",
        "install-type": "store",
        "channel": "edge",
    },
]

snap_manifest_arm123 = [
    {
        "name": "grafana-agent",
        "install-type": "store",
        "revision": 123,
    }
]

snap_manifest_amd64_parsed = {
    snap["name"]: SnapStoreArgument(**snap) for snap in snap_manifest_amd64
}


class TestSnapManifest:
    """Tests for the SnapManifest class."""

    @patch("snap_management.SnapManifest._get_parsed_manifest")
    def test_get_arch_with_given_arch(self, _mocked_get_parsed_manifest):
        expected_arch = "myarch"
        sm = SnapManifest("./", expected_arch)

        assert sm.arch == expected_arch

    @patch("snap_management.SnapManifest._get_parsed_manifest")
    def test_arch_detection(self, _mocked_get_parsed_manifest):
        expected_arch = "amd64"
        sm = SnapManifest("./", None)

        assert sm.arch == expected_arch

    @pytest.mark.parametrize(
        "arch, expected_manifest",
        [
            ("amd64", snap_manifest_amd64),
            ("arm123", snap_manifest_arm123),
        ],
    )
    @patch("snap_management.SnapManifest._get_parsed_manifest")
    def test_get_manifest(self, _mocked_get_parsed_manifest, arch, expected_manifest):
        sm = SnapManifest(snap_manifest_file, arch)

        manifest = sm._get_manifest()

        assert manifest == expected_manifest

    def test_get_manifest_file_does_not_exist(self):
        with pytest.raises(SnapManifestError):
            SnapManifest("non-existent-file", "amd64")

    @patch("snap_management.SnapManifest._get_parsed_manifest")
    def test_parse_manifest(self, _mocked_get_parsed_manifest):
        sm = SnapManifest("./", "amd64")

        actual_parsed = sm._parse_manifest(snap_manifest_amd64)

        assert actual_parsed == snap_manifest_amd64_parsed

    @patch("snap_management.SnapManifest._get_parsed_manifest")
    def test_parse_manifest_invalid_format(self, _mocked_get_parsed_manifest):
        sm = SnapManifest("./", "amd64")

        with pytest.raises(SnapManifestError):
            sm._parse_manifest([{}])

    @patch("snap_management.SnapManifest._get_parsed_manifest")
    def test_get_snap_argument(self, _mocked_get_parsed_manifest):
        name = "another-snap"
        expected_snap_args = snap_manifest_amd64_parsed[name]
        sm = SnapManifest("./", "amd64")
        sm._manifest = snap_manifest_amd64_parsed

        actual_snap_args = sm.get_snap_arguments(name)

        assert actual_snap_args == expected_snap_args

    @patch("snap_management.SnapManifest._get_parsed_manifest")
    def test_get_snap_argument_not_found(self, _mocked_get_parsed_manifest):
        sm = SnapManifest("./", "amd64")
        sm._manifest = {}

        with pytest.raises(KeyError):
            sm.get_snap_arguments("not-a-snap")


class TestSnapInstall:

    @patch("snap_management.snap_lib.SnapCache")
    def test_install_store_snap_with_revision(self, mocked_cache):
        name = "some-charm"
        revision = 123
        snap = mocked_cache()[name]
        snap_arguments = SnapStoreArgument(name=name, revision=revision)
        install_snap(snap_arguments)

        snap.ensure.assert_called_once_with(
            state=snap_management.snap_lib.SnapState.Present, revision=str(revision)
        )
        snap.hold.assert_called_once()
