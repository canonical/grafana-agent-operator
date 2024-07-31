# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
import inspect
from pathlib import Path
from unittest.mock import patch

import charm
import pytest
import yaml
from scenario import Context, State

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


@pytest.fixture
def charm_meta() -> dict:
    charm_source_path = Path(inspect.getfile(charm.GrafanaAgentMachineCharm))
    charm_root = charm_source_path.parent.parent

    raw_meta = (charm_root / "metadata").with_suffix(".yaml").read_text()
    return yaml.safe_load(raw_meta)


def test_install(charm_meta, vroot):
    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
        meta=charm_meta,
        charm_root=vroot,
    )
    out = ctx.run(state=State(), event="install")

    assert out.unit_status == ("maintenance", "Installing grafana-agent snap")


def test_start_not_ready(charm_meta, vroot, placeholder_cfg_path):
    with patch("charm.GrafanaAgentMachineCharm.is_ready", False):
        ctx = Context(
            charm_type=charm.GrafanaAgentMachineCharm,
            meta=charm_meta,
            charm_root=vroot,
        )
        with ctx.manager(state=State(), event="start") as mgr:
            assert not mgr.charm.is_ready
    assert mgr.output.unit_status == ("waiting", "waiting for agent to start")


def test_start(charm_meta, vroot, placeholder_cfg_path):
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
        ctx = Context(
            charm_type=charm.GrafanaAgentMachineCharm,
            meta=charm_meta,
            charm_root=vroot,
        )
        out = ctx.run(state=State(), event="start")

    written_cfg = placeholder_cfg_path.read_text()
    assert written_cfg  # check nonempty

    assert out.unit_status.name == "blocked"
