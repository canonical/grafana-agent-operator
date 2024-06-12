from unittest.mock import patch

import snap_management
from snap_management import install_snap


class TestSnapInstall:

    @patch("snap_management.snap_lib.SnapCache")
    def test_install_store_snap_with_revision(self, mocked_cache):
        name = "some-charm"
        revision = "123"
        snap = mocked_cache()[name]
        install_snap(name=name, revision=revision)

        snap.ensure.assert_called_once_with(
            state=snap_management.snap_lib.SnapState.Present, revision=str(revision)
        )
        snap.hold.assert_called_once()
