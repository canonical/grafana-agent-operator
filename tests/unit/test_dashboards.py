# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from unittest.mock import MagicMock

from charms.grafana_agent.v0.cos_agent import (
    CosAgentPeersUnitData,
    COSAgentRequirer,
)
from charms.prometheus_k8s.v1.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from cosl import LZMABase64
from ops.charm import CharmBase
from ops.framework import Framework
from ops.testing import Context, PeerRelation, State

from grafana_agent import GrafanaAgentCharm, RulesMapping


def encode_as_dashboard(dct: dict):
    return LZMABase64.compress(json.dumps(dct))


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
        self.prom = PrometheusRemoteWriteConsumer(self, peer_relation_name="peers")
        self.tracing = MagicMock()
        framework.observe(self.cosagent.on.data_changed, self._on_cosagent_data_changed)

    def _on_cosagent_data_changed(self, _):
        pass


def _peer_state_with_dashboards(*dashboard_groups):
    # Build a State with a peer relation whose peer unit carries the given dashboard groups.
    # Each element of *dashboard_groups* is a list of raw dashboard dicts belonging to a
    # single principal app. Synthetic app names "primary_0", "primary_1", ... ensure each
    # group is treated as a distinct app by _gather_peer_data.
    peers_data: dict = {}
    for idx, dashboards in enumerate(dashboard_groups):
        app_name = f"primary_{idx}"
        unit_name = f"{app_name}/0"
        peers_data[idx + 1] = {
            f"{CosAgentPeersUnitData.KEY}-{unit_name}": CosAgentPeersUnitData(
                unit_name=unit_name,
                relation_id=str(40 + idx),
                relation_name="cos-agent",
                dashboards=[encode_as_dashboard(d) for d in dashboards],
                metrics_alert_rules={},
                log_alert_rules={},
            ).json()
        }

    peer_relation = PeerRelation(
        endpoint="peers",
        interface="grafana_agent_replica",
        peers_data=peers_data,
    )
    return State(relations=[peer_relation])


def test_dashboard_without_title_gets_no_title_placeholder():
    # GIVEN a peer state with a single dashboard that has no 'title' key
    raw_dashboard = {"uid": "abc123", "overwrite": True, "tags": ["charm: myapp"]}
    ctx = Context(charm_type=MyRequirerCharm, meta=MyRequirerCharm.META)
    state = _peer_state_with_dashboards([raw_dashboard])

    # WHEN update-status is processed
    with ctx(ctx.on.update_status(), state) as mgr:
        mgr.run()
        dashboards = mgr.charm.cosagent.dashboards

    # THEN the dashboard is assigned the placeholder title 'no_title_1'
    assert len(dashboards) == 1
    assert dashboards[0]["title"] == "no_title_1"


def test_multiple_no_title_dashboards_same_app_get_unique_placeholders():
    # GIVEN 7 dashboards from the same app, none of which have a title
    # (this is the root scenario from issue #414: cos-proxy sends multiple untitled dashboards
    # that previously all mapped to the same filename on disk, with only the last surviving)
    no_title_dashes = [{"uid": f"uid_{i}", "overwrite": True, "tags": []} for i in range(7)]
    ctx = Context(charm_type=MyRequirerCharm, meta=MyRequirerCharm.META)
    state = _peer_state_with_dashboards(no_title_dashes)

    # WHEN update-status is processed
    with ctx(ctx.on.update_status(), state) as mgr:
        mgr.run()
        dashboards = mgr.charm.cosagent.dashboards

    # THEN all 7 dashboards are present with unique no_title_N placeholders
    assert len(dashboards) == 7
    titles = [d["title"] for d in dashboards]
    assert len(set(titles)) == 7, f"Expected 7 unique titles, got: {titles}"
    for title in titles:
        assert title.startswith("no_title_"), f"Unexpected title: {title}"


def test_nested_provisioning_title_is_extracted():
    # GIVEN a dashboard in Grafana provisioning envelope format with the title inside the
    # nested 'dashboard' sub-object rather than at the top level
    raw_dashboard = {
        "dashboard": {
            "title": "My Nested Dashboard",
            "panels": [],
            "uid": "abc123",
        },
        "overwrite": True,
    }
    ctx = Context(charm_type=MyRequirerCharm, meta=MyRequirerCharm.META)
    state = _peer_state_with_dashboards([raw_dashboard])

    # WHEN update-status is processed
    with ctx(ctx.on.update_status(), state) as mgr:
        mgr.run()
        dashboards = mgr.charm.cosagent.dashboards

    # THEN the title is read from the nested sub-object
    assert len(dashboards) == 1
    assert dashboards[0]["title"] == "My Nested Dashboard"


def test_flat_title_takes_precedence_over_nested_title():
    # GIVEN a dashboard with a title at the top level AND inside a nested 'dashboard' key
    raw_dashboard = {
        "title": "Top-level Title",
        "dashboard": {"title": "Nested Title"},
        "overwrite": True,
    }
    ctx = Context(charm_type=MyRequirerCharm, meta=MyRequirerCharm.META)
    state = _peer_state_with_dashboards([raw_dashboard])

    # WHEN update-status is processed
    with ctx(ctx.on.update_status(), state) as mgr:
        mgr.run()
        dashboards = mgr.charm.cosagent.dashboards

    # THEN the top-level title takes precedence
    assert len(dashboards) == 1
    assert dashboards[0]["title"] == "Top-level Title"


def test_no_title_counter_is_global_across_multiple_apps():
    # GIVEN one untitled dashboard from each of two separate apps
    dash_app_a = {"uid": "uid_a", "overwrite": True, "tags": []}
    dash_app_b = {"uid": "uid_b", "overwrite": True, "tags": []}
    ctx = Context(charm_type=MyRequirerCharm, meta=MyRequirerCharm.META)
    state = _peer_state_with_dashboards([dash_app_a], [dash_app_b])

    # WHEN update-status is processed
    with ctx(ctx.on.update_status(), state) as mgr:
        mgr.run()
        dashboards = mgr.charm.cosagent.dashboards

    # THEN both dashboards receive unique no_title_N placeholders
    assert len(dashboards) == 2
    titles = [d["title"] for d in dashboards]
    assert len(set(titles)) == 2, f"Expected 2 unique titles, got: {titles}"
    for title in titles:
        assert title.startswith("no_title_"), f"Unexpected title: {title}"


def test_update_dashboards_writes_unique_files_for_no_title(tmp_path):
    # GIVEN 7 dashboards that each have a unique no_title_N placeholder title
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    dashboards = [
        {
            "charm": "cos-agent-cos-proxy",
            "relation_id": "17",
            "title": f"no_title_{i}",
            "content": {"uid": f"uid_{i}", "overwrite": True},
        }
        for i in range(1, 8)
    ]
    reload_func = MagicMock()
    mapping = RulesMapping(src=src, dest=dest)

    # WHEN update_dashboards is called
    # (update_dashboards does not use `self`, so a MagicMock is sufficient)
    GrafanaAgentCharm.update_dashboards(MagicMock(), dashboards, reload_func, mapping)

    # THEN one distinct file is written to disk for each dashboard
    written_files = sorted(dest.iterdir())
    assert len(written_files) == 7, (
        f"Expected 7 dashboard files on disk, got {len(written_files)}: "
        + ", ".join(f.name for f in written_files)
    )
    names = [f.name for f in written_files]
    assert len(set(names)) == 7, f"Duplicate filenames detected: {names}"
    for f in written_files:
        data = json.loads(f.read_text())
        assert "uid" in data
    # AND the reload function is called exactly once
    reload_func.assert_called_once()
