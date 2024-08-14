import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml
from ops import BlockedStatus, ActiveStatus
from ops.testing import Harness

from charm import GrafanaAgentMachineCharm as GrafanaAgentCharm


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

    def test_prometheus_remote_write_config_with_grafana_cloud_integrator_on_leader(self):
        """Asserts that the prometheus remote write config is written correctly when the charm is a leader."""
        harness = Harness(GrafanaAgentCharm)
        harness.set_model_name(self.__class__.__name__)

        harness.set_leader(True)
        harness.begin_with_initial_hooks()

        self._subtest_prometheus_remote_write_config_with_grafana_cloud_integrator_on_leader(harness)

    def test_prometheus_remote_write_config_with_grafana_cloud_integrator_on_non_leader(self):
        """Asserts that the prometheus remote write config is written correctly when the charm is not a leader."""
        harness = Harness(GrafanaAgentCharm)
        harness.set_model_name(self.__class__.__name__)

        harness.set_leader(False)
        harness.begin_with_initial_hooks()

        self._subtest_prometheus_remote_write_config_with_grafana_cloud_integrator_on_leader(harness)

    def _subtest_prometheus_remote_write_config_with_grafana_cloud_integrator_on_leader(self, harness):
        """Helper for all shared code between prometheus_remote_write_config tests."""
        # WHEN an incoming relation is added
        rel_id = harness.add_relation("juju-info", "grafana-agent")
        harness.add_relation_unit(rel_id, "grafana-agent/0")

        # THEN the charm goes into blocked status
        assert isinstance(harness.charm.unit.status, BlockedStatus)

        # AND WHEN all the necessary outgoing relations are added
        # for outgoing in ["send-remote-write", "logging-consumer"]:
        harness.add_relation("grafana-cloud-config", "grafana-cloud-integrator", app_data={"prometheus_url": "http://some.domain.name:9090/api/v1/write"})

        # THEN the charm goes into active status
        assert isinstance(harness.charm.unit.status, ActiveStatus)

        # THEN with the expected prometheus endpoint settings are written to the config file
        config = yaml.safe_load(Path(self.config_path_mock).read_text())
        assert len(config["integrations"]["prometheus_remote_write"]) == 1
        assert config["integrations"]["prometheus_remote_write"][0]["url"] == "http://some.domain.name:9090/api/v1/write"
