# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from types import SimpleNamespace
from typing import List

import pytest
from juju.errors import JujuError
from pytest_operator.plugin import OpsTest

agent = SimpleNamespace(name="agent")
principal = SimpleNamespace(charm="ubuntu", name="principal")

logger = logging.getLogger(__name__)


async def ssh(ops_test, app_name: str, command: str) -> List[str]:
    """Run a command in all units of the given apps and return all the outputs."""
    unit = ops_test.model.applications[app_name].units[0]
    try:
        return await unit.ssh(command)
    except JujuError as e:
        pytest.fail(f"Failed to run ssh command '{command}' in {app_name}: {e.message}")


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, grafana_agent_charm):
    # Principal
    await ops_test.model.deploy(principal.charm, application_name=principal.name, series="jammy")

    # Workaround: `charmcraft pack` produces two files, but `ops_test.build_charm` returns the
    # first one. Since primary is jammy, we know we need to deploy the jammy grafana agent charm,
    # otherwise we'd get an error such as:
    #   ImportError: libssl.so.1.1: cannot open shared object file: No such file or directory
    jammy_charm_path = grafana_agent_charm.parent / "grafana-agent_ubuntu-22.04-amd64.charm"

    # Subordinate
    await ops_test.model.deploy(
        jammy_charm_path, application_name=agent.name, num_units=0, series="jammy"
    )

    # Placeholder for o11y relations (otherwise grafana agent charm is in blocked status)
    await ops_test.model.deploy(
        "grafana-cloud-integrator",
        application_name="gci",
        num_units=1,
        series="focal",
        channel="edge",
    )

    await ops_test.model.add_relation("agent:juju-info", principal.name)
    await ops_test.model.add_relation("agent:grafana-cloud-config", "gci")
    await ops_test.model.wait_for_idle(apps=[principal.name, agent.name], status="active")


@pytest.mark.abort_on_fail
async def test_classic_by_default(ops_test: OpsTest):
    # WHEN the charm is related to a principal over `juju-info`

    # THEN all units of the principal have the charm in 'enabled/active' state
    # $ juju ssh agent/0 snap services grafana-agent
    # Service                      Startup  Current  Notes
    # grafana-agent.grafana-agent  enabled  active   -
    out = await ssh(ops_test, agent.name, "snap info --verbose grafana-agent | grep confinement")
    assert out.split()[1] == "classic"


@pytest.mark.abort_on_fail
async def test_switch_to_strict(ops_test: OpsTest):
    # WHEN the charm is related to a principal over `juju-info`

    # THEN all units of the principal have the charm in 'enabled/active' state
    # $ juju ssh agent/0 snap services grafana-agent
    # Service                      Startup  Current  Notes
    # grafana-agent.grafana-agent  enabled  active   -
    ops_test.model.applications[agent.name].set_config({"classic_snap": False})
    await ops_test.model.wait_for_idle(
        apps=[principal.name, agent.name], status="active", idle_period=15
    )
    out = await ssh(ops_test, agent.name, "snap info --verbose grafana-agent | grep confinement")
    assert out.split()[1] == "strict"


@pytest.mark.abort_on_fail
async def test_switch_to_classic(ops_test: OpsTest):
    # WHEN the charm is related to a principal over `juju-info`

    # THEN all units of the principal have the charm in 'enabled/active' state
    # $ juju ssh agent/0 snap services grafana-agent
    # Service                      Startup  Current  Notes
    # grafana-agent.grafana-agent  enabled  active   -
    ops_test.model.applications[agent.name].set_config({"classic_snap": True})
    await ops_test.model.wait_for_idle(
        apps=[principal.name, agent.name], status="active", idle_period=15
    )
    out = await ssh(ops_test, agent.name, "snap info --verbose grafana-agent | grep confinement")
    assert out.split()[1] == "classic"
