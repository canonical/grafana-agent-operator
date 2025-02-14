# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import pytest
from ops.testing import Context, PeerRelation, State, SubordinateRelation

import charm


@pytest.fixture(autouse=True)
def use_mock_config_path(mock_config_path):
    # Use the common mock_config_path fixture from conftest.py
    yield


def test_juju_info_and_cos_agent(charm_config):
    cos_agent_data = {
        "config": json.dumps(
            {
                "subordinate": True,
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "hardware-observer_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["foo:bar"],
            }
        )
    }

    cos_agent_relation = SubordinateRelation(
        "cos-agent", remote_app_name="hardware-observer", remote_unit_data=cos_agent_data
    )

    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    state = State(
        relations=[
            cos_agent_relation,
            SubordinateRelation("juju-info", remote_app_name="remote-juju-info"),
            PeerRelation("peers"),
        ],
        config=charm_config,
    )
    with ctx(ctx.on.relation_changed(cos_agent_relation), state) as mgr:
        mgr.run()

        assert len(mgr.charm._cos.dashboards) == 1
        assert len(mgr.charm._cos.snap_log_endpoints) == 1
        assert not mgr.charm._cos.logs_alerts
        assert not mgr.charm._cos.metrics_alerts
        assert len(mgr.charm._cos.metrics_jobs) == 1


def test_two_cos_agent_relations(charm_config):
    cos_agent_primary_data = {
        "config": json.dumps(
            {
                "subordinate": False,
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "primary_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["foo:bar"],
            }
        )
    }

    cos_agent_subordinate_data = {
        "config": json.dumps(
            {
                "subordinate": True,
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "subordinate_0", "path": "/metrics", "port": "8081"}
                ],
                "log_slots": ["oh:snap"],
            }
        )
    }

    cos_agent_primary_relation = SubordinateRelation(
        "cos-agent", remote_app_name="primary", remote_unit_data=cos_agent_primary_data
    )
    cos_agent_subordinate_relation = SubordinateRelation(
        "cos-agent", remote_app_name="subordinate", remote_unit_data=cos_agent_subordinate_data
    )

    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    state = State(
        relations=[
            cos_agent_primary_relation,
            cos_agent_subordinate_relation,
            PeerRelation("peers"),
        ],
        config=charm_config,
    )
    out_state = ctx.run(ctx.on.relation_changed(relation=cos_agent_primary_relation), state)

    with ctx(ctx.on.relation_changed(relation=cos_agent_subordinate_relation), out_state) as mgr:
        mgr.run()

        assert len(mgr.charm._cos.dashboards) == 2
        assert len(mgr.charm._cos.snap_log_endpoints) == 2
        assert not mgr.charm._cos.logs_alerts
        assert not mgr.charm._cos.metrics_alerts
        assert len(mgr.charm._cos.metrics_jobs) == 2
