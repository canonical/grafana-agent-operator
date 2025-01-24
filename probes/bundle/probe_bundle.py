#!/usr/bin/env python3

import sys
import yaml
from itertools import combinations
from collections import defaultdict


def one_grafana_agent_per_machine(bundle: dict):
    applications = bundle["applications"]
    relations = bundle["relations"]

    # A mapping from app name to the machines it is deployed on
    principals_to_machines = {k: set(v["to"]) for k, v in applications.items() if "to" in v}

    # List of grafana-agent app names
    grafana_agent_names = [k for k, v in applications.items() if v["charm"] == "grafana-agent"]

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
            print(f"grafana-agent is related to '{app1}', '{app2}' on the same machine(s) {isect}")


def one_grafana_agent_per_app(bundle: dict):
    applications = bundle["applications"]
    relations = bundle["relations"]

    # List of grafana-agent app names
    grafana_agent_names = [k for k, v in applications.items() if v["charm"] == "grafana-agent"]

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
            print(f"App '{k}' related to multiple grafana-agent apps '{v}'")

if __name__ == '__main__':
    bundle = yaml.safe_load(sys.stdin.read())
    one_grafana_agent_per_machine(bundle)
    one_grafana_agent_per_app(bundle)

