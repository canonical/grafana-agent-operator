from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from ops import pebble
from ops.testing import Container, Context, State

from charm import GrafanaAgentCharm


@pytest.fixture
def ctx():
    with charm_tracing_disabled():
        with patch("socket.getfqdn", new=lambda: "localhost"):
            yield Context(GrafanaAgentCharm)


@pytest.fixture
def base_state():
    yield State(
        leader=True,
        containers=[
            Container(
                "agent",
                can_connect=True,
                # set it to inactive so we can detect when an event has caused it to start
                service_statuses={"agent": pebble.ServiceStatus.INACTIVE},
            )
        ],
    )
