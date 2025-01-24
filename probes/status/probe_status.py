#!/usr/bin/env python3

import sys
import yaml


def one_grafana_agent_per_machine(status: dict):
    # A mapping from grafana-agent app name to the list of apps it's subordinate to
    agents = {
        k: v["subordinate-to"]
        for k, v in status["applications"].items()
        if v["charm"] == "grafana-agent"
    }

    for agent, principals in agents.items():
        # A mapping from app name to machines
        machines = {
            p: [u["machine"] for u in status["applications"][p].get("units", {}).values()]
            for p in principals
        }

        from itertools import combinations

        for p1, p2 in combinations(principals, 2):
            if overlap := set(machines[p1]) & set(machines[p2]):
                print(
                    f"{agent} is subordinate to both '{p1}', '{p2}' in the same machines {overlap}"
                )


def one_grafana_agent_per_app(status: dict):
    # A mapping from grafana-agent app name to the list of apps it's subordinate to
    agents = {
        k: v["subordinate-to"]
        for k, v in status["applications"].items()
        if v["charm"] == "grafana-agent"
    }

    for agent, principals in agents.items():
        for p in principals:
            for name, unit in status["applications"][p].get("units", {}).items():
                subord_apps = {u.split("/", -1)[0] for u in unit["subordinates"].keys()}
                subord_agents = subord_apps & agents.keys()
                if len(subord_agents) > 1:
                    print(
                        f"{name} is related to more than one grafana-agent subordinate: {subord_agents}"
                    )


if __name__ == '__main__':
    status = yaml.safe_load(sys.stdin.read())
    one_grafana_agent_per_machine(status)
    one_grafana_agent_per_app(status)
