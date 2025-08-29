# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import List

import pytest
from juju.errors import JujuError
from pytest_operator.plugin import OpsTest

agent = SimpleNamespace(name="agent")
hwo = SimpleNamespace(
    entity_url="hardware-observer",
    application_name="hwo",
    series="jammy",
    channel="stable",
)
principal = SimpleNamespace(charm="ubuntu", name="principal")

logger = logging.getLogger(__name__)

topology_labels = {
    "juju_application",
    # "juju_charm",  # juju_charm is present in the grafana agent's self scrape only
    "juju_model",
    "juju_model_uuid",
    "juju_unit",
}


async def ssh_units(ops_test, app_name: str, command: str) -> List[str]:
    """Run a command in all units of the given apps and return all the outputs."""
    units: list = ops_test.model.applications[app_name].units
    try:
        return [await unit.ssh(command) for unit in units]
    except JujuError as e:
        pytest.fail(f"Failed to run ssh command '{command}' in {app_name}: {e.message}")


async def test_setup_env(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, grafana_agent_charm):
    assert ops_test.model
    # Principal
    await ops_test.model.deploy(
        principal.charm, application_name=principal.name, num_units=2, series="jammy"
    )

    # Workaround: `charmcraft pack` produces two files, but `ops_test.build_charm` returns the
    # first one. Since primary is jammy, we know we need to deploy the jammy grafana agent charm,
    # otherwise we'd get an error such as:
    #   ImportError: libssl.so.1.1: cannot open shared object file: No such file or directory
    jammy_charm_path = grafana_agent_charm.parent / "grafana-agent_ubuntu@22.04-amd64.charm"

    # Subordinate
    await ops_test.model.deploy(
        jammy_charm_path, application_name=agent.name, num_units=0, series="jammy"
    )

    # Hardware Observer
    await ops_test.model.deploy(**vars(hwo))

    # Placeholder for o11y relations (otherwise grafana agent charm is in blocked status)
    await ops_test.model.deploy(
        "grafana-cloud-integrator",
        application_name="gci",
        num_units=1,
        series="jammy",
        channel="2/edge",
    )

    # grafana agent is in 'unknown' status until related, and grafana-cloud-integrator is in
    # 'blocked' until grafana cloud credentials are provided, so wait only for the principal.
    await ops_test.model.wait_for_idle(apps=[principal.name])


@pytest.mark.abort_on_fail
async def test_service(ops_test: OpsTest):
    assert ops_test.model
    # WHEN the charm is related to a principal over `juju-info`
    await ops_test.model.integrate("agent:juju-info", principal.name)
    await ops_test.model.integrate("hwo:general-info", principal.name)
    await ops_test.model.integrate("hwo:cos-agent", "agent:cos-agent")
    await ops_test.model.integrate("agent:grafana-cloud-config", "gci")
    await ops_test.model.wait_for_idle(apps=[principal.name, agent.name], status="active")

    # THEN all units of the principal have the charm in 'enabled/active' state
    # $ juju ssh agent/0 snap services grafana-agent
    # Service                      Startup  Current  Notes
    # grafana-agent.grafana-agent  enabled  active   -
    await ssh_units(
        ops_test, principal.name, "snap services grafana-agent | grep 'enabled.*active'"
    )


@pytest.mark.abort_on_fail
@pytest.mark.xfail(
    reason="The hardware-observer charm needs to fetch the new cos-agent library."
)  # https://github.com/canonical/grafana-agent-operator/issues/321
async def test_metrics(ops_test: OpsTest):
    # Wait the scrape interval to make sure all "state" keys turned from unknown to up (or down).
    await asyncio.sleep(90)

    unit_targets = await ssh_units(
        ops_test, principal.name, "curl localhost:12345/agent/api/v1/metrics/targets"
    )
    unit_targets = [json.loads(itm)["data"] for itm in unit_targets]

    assert len(unit_targets) > 1  # Self-scrape + node-exporter
    for targets in unit_targets:
        for target in targets:
            target_labels = target["labels"].keys()
            assert topology_labels.issubset(target_labels)
            assert target["state"] == "up"

    # $ juju ssh agent/0 curl localhost:12345/agent/api/v1/metrics/targets
    # {
    #   "status": "success",
    #   "data": [
    #     {
    #       "instance": "243a344db344241f404868d04272fc76",
    #       "target_group": "integrations/agent",
    #       "endpoint": "http://127.0.0.1:12345/integrations/agent/metrics",
    #       "state": "up",
    #       "labels": {
    #         "agent_hostname": "juju-f48d37-1",
    #         "instance": "test-charm-hz7v_8df47ec8-0c18-..._principal_principal/1",
    #         "job": "juju_test-charm-hz7v_8df47ec8-0c18-..._agent_self-monitoring",
    #         "juju_application": "agent",
    #         "juju_charm": "grafana-agent",
    #         "juju_model": "test-charm-hz7v",
    #         "juju_model_uuid": "8df47ec8-0c18-465a-8b68-a07188f48d37",
    #         "juju_unit": "agent/0"
    #       },
    #       "discovered_labels": {
    #         "__address__": "127.0.0.1:12345",
    #         "__metrics_path__": "/integrations/agent/metrics",
    #         "__scheme__": "http",
    #         "__scrape_interval__": "1m",
    #         "__scrape_timeout__": "10s",
    #         "agent_hostname": "juju-f48d37-1",
    #         "job": "integrations/agent"
    #       },
    #       "last_scrape": "2023-03-09T22:31:16.5693783Z",
    #       "scrape_duration_ms": 2,
    #       "scrape_error": ""
    #     },
    #     ...


@pytest.mark.xfail  # agent return an empty reply (bug)
async def test_logs(ops_test: OpsTest):
    unit_targets = await ssh_units(
        ops_test, principal.name, "curl localhost:12345/agent/api/v1/logs/targets"
    )
    unit_targets = [json.loads(itm)["data"] for itm in unit_targets]
    assert len(unit_targets) > 1  # Self-scrape + node-exporter
    for targets in unit_targets:
        for target in targets:
            target_labels = target["labels"].keys()
            assert topology_labels.issubset(target_labels)
