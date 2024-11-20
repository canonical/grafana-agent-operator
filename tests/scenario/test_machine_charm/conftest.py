# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import PropertyMock, patch

import pytest


@pytest.fixture
def placeholder_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@pytest.fixture()
def mock_config_path(placeholder_cfg_path):
    with patch("grafana_agent.CONFIG_PATH", placeholder_cfg_path):
        yield


@pytest.fixture(autouse=True)
def mock_snap():
    """Mock the charm's snap property so we don't access the host."""
    with patch("charm.GrafanaAgentMachineCharm.snap", new_callable=PropertyMock):
        yield


@pytest.fixture(autouse=True)
def mock_refresh():
    """Mock the refresh call so we don't access the host."""
    with patch("snap_management._install_snap", new_callable=PropertyMock):
        yield


CONFIG_MATRIX = [
    {"classic_snap": True},
    {"classic_snap": False},
]


@pytest.fixture(params=CONFIG_MATRIX)
def charm_config(request):
    return request.param
