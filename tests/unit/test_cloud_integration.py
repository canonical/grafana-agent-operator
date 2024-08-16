import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from charm import GrafanaAgentMachineCharm as GrafanaAgentCharm
from ops import ActiveStatus, BlockedStatus
from ops.testing import Harness


class TestUpdateStatus(unittest.TestCase):
    def setUp(self, *unused):
        patcher = patch.object(GrafanaAgentCharm, "_agent_version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        temp_config_path = tempfile.mkdtemp() + "/grafana-agent.yaml"
        # otherwise will attempt to write to /etc/grafana-agent.yaml
        patcher = patch("grafana_agent.CONFIG_PATH", temp_config_path)
        self.config_path_mock = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch("charm.snap")
        self.mock_snap = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch.object(GrafanaAgentCharm, "_install")
        self.mock_install = patcher.start()
        self.addCleanup(patcher.stop)

    def test_prometheus_remote_write_config_with_grafana_cloud_integrator(self):
        """Asserts that the prometheus remote write config is written correctly for leaders and non-leaders."""
        for leader in (True, False):
            with self.subTest(leader=leader):
                harness = Harness(GrafanaAgentCharm)
                harness.set_model_name(self.__class__.__name__)
                harness.set_leader(True)
                harness.begin_with_initial_hooks()

                # WHEN an incoming relation is added
                rel_id = harness.add_relation("juju-info", "grafana-agent")
                harness.add_relation_unit(rel_id, "grafana-agent/0")

                # THEN the charm goes into blocked status
                assert isinstance(harness.charm.unit.status, BlockedStatus)

                # AND WHEN the necessary outgoing relations are added
                harness.add_relation(
                    "grafana-cloud-config",
                    "grafana-cloud-integrator",
                    app_data={"prometheus_url": "http://some.domain.name:9090/api/v1/write"},
                )

                # THEN the charm goes into active status
                assert isinstance(harness.charm.unit.status, ActiveStatus)

                # THEN with the expected prometheus endpoint settings are written to the config file
                config = yaml.safe_load(Path(self.config_path_mock).read_text())
                assert len(config["integrations"]["prometheus_remote_write"]) == 1
                self.assertEqual(
                    config["integrations"]["prometheus_remote_write"][0]["url"],
                    "http://some.domain.name:9090/api/v1/write",
                )
