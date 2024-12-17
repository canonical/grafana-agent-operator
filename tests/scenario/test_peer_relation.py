# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import MagicMock

import pytest
from charms.grafana_agent.v0.cos_agent import (
    CosAgentPeersUnitData,
    CosAgentProviderUnitData,
    COSAgentRequirer,
)
from charms.prometheus_k8s.v1.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from cosl import LZMABase64
from ops.charm import CharmBase
from ops.framework import Framework
from ops.testing import Context, PeerRelation, State, SubordinateRelation


def encode_as_dashboard(dct: dict):
    return LZMABase64.compress(json.dumps(dct))


def test_fetch_data_from_relation():
    relation = MagicMock()
    unit = MagicMock()
    app = MagicMock()
    py_dash = {"title": "title", "foo": "bar"}

    relation.units = []  # there should be remote units in here, presumably
    config = {
        "unit_name": "principal/0",
        "relation_id": "0",
        "relation_name": "foo",
        "dashboards": [encode_as_dashboard(py_dash)],
    }
    relation.app = app
    relation.data = {unit: {CosAgentPeersUnitData.KEY: json.dumps(config)}, app: {}}

    obj = MagicMock()
    obj._charm.unit = unit

    obj.peer_relation = relation
    data = COSAgentRequirer._gather_peer_data(obj)
    assert len(data) == 1

    data_peer_1 = data[0]
    assert len(data_peer_1.dashboards) == 1
    dash_out_raw = data_peer_1.dashboards[0]
    assert json.loads(LZMABase64.decompress(dash_out_raw)) == py_dash


class MyRequirerCharm(CharmBase):
    META = {
        "name": "test",
        "requires": {
            "cos-agent": {"interface": "cos_agent", "scope": "container"},
            "send-remote-write": {"interface": "prometheus_remote_write"},
        },
        "peers": {"peers": {"interface": "grafana_agent_replica"}},
    }

    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.cosagent = COSAgentRequirer(self)
        self.prom = PrometheusRemoteWriteConsumer(self)
        self.tracing = MagicMock()
        framework.observe(self.cosagent.on.data_changed, self._on_cosagent_data_changed)

    def _on_cosagent_data_changed(self, _):
        pass


def test_no_dashboards():
    ctx = Context(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
    )
    with ctx(ctx.on.update_status(), State()) as mgr:
        mgr.run()
        assert not mgr.charm.cosagent.dashboards


def test_no_dashboards_peer():
    peer_relation = PeerRelation(endpoint="peers", interface="grafana_agent_replica")

    state = State(relations=[peer_relation])

    ctx = Context(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
    )
    with ctx(ctx.on.update_status(), state) as mgr:
        mgr.run()
        assert not mgr.charm.cosagent.dashboards


def test_no_dashboards_peer_cosagent():
    cos_agent = SubordinateRelation(
        endpoint="cos-agent", interface="cos_agent", remote_app_name="primary"
    )
    peer_relation = PeerRelation(endpoint="peers", interface="grafana_agent_replica")

    state = State(relations=[peer_relation, cos_agent])

    ctx = Context(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
    )
    with ctx(ctx.on.relation_changed(relation=cos_agent, remote_unit=0), state) as mgr:
        mgr.run()
        assert not mgr.charm.cosagent.dashboards


@pytest.mark.parametrize("leader", (True, False))
def test_cosagent_to_peer_data_flow_dashboards(leader):
    # This test verifies that if the charm receives via cos-agent a dashboard,
    # it is correctly transferred to peer relation data.

    raw_dashboard_1 = {"title": "title", "foo": "bar"}
    raw_data_1 = CosAgentProviderUnitData(
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=[],
        dashboards=[encode_as_dashboard(raw_dashboard_1)],
    )
    cos_agent = SubordinateRelation(
        endpoint="cos-agent",
        interface="cos_agent",
        remote_app_name="primary",
        remote_unit_data={raw_data_1.KEY: raw_data_1.json()},
    )
    peer_relation = PeerRelation(endpoint="peers", interface="grafana_agent_replica")

    state = State(relations=[peer_relation, cos_agent], leader=leader)

    ctx = Context(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
    )
    with ctx(ctx.on.relation_changed(relation=cos_agent, remote_unit=0), state) as mgr:
        out = mgr.run()
        assert mgr.charm.cosagent.dashboards

    peer_relation_out = next(filter(lambda r: r.endpoint == "peers", out.relations))
    peer_data = peer_relation_out.local_unit_data[f"{CosAgentPeersUnitData.KEY}-primary/0"]
    assert json.loads(peer_data)["dashboards"] == [encode_as_dashboard(raw_dashboard_1)]


@pytest.mark.parametrize("leader", (True, False))
def test_cosagent_to_peer_data_flow_relation(leader):
    # dump the data the same way the provider would
    raw_dashboard_1 = {"title": "title", "foo": "bar"}
    data_1 = CosAgentProviderUnitData(
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=[],
        dashboards=[encode_as_dashboard(raw_dashboard_1)],
    )

    cos_agent_1 = SubordinateRelation(
        endpoint="cos-agent",
        interface="cos_agent",
        remote_app_name="primary",
        remote_unit_data={data_1.KEY: data_1.json()},
    )

    raw_dashboard_2 = {"title": "other_title", "foo": "other bar (would that be a pub?)"}
    data_2 = CosAgentProviderUnitData(
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=[],
        dashboards=[encode_as_dashboard(raw_dashboard_2)],
    )

    cos_agent_2 = SubordinateRelation(
        endpoint="cos-agent",
        interface="cos_agent",
        remote_app_name="other_primary",
        remote_unit_data={data_2.KEY: data_2.json()},
    )

    # now the peer relation already contains the primary/0 information
    # i.e. we've already seen cos_agent_1-relation-changed before
    peer_relation = PeerRelation(
        endpoint="peers",
        interface="grafana_agent_replica",
        peers_data={
            1: {
                f"{CosAgentPeersUnitData.KEY}-primary/0": CosAgentPeersUnitData(
                    unit_name="primary/0",
                    relation_id="42",
                    relation_name="foobar-relation",
                    dashboards=[encode_as_dashboard(raw_dashboard_1)],
                ).json()
            }
        },
    )

    state = State(
        leader=leader,
        relations=[
            peer_relation,
            cos_agent_1,
            cos_agent_2,
        ],
    )

    ctx = Context(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
    )

    with ctx(ctx.on.relation_changed(relation=cos_agent_2, remote_unit=0), state) as mgr:
        dashboards = mgr.charm.cosagent.dashboards
        dash_0 = dashboards[0]
        assert len(dashboards) == 1
        assert dash_0["title"] == "title"
        assert dash_0["content"] == raw_dashboard_1

        out = mgr.run()

        dashboards = mgr.charm.cosagent.dashboards
        other_dash, dash = dashboards
        assert len(dashboards) == 2
        assert dash["title"] == "title"
        assert dash["content"] == raw_dashboard_1
        assert other_dash["title"] == "other_title"
        assert other_dash["content"] == raw_dashboard_2

    peer_relation_out: PeerRelation = next(filter(lambda r: r.endpoint == "peers", out.relations))
    # the dashboard we just received via cos-agent is now in our local peer databag
    peer_data_local = peer_relation_out.local_unit_data[
        f"{CosAgentPeersUnitData.KEY}-other_primary/0"
    ]
    assert json.loads(peer_data_local)["dashboards"] == [encode_as_dashboard(raw_dashboard_2)]

    # the dashboard we previously had via peer data is still there.
    peer_data_peer = peer_relation_out.peers_data[1][f"{CosAgentPeersUnitData.KEY}-primary/0"]
    assert json.loads(peer_data_peer)["dashboards"] == [encode_as_dashboard(raw_dashboard_1)]


@pytest.mark.parametrize("leader", (True, False))
def test_cosagent_to_peer_data_app_vs_unit(leader):
    # this test verifies that if multiple units (belonging to different apps) all publish their own
    # CosAgentProviderUnitData via `cos-agent`, then the `peers` peer relation will be populated
    # with the right data.
    # This means:
    # - The per-app data is only collected once per application (dedup'ed).
    # - The per-unit data is collected across all units.

    # dump the data the same way the provider would
    raw_dashboard_1 = {"title": "title", "foo": "bar"}
    data_1 = CosAgentProviderUnitData(
        dashboards=[encode_as_dashboard(raw_dashboard_1)],
        metrics_alert_rules={"a": "b", "c": 1},
        log_alert_rules={"a": "b", "c": 2},
        metrics_scrape_jobs=[{"1": 2, "2": 3}],
        log_slots=["foo:bar", "bax:qux"],
    )

    # there's an "other_primary" app also relating over `cos-agent`
    raw_dashboard_2 = {"title": "other_title", "foo": "other bar (would that be a pub?)"}
    data_2 = CosAgentProviderUnitData(
        dashboards=[encode_as_dashboard(raw_dashboard_2)],
        metrics_alert_rules={"a": "h", "c": 1},
        log_alert_rules={"a": "h", "d": 2},
        metrics_scrape_jobs=[{"1": 2, "4": 3}],
        log_slots=["dead:beef", "bax:quff"],
    )

    cos_agent_2 = SubordinateRelation(
        endpoint="cos-agent",
        interface="cos_agent",
        remote_app_name="other_primary",
        remote_unit_data={data_2.KEY: data_2.json()},
    )

    # suppose that this unit's primary is 'other_primary/0'.

    # now the peer relation already contains the primary/0 information
    # i.e. we've already seen cos_agent_1-relation-changed before
    peer_relation = PeerRelation(
        endpoint="peers",
        interface="grafana_agent_replica",
        # one of this unit's peers, who has as primary "primary/23", has already
        # logged its part of the data
        peers_data={
            1: {
                f"{CosAgentPeersUnitData.KEY}-primary/23": CosAgentPeersUnitData(
                    unit_name="primary/23",
                    relation_id="42",
                    relation_name="cos-agent",
                    # data coming from `primary` is here:
                    dashboards=data_1.dashboards,
                    metrics_alert_rules=data_1.metrics_alert_rules,
                    log_alert_rules=data_1.log_alert_rules,
                ).json()
            }
        },
    )

    state = State(
        leader=leader,
        relations=[
            peer_relation,
            cos_agent_2,
        ],
    )

    ctx = Context(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
    )

    with ctx(ctx.on.relation_changed(relation=cos_agent_2, remote_unit=0), state) as mgr:
        # verify that before the event is processed, the charm correctly gathers only 1 dashboard
        dashboards = mgr.charm.cosagent.dashboards
        dash_0 = dashboards[0]
        assert len(dashboards) == 1
        assert dash_0["title"] == "title"
        assert dash_0["content"] == raw_dashboard_1

        out = mgr.run()

        # after the event is processed, the charm has copied its primary's 'cos-agent' data into
        # its 'peers' peer databag, therefore there are now two dashboards.
        # The source of the dashboards is peer data.
        dashboards = mgr.charm.cosagent.dashboards
        dash_0 = dashboards[0]
        dash_1 = dashboards[1]
        assert len(dashboards) == 2
        assert dash_0["title"] == "other_title"
        assert dash_0["content"] == raw_dashboard_2
        assert dash_1["title"] == "title"
        assert dash_1["content"] == raw_dashboard_1

    peer_relation_out: PeerRelation = next(filter(lambda r: r.endpoint == "peers", out.relations))
    my_databag_peer_data = peer_relation_out.local_unit_data[
        f"{CosAgentPeersUnitData.KEY}-other_primary/0"
    ]
    assert set(json.loads(my_databag_peer_data)["dashboards"]) == {
        encode_as_dashboard(raw_dashboard_2)
    }

    peer_databag_peer_data = peer_relation_out.peers_data[1][
        f"{CosAgentPeersUnitData.KEY}-primary/23"
    ]
    assert json.loads(peer_databag_peer_data)["dashboards"][0] == encode_as_dashboard(
        raw_dashboard_1
    )
