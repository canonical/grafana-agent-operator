# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from charms.grafana_agent.v0.cos_agent import (
    CosAgentPeersUnitData,
    COSAgentProvider,
    COSAgentRequirer,
)
from cosl.rules import generic_alert_groups
from ops.charm import CharmBase
from ops.framework import Framework
from ops.testing import Context, PeerRelation, State, SubordinateRelation

PROVIDER_NAME = "mock-principal"
PROM_RULE = """alert: HostCpuHighIowait
expr: avg by (instance) (rate(node_cpu_seconds_total{mode="iowait"}[5m])) * 100 > 10
for: 0m
labels:
  severity: warning
annotations:
  summary: Host CPU high iowait (instance {{ $labels.instance }})
  description: "CPU iowait > 10%. A high iowait means that you are disk or network bound.\n  VALUE = {{ $value }}\n  LABELS = {{ $labels }}"
"""
GRAFANA_DASH = """
{
  "title": "foo",
  "bar" : "baz"
}
"""


@pytest.fixture(autouse=True)
def patch_all(placeholder_cfg_path):
    with patch("subprocess.run", MagicMock()), patch(
        "grafana_agent.CONFIG_PATH", placeholder_cfg_path
    ), patch("socket.getfqdn", return_value="localhost"):
        yield


@pytest.fixture(autouse=True)
def snap_is_installed():
    with patch(
        "charm.GrafanaAgentMachineCharm._is_installed", new_callable=PropertyMock
    ) as mock_foo:
        mock_foo.return_value = True
        yield


PROVIDER_META = {
    "name": PROVIDER_NAME,
    "provides": {
        "cos-agent": {"interface": "cos_agent", "scope": "container"},
    },
}


class PrincipalProvider(CharmBase):
    _log_slots = ["charmed-kafka:logs"]

    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.gagent = COSAgentProvider(
            self,
            metrics_endpoints=[
                {"path": "/metrics", "port": 8080},
            ],
            metrics_rules_dir="./src/alert_rules/prometheus",
            logs_rules_dir="./src/alert_rules/loki",
            log_slots=self._log_slots,
            refresh_events=[self.on.cos_agent_relation_changed],
            tracing_protocols=["otlp_grpc", "otlp_http"],
        )


class BadPrincipalProvider(PrincipalProvider):
    _log_slots = 'charmed:oops-a-str-not-a-list'  # type: ignore


REQUIRER_META = {
    "name": "mock-subordinate",
    "requires": {
        "cos-agent": {"interface": "cos_agent", "scope": "container"},
    },
    "peers": {"peers": {"interface": "grafana_agent_replica"}},
}


class SubordinateRequirer(CharmBase):
    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.gagent = COSAgentRequirer(
            self,
            refresh_events=[self.on.cos_agent_relation_changed],
        )
        self.tracing = MagicMock()


def test_cos_agent_injects_generic_alerts():
    # GIVEN a cos-agent subordinate relation
    provider_ctx = Context(charm_type=PrincipalProvider, meta=PROVIDER_META)
    cos_agent = SubordinateRelation("cos-agent")

    # WHEN the relation_changed event fires
    state_out = provider_ctx.run(
        provider_ctx.on.relation_changed(relation=cos_agent, remote_unit=1),
        State(relations=[cos_agent]),
    )

    config = json.loads(
        state_out.get_relation(cos_agent.id).local_unit_data[CosAgentPeersUnitData.KEY]
    )
    # THEN the metrics_alert_rules groups should only contain the generic alert groups
    # NOTE: that we cannot simply test equality with generic_alert_groups since
    #       the name and labels are injected too
    def names_and_exprs(rules):
        return {(r["alert"], r["expr"]) for g in rules["groups"] for r in g["rules"]}
    assert (
        names_and_exprs(config["metrics_alert_rules"]) == names_and_exprs(generic_alert_groups.application_rules)
    )


@pytest.mark.parametrize("path,port,expected", [
    ("/metrics", 8080, "default"),
    ("/metrics/", 8080, "default"),
    ("/sub/metrics", 8080, "default"),
])
def test_cos_agent_renders_job_name_for_metrics_endpoints(path, port, expected):
    # GIVEN a principal charm specified some metrics endpoint (not scrape jobs)
    class SomeProvider(CharmBase):

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.gagent = COSAgentProvider(
                self,
                metrics_endpoints=[
                    {"path": path, "port": port},
                ],
            )

    # GIVEN a cos-agent subordinate relation
    provider_ctx = Context(charm_type=SomeProvider, meta=PROVIDER_META)
    cos_agent = SubordinateRelation("cos-agent")

    # WHEN the relation_changed event fires
    state_out = provider_ctx.run(
        provider_ctx.on.relation_changed(relation=cos_agent, remote_unit=1),
        State(relations=[cos_agent]),
    )

    config = json.loads(
        state_out.get_relation(cos_agent.id).local_unit_data[CosAgentPeersUnitData.KEY]
    )

    # THEN a scrape job is rendered
    assert len(config['metrics_scrape_jobs']) == 1

    # AND the job name is rendered automatically from the paths and ports provided
    job_dict = config['metrics_scrape_jobs'][0]
    assert "job_name" in job_dict
    # AND scrape spec is part of the job name
    assert job_dict["job_name"].endswith(expected)


def test_cos_agent_changed_no_remote_data():
    provider_ctx = Context(charm_type=PrincipalProvider, meta=PROVIDER_META)
    cos_agent = SubordinateRelation("cos-agent")

    state_out = provider_ctx.run(
        provider_ctx.on.relation_changed(relation=cos_agent, remote_unit=1),
        State(relations=[cos_agent]),
    )

    config = json.loads(
        state_out.get_relation(cos_agent.id).local_unit_data[CosAgentPeersUnitData.KEY]
    )

    # the cos_agent lib injects generic (HostHealth) alert rules and should be filtered for the test
    config["metrics_alert_rules"]["groups"] = [
        group
        for group in config["metrics_alert_rules"]["groups"]
        if "_HostHealth_" not in group["name"]
    ]

    assert config["metrics_alert_rules"] == {"groups": []}
    assert config["log_alert_rules"] == {}
    assert len(config["dashboards"]) == 1
    assert len(config["metrics_scrape_jobs"]) == 1
    assert config["log_slots"] == ["charmed-kafka:logs"]
    assert len(config["tracing_protocols"]) == 2


def test_subordinate_update():
    # step 2: gagent is notified that the principal has touched its relation data
    requirer_ctx = Context(charm_type=SubordinateRequirer, meta=REQUIRER_META)
    peer = PeerRelation("peers")
    config = {
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
        "tracing_protocols": ["otlp_http", "otlp_grpc"],
    }

    cos_agent1 = SubordinateRelation(
        "cos-agent",
        remote_app_name="mock-principal",
        remote_unit_data={"config": json.dumps(config)},
    )
    state_out1 = requirer_ctx.run(
        requirer_ctx.on.relation_changed(relation=cos_agent1, remote_unit=0),
        State(relations=[cos_agent1, peer]),
    )
    peer_out = state_out1.get_relations("peers")[0]
    peer_out_data = json.loads(
        peer_out.local_unit_data[f"{CosAgentPeersUnitData.KEY}-mock-principal/0"]
    )
    assert peer_out_data["unit_name"] == f"{PROVIDER_NAME}/0"
    assert peer_out_data["relation_id"] == str(cos_agent1.id)
    assert peer_out_data["relation_name"] == cos_agent1.endpoint

    # passthrough as-is
    assert peer_out_data["metrics_alert_rules"] == config["metrics_alert_rules"]
    assert peer_out_data["log_alert_rules"] == config["log_alert_rules"]
    assert peer_out_data["dashboards"] == config["dashboards"]

    # check that requirer side of the databag contains expected receivers
    receivers = json.loads(state_out1.get_relations("cos-agent")[0].local_unit_data["receivers"])
    assert len(receivers) == 2
    urls = [item["url"] for item in receivers]
    assert "localhost:4317" in urls
    assert "http://localhost:4318" in urls


def test_cos_agent_wrong_rel_data():
    # Step 1: principal charm is deployed and ends in "unknown" state
    provider_ctx = Context(charm_type=BadPrincipalProvider, meta=PROVIDER_META)
    cos_agent_rel = SubordinateRelation("cos-agent")
    state = State(relations=[cos_agent_rel])

    state_out = provider_ctx.run(
        provider_ctx.on.relation_changed(relation=cos_agent_rel, remote_unit=1), state
    )
    assert state_out.unit_status.name == "unknown"

    assert any(
        log.level == "ERROR" and "Invalid relation data provided:" in log.message
        for log in provider_ctx.juju_log
    )
