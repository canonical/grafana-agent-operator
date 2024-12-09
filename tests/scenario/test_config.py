# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest
import yaml
from ops.testing import Context, State

import charm


@pytest.fixture(autouse=True)
def patch_all(placeholder_cfg_path):
    with patch("grafana_agent.CONFIG_PATH", placeholder_cfg_path):
        yield


@pytest.mark.parametrize("log_level", ("debug", "info", "warn", "error"))
def test_config_log_level(placeholder_cfg_path, log_level):
    # GIVEN a GrafanaAgentMachineCharm
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
        ctx = Context(charm_type=charm.GrafanaAgentMachineCharm)
        # WHEN the config option for log_level is set to a VALID option
        ctx.run(ctx.on.start(), State(config={"log_level": log_level}))

    # THEN the config file has the correct server:log_level field
    yaml_cfg = yaml.safe_load(placeholder_cfg_path.read_text())
    assert yaml_cfg["server"]["log_level"] == log_level


def test_default_config_log_level(placeholder_cfg_path):
    # GIVEN a GrafanaAgentMachineCharm
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
        ctx = Context(charm_type=charm.GrafanaAgentMachineCharm)
        # WHEN the config option for log_level is set to an INVALID option
        ctx.run(ctx.on.start(), State(config={"log_level": "foo"}))

        # THEN Juju debug-log is created with WARNING level
        found = False
        for log in ctx.juju_log:
            if (
                "WARNING" == log.level
                and "Invalid loglevel: foo given, debug/info/warn/error allowed." in log.message
            ):
                found = True
                break
        assert found is True

    # AND the config file defaults the server:log_level field to "info"
    yaml_cfg = yaml.safe_load(placeholder_cfg_path.read_text())
    assert yaml_cfg["server"]["log_level"] == "info"
