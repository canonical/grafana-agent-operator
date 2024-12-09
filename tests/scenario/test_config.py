# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest
import yaml
from ops.testing import Context, State

import charm
from ops import BlockedStatus

@pytest.fixture(autouse=True)
def patch_all(placeholder_cfg_path):
    with patch("grafana_agent.CONFIG_PATH", placeholder_cfg_path):
        yield


@pytest.mark.parametrize("log_level", ("debug", "info", "warn", "error"))
def test_valid_config_log_level(placeholder_cfg_path, log_level):
    """Asserts that all valid log_levels set the correct config"""
    # GIVEN a GrafanaAgentMachineCharm
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
        ctx = Context(charm_type=charm.GrafanaAgentMachineCharm)
        # WHEN the config option for log_level is set to a VALID option
        ctx.run(ctx.on.start(), State(config={"log_level": log_level}))

    # THEN the config file has the correct server:log_level field
    yaml_cfg = yaml.safe_load(placeholder_cfg_path.read_text())
    assert yaml_cfg["server"]["log_level"] == log_level


@patch("charm.GrafanaAgentMachineCharm.is_ready", True)
def test_invalid_config_log_level(placeholder_cfg_path):
    """Asserts that an invalid log_level sets Blocked status"""
    # GIVEN a GrafanaAgentMachineCharm
    ctx = Context(charm_type=charm.GrafanaAgentMachineCharm)
    with ctx(ctx.on.start(), State(config={"log_level": "foo"})) as mgr:
        # WHEN the config option for log_level is set to an invalid option
        mgr.run()
        # THEN a warning Juju debug-log is created
        assert any(
            log.level == "WARNING" and "log_level must be one of" in log.message
            for log in ctx.juju_log
        )
        # AND the charm goes into blocked status
        assert isinstance(mgr.charm.unit.status, BlockedStatus)
    # AND the config file defaults the server:log_level field to "info"
    yaml_cfg = yaml.safe_load(placeholder_cfg_path.read_text())
    assert yaml_cfg["server"]["log_level"] == "info"
