from typing import get_args

import pytest
from charms.grafana_agent.v0.cos_agent import ReceiverProtocol
from charms.tempo_k8s.v2.tracing import ReceiverProtocol as TracingReceiverProtocol
from scenario import Context, State

from charm import GrafanaAgentMachineCharm


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
