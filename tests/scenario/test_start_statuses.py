# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest
from ops.testing import Context, State, WaitingStatus

import charm

CHARM_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture
def placeholder_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@dataclasses.dataclass
class _MockProc:
    returncode: int = 0
    stdout: str = ""


def _subp_run_mock(*a, **kw):
    return _MockProc(0)


@pytest.fixture(autouse=True)
def patch_all(placeholder_cfg_path):
    with patch("subprocess.run", _subp_run_mock), patch(
        "grafana_agent.CONFIG_PATH", placeholder_cfg_path
    ):
        yield


def test_install():
    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    out = ctx.run(ctx.on.install(), State())

    assert out.unit_status == ("maintenance", "Installing grafana-agent snap")


def test_start_not_ready(placeholder_cfg_path):
    with patch("charm.GrafanaAgentMachineCharm.is_ready", False):
        ctx = Context(
            charm_type=charm.GrafanaAgentMachineCharm,
        )
        with ctx(ctx.on.start(), State()) as mgr:
            assert not mgr.charm.is_ready
            out = mgr.run()
            assert out.unit_status == WaitingStatus("waiting for agent to start")


def test_start(placeholder_cfg_path):
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
        ctx = Context(
            charm_type=charm.GrafanaAgentMachineCharm,
        )
        out = ctx.run(ctx.on.start(), State())

    written_cfg = placeholder_cfg_path.read_text()
    assert written_cfg  # check nonempty

    assert out.unit_status.name == "blocked"
