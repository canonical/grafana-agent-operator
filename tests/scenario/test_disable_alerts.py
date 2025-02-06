# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import pytest
from ops.testing import Context, PeerRelation, Relation, State, SubordinateRelation

import charm


@pytest.fixture(autouse=True)
def use_mock_config_path(mock_config_path):
    # Use the common mock_config_path fixture from conftest.py
    yield


def test_forward_alert_rules_toggle():
    cos_agent_data = {
        "config": json.dumps(
            {
                "subordinate": True,
                "metrics_alert_rules": {"groups": "alert_foo"},
                "log_alert_rules": {"groups": "alert_bar"},
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

    prometheus_relation = Relation(
        endpoint="send-remote-write",
        remote_app_name="prometheus",
        local_unit_data={"remote_write": json.dumps({"url": "http://1.2.3.4/api/v1/write"})},
    )

    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    state = State(
        relations=[
            cos_agent_relation,
            prometheus_relation,
            SubordinateRelation("juju-info", remote_app_name="remote-juju-info"),
            PeerRelation("peers"),
        ],
        config={"forward_alert_rules": True},
    )
    with ctx(ctx.on.relation_changed(cos_agent_relation), state) as mgr:
        output_state = mgr.run()
        assert mgr.charm._cos.logs_alerts
        assert mgr.charm._cos.metrics_alerts

    with ctx(ctx.on.config_changed(), state) as mgr:
        prometheus_relation_out = output_state.get_relation(prometheus_relation.id)
        print("+++")
        print(prometheus_relation_out)
