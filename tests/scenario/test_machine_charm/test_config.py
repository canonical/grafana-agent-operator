# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest
from ops.testing import Context, State

import charm


@pytest.fixture
def placeholder_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


def test_config_log_level(placeholder_cfg_path):
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
        ctx = Context(charm_type=charm.GrafanaAgentMachineCharm, config={"log_level": "error"})
        out = ctx.run(ctx.on.start(), State())

    written_cfg = placeholder_cfg_path.read_text()
    assert written_cfg  # check nonempty

    assert out.unit_status.name == "blocked"
