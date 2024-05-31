# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from typing import Type
from unittest.mock import PropertyMock, patch

import charm
import grafana_agent
import pytest
from ops import UnknownStatus, WaitingStatus
from ops.testing import CharmType
from scenario import Context, State

from tests.scenario.helpers import get_charm_meta


@pytest.fixture(params=["lxd"])
def substrate(request):
    return request.param


@pytest.fixture
def charm_type(substrate) -> Type[CharmType]:
    return {"lxd": charm.GrafanaAgentMachineCharm}[substrate]


@pytest.fixture
def mock_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@dataclasses.dataclass
class _MockProc:
    returncode: int = 0
    stdout = ""


def _subp_run_mock(*a, **kw):
    return _MockProc(0)


@pytest.fixture(autouse=True)
def patch_all(substrate, mock_cfg_path):
    grafana_agent.CONFIG_PATH = mock_cfg_path
    with patch("subprocess.run", _subp_run_mock):
        yield


@pytest.fixture()
def mock_snap():
    """Mock the charm's snap property so we don't access the host."""
    with patch(
        "charm.GrafanaAgentMachineCharm.snap", new_callable=PropertyMock
    ) as mocked_property:
        mock_snap = mocked_property.return_value
        # Mock the .present property of the snap object so the start event doesn't try to configure
        # anything
        mock_snap.present = False
        yield


@patch("charm.SnapManifest._get_system_arch", return_value="amd64")
def test_install(_mock_manifest_get_system_arch, charm_type, substrate, vroot, mock_snap):
    context = Context(
        charm_type,
        meta=get_charm_meta(charm_type),
        charm_root=vroot,
    )
    out = context.run("install", State())

    if substrate == "lxd":
        assert out.unit_status == ("maintenance", "Installing grafana-agent snap")

    else:
        assert out.unit_status == ("unknown", "")


def test_start(charm_type, substrate, vroot, mock_snap):
    context = Context(
        charm_type,
        meta=get_charm_meta(charm_type),
        charm_root=vroot,
    )
    out = context.run("start", State())

    if substrate == "lxd":
        assert not grafana_agent.CONFIG_PATH.exists(), "config file written on start"
        assert out.unit_status == WaitingStatus("waiting for agent to start")

    else:
        assert out.unit_status == UnknownStatus()
