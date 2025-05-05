from collections import defaultdict
from itertools import combinations


def status(juju_statuses):
    # One grafana agent subordinate per principal app or machine
    for status in juju_statuses.values():
        if status is None:
            continue
        _status_one_per_machine(status)
        _status_one_per_app(status)


def bundle(juju_bundles):
    # One grafana agent subordinate per principal app or machine
    for bundle in juju_bundles.values():
        if bundle is None:
            continue
        _bundle_one_per_machine(bundle)
        _bundle_one_per_app(bundle)


def _status_one_per_machine(status: dict):
    # A mapping from grafana-agent app name to the list of apps it's subordinate to
    agents = {
        k: v["subordinate-to"]
        for k, v in status["applications"].items()
        if v["charm"] == "grafana-agent"
    }

    assert len(agents) > 0, "Missing subordinate grafana-agent applications on machines."

    for agent, principals in agents.items():
        # A mapping from app name to machines
        machines = {
            p: [u["machine"] for u in status["applications"][p].get("units", {}).values()]
            for p in principals
        }

        from itertools import combinations

        for p1, p2 in combinations(principals, 2):
            if overlap := set(machines[p1]) & set(machines[p2]):
                raise Exception(f"{agent} is subordinate to both '{p1}', '{p2}' in the same machines {overlap}")


def _status_one_per_app(status: dict):
    # A mapping from grafana-agent app name to the list of apps it's subordinate to
    agents = {
        k: v["subordinate-to"]
        for k, v in status["applications"].items()
        if v["charm"] == "grafana-agent"
    }

    assert len(agents) > 0, "Missing subordinate grafana-agent applications related to principals."

    for agent, principals in agents.items():
        for p in principals:
            for name, unit in status["applications"][p].get("units", {}).items():
                subord_apps = {u.split("/", -1)[0] for u in unit["subordinates"].keys()}
                subord_agents = subord_apps & agents.keys()
                if len(subord_agents) > 1:
                    raise Exception(f"{name} is related to more than one grafana-agent subordinate: {subord_agents}")


def _bundle_one_per_machine(bundle: dict):
    applications = bundle["applications"]
    relations = bundle["relations"]

    # A mapping from app name to the machines it is deployed on
    principals_to_machines = {k: set(v["to"]) for k, v in applications.items() if "to" in v}

    assert len(principals_to_machines) > 0, "No principal apps found on machines."

    # List of grafana-agent app names
    grafana_agent_names = [k for k, v in applications.items() if v["charm"] == "grafana-agent"]

    assert len(grafana_agent_names) > 0, "No subordinate grafana-agents found on machines."

    principals_related_to_grafana_agent = []
    subordinates_related_to_grafana_agent = []
    for rel_pair in relations:
        # Truncate the relation names
        apps_pair = [s.split(':',-1)[0] for s in rel_pair]

        related_app = None
        if apps_pair[0] in grafana_agent_names:
            related_app = apps_pair[1]
        elif apps_pair[1] in grafana_agent_names:
            related_app = apps_pair[0]

        if related_app:
            if related_app in principals_to_machines:
                principals_related_to_grafana_agent.append(related_app)
            elif related_app in applications:
                subordinates_related_to_grafana_agent.append(related_app)

    for app1,app2 in combinations(principals_related_to_grafana_agent, 2):
        if isect := principals_to_machines[app1].intersection(principals_to_machines[app2]):
            raise Exception(f"grafana-agent is related to '{app1}', '{app2}' on the same machine(s) {isect}")


def _bundle_one_per_app(bundle: dict):
    applications = bundle["applications"]
    relations = bundle["relations"]

    # List of grafana-agent app names
    grafana_agent_names = [k for k, v in applications.items() if v["charm"] == "grafana-agent"]

    assert len(grafana_agent_names) > 0, "Missing subordinate grafana-agent applications related to principals."

    counter = defaultdict(list)
    for rel_pair in relations:
        # Truncate the relation names
        apps_pair = [s.split(':',-1)[0] for s in rel_pair]

        if apps_pair[0] in grafana_agent_names and apps_pair[1] in applications:
            counter[apps_pair[1]].append(apps_pair[0])
        elif apps_pair[1] in grafana_agent_names and apps_pair[0] in applications:
            counter[apps_pair[0]].append(apps_pair[1])

    for k, v in counter.items():
        if len(v) > 1:
            raise Exception(f"App '{k}' related to multiple grafana-agent apps '{v}'")