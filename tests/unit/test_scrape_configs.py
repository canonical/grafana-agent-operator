#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import uuid
from unittest.mock import patch

import pytest
import yaml
from charms.grafana_agent.v0.cos_agent import CosAgentProviderUnitData
from ops.testing import Context, Model, PeerRelation, Relation, State, SubordinateRelation

import charm


@pytest.fixture(autouse=True)
def patch_all(placeholder_cfg_path):
    with patch("grafana_agent.CONFIG_PATH", placeholder_cfg_path):
        yield


@pytest.mark.skip(reason="can't parse a custom fstab file")
def test_snap_endpoints(placeholder_cfg_path, charm_config):
    written_path, written_text = "", ""

    def mock_write(_, path, text):
        nonlocal written_path, written_text
        written_path = path
        written_text = text

    loki_relation = Relation(
        "logging-consumer",
        remote_app_name="loki",
        remote_units_data={
            1: {"endpoint": json.dumps({"url": "http://loki1:3100/loki/api/v1/push"})}
        },
    )

    data = CosAgentProviderUnitData(
        dashboards=[],
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=["foo:bar", "oh:snap", "shameless-plug"],
    )
    cos_relation = SubordinateRelation(
        "cos-agent", remote_app_name="principal", remote_unit_data={data.KEY: data.json()}
    )

    my_uuid = str(uuid.uuid4())

    with patch("charms.operator_libs_linux.v2.snap.SnapCache"), patch(
        "charm.GrafanaAgentMachineCharm.write_file", new=mock_write
    ), patch("charm.GrafanaAgentMachineCharm.is_ready", return_value=True):
        state = State(
            relations=[cos_relation, loki_relation, PeerRelation("peers")],
            model=Model(name="my-model", uuid=my_uuid),
            config=charm_config,
        )

        ctx = Context(
            charm_type=charm.GrafanaAgentMachineCharm,
        )
        ctx.run(state=state, event=cos_relation.changed_event)  # type: ignore

    assert written_path == placeholder_cfg_path
    written_config = yaml.safe_load(written_text)
    logs_configs = written_config["logs"]["configs"]
    for config in logs_configs:
        if config["name"] == "log_file_scraper":
            scrape_job_names = [job["job_name"] for job in config["scrape_configs"]]
            assert "foo" in scrape_job_names
            assert "oh" in scrape_job_names
            assert "shameless_plug" not in scrape_job_names
