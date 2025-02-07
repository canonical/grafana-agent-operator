# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import pytest
from ops.testing import Context, PeerRelation, Relation, State, SubordinateRelation

import charm


@pytest.mark.parametrize("forwarding", (True, False))
def test_forward_alert_rules(mock_config_path, forwarding):
    # GIVEN these relations
    cos_agent_data = {
        "config": json.dumps(
            {
                "subordinate": True,
                "metrics_alert_rules": {"groups": [{"name": "foo", "rules": []}]},
                "log_alert_rules": {"groups": [{"name": "bar", "rules": []}]},
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
    )
    state = State(
        leader=True,
        relations=[
            cos_agent_relation,
            prometheus_relation,
            SubordinateRelation("juju-info", remote_app_name="remote-juju-info"),
            PeerRelation("peers"),
        ],
        config={"forward_alert_rules": forwarding},
    )
    # WHEN the charm receives a cos-agent-relation-changed event
    ctx = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
    )
    with ctx(ctx.on.relation_changed(cos_agent_relation), state) as mgr:
        output_state = mgr.run()
        # THEN the charm can access the alerts
        assert mgr.charm._cos.logs_alerts
        assert mgr.charm._cos.metrics_alerts

    # AND THEN the charm forwards the remote_write config to the prom relation IF forwarding
    prometheus_relation_out = output_state.get_relation(prometheus_relation.id)
    if forwarding:
        assert prometheus_relation_out.local_app_data.get("alert_rules") != "{}"
    else:
        assert prometheus_relation_out.local_app_data.get("alert_rules") == "{}"
