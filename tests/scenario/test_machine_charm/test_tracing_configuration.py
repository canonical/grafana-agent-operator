from typing import get_args
from unittest.mock import patch

import pytest
import yaml
from charms.grafana_agent.v0.cos_agent import ReceiverProtocol
from charms.tempo_coordinator_k8s.v0.tracing import ReceiverProtocol as TracingReceiverProtocol
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from scenario import Context, Relation, State, SubordinateRelation

from charm import GrafanaAgentMachineCharm
from lib.charms.grafana_agent.v0.cos_agent import (
    CosAgentProviderUnitData,
    Receiver,
)
from lib.charms.tempo_coordinator_k8s.v0.tracing import TracingProviderAppData


def test_cos_agent_receiver_protocols_match_with_tracing():
    assert set(get_args(ReceiverProtocol)) == set(get_args(TracingReceiverProtocol))


@pytest.mark.parametrize("protocol", get_args(TracingReceiverProtocol))
def test_always_enable_config_variables_are_generated_for_tracing_protocols(
    protocol, vroot, mock_config_path, charm_config
):
    context = Context(
        charm_type=GrafanaAgentMachineCharm,
        charm_root=vroot,
    )
    state = State(
        config={f"always_enable_{protocol}": True, **charm_config},
        leader=True,
        relations=[],
    )
    with context.manager("config-changed", state) as mgr:
        charm: GrafanaAgentMachineCharm = mgr.charm
        assert protocol in charm.requested_tracing_protocols


@pytest.mark.parametrize(
    "sampling_config",
    (
        {
            "always_enable_otlp_http": True,
        },
        {
            "always_enable_otlp_http": True,
            "tracing_sample_rate_charm": 23.0,
            "tracing_sample_rate_workload": 13.13,
            "tracing_sample_rate_error": 42.42,
        },
    ),
)
def test_tracing_sampling_config_is_present(
    vroot, placeholder_cfg_path, mock_config_path, sampling_config
):
    # GIVEN a tracing relation over the tracing-provider endpoint and one over tracing
    context = Context(
        charm_type=GrafanaAgentMachineCharm,
        charm_root=vroot,
    )
    tracing_provider = SubordinateRelation(
        "cos-agent",
        remote_unit_data=CosAgentProviderUnitData(
            metrics_alert_rules={},
            log_alert_rules={},
            metrics_scrape_jobs=[],
            log_slots=[],
            dashboards=[],
            subordinate=True,
            tracing_protocols=["otlp_http", "otlp_grpc"],
        ).dump(),
    )
    tracing = Relation(
        "tracing",
        remote_app_data=TracingProviderAppData(
            receivers=[
                Receiver(protocol={"name": "otlp_grpc", "type": "grpc"}, url="http:foo.com:1111"),
                Receiver(protocol={"name": "otlp_http", "type": "http"}, url="http://localhost:1112"),
            ]
        ).dump(),
    )

    state = State(leader=True, relations=[tracing, tracing_provider], config=sampling_config)
    # WHEN we process any setup event for the relation
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
        context.run("config_changed", state)

    yml = yaml.safe_load(placeholder_cfg_path.read_text())

    assert yml["traces"]["configs"][0]["tail_sampling"]
