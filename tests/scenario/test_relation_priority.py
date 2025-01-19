# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import patch

import pytest
from cosl import LZMABase64
from ops.testing import Context, PeerRelation, State, SubordinateRelation

import charm
from tests.scenario.helpers import set_run_out


@pytest.fixture
def mock_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@pytest.fixture(autouse=True)
def patch_all(placeholder_cfg_path):
    with patch("grafana_agent.CONFIG_PATH", placeholder_cfg_path):
        yield


@patch("charm.subprocess.run")
def test_no_relations(mock_run, charm_config):
    set_run_out(mock_run, 0)
    state = State(config=charm_config)
    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    with ctx(ctx.on.start(), state) as mgr:
        mgr.run()
        assert not mgr.charm._cos.dashboards
        assert not mgr.charm._cos.logs_alerts
        assert not mgr.charm._cos.metrics_alerts
        assert not mgr.charm._cos.metrics_jobs
        assert not mgr.charm._cos.snap_log_endpoints


@patch("charm.subprocess.run")
def test_juju_info_relation(mock_run, charm_config):
    set_run_out(mock_run, 0)
    state = State(
        relations=[
            SubordinateRelation(
                "juju-info", remote_unit_data={"config": json.dumps({"subordinate": True})}
            )
        ],
        config=charm_config,
    )
    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    with ctx(ctx.on.start(), state) as mgr:
        mgr.run()
        assert not mgr.charm._cos.dashboards
        assert not mgr.charm._cos.logs_alerts
        assert not mgr.charm._cos.metrics_alerts
        assert not mgr.charm._cos.metrics_jobs
        assert not mgr.charm._cos.snap_log_endpoints


@patch("charm.subprocess.run")
def test_cos_machine_relation(mock_run, charm_config):
    set_run_out(mock_run, 0)

    cos_agent_data = {
        "config": json.dumps(
            {
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "mock-principal_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["charmed-kafka:logs"],
            }
        )
    }

    peer_data = {
        "config": json.dumps(
            {
                "unit_name": "foo",
                "relation_id": "2",
                "relation_name": "peers",
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [LZMABase64.compress('{"very long": "dashboard"}')],
            }
        )
    }

    state = State(
        relations=[
            SubordinateRelation(
                "cos-agent",
                remote_app_name="mock-principal",
                remote_unit_data=cos_agent_data,
            ),
            PeerRelation("peers", peers_data={1: peer_data}),
        ],
        config=charm_config,
    )
    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    with ctx(ctx.on.start(), state) as mgr:
        mgr.run()
        assert mgr.charm._cos.dashboards
        assert mgr.charm._cos.snap_log_endpoints
        assert not mgr.charm._cos.logs_alerts
        assert not mgr.charm._cos.metrics_alerts
        assert mgr.charm._cos.metrics_jobs


@patch("charm.subprocess.run")
def test_both_relations(mock_run, charm_config):
    set_run_out(mock_run, 0)

    cos_agent_data = {
        "config": json.dumps(
            {
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "mock-principal_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["charmed-kafka:logs"],
            }
        )
    }

    peer_data = {
        "config": json.dumps(
            {
                "unit_name": "foo",
                "relation_id": "2",
                "relation_name": "peers",
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [LZMABase64.compress('{"very long": "dashboard"}')],
            }
        )
    }

    state = State(
        relations=[
            SubordinateRelation(
                "cos-agent",
                remote_app_name="remote-cos-agent",
                remote_unit_data=cos_agent_data,
            ),
            SubordinateRelation("juju-info", remote_app_name="remote-juju-info"),
            PeerRelation("peers", peers_data={1: peer_data}),
        ],
        config=charm_config,
    )
    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    with ctx(ctx.on.start(), state) as mgr:
        mgr.run()
        assert mgr.charm._cos.dashboards
        assert mgr.charm._cos.snap_log_endpoints
        assert not mgr.charm._cos.logs_alerts
        assert not mgr.charm._cos.metrics_alerts
        assert mgr.charm._cos.metrics_jobs
