# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Common logic for both k8s and machine charms for Grafana Agent."""

import json
import logging
import os
import pathlib
import re
import shutil
import socket
from collections import namedtuple
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Union, cast

import yaml
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateAvailableEvent as CertificateTransferAvailableEvent,
)
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateRemovedEvent as CertificateTransferRemovedEvent,
)
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateTransferRequires,
)
from charms.grafana_cloud_integrator.v0.cloud_config_requirer import (
    GrafanaCloudConfigRequirer,
)
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LokiPushApiConsumer
from charms.observability_libs.v0.cert_handler import CertHandler
from charms.prometheus_k8s.v1.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer, charm_tracing_config
from cosl import MandatoryRelationPairs
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import APIError, PathError
from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util import Retry  # type: ignore
from yaml.parser import ParserError

logger = logging.getLogger(__name__)

CONFIG_PATH = "/etc/grafana-agent.yaml"
# all these are relative to the charm root
LOKI_RULES_SRC_PATH = "src/loki_alert_rules"
LOKI_RULES_DEST_PATH = "loki_alert_rules"
METRICS_RULES_SRC_PATH = "src/prometheus_alert_rules"
METRICS_RULES_DEST_PATH = "prometheus_alert_rules"
DASHBOARDS_SRC_PATH = "src/grafana_dashboards"
DASHBOARDS_DEST_PATH = "grafana_dashboards"  # placeholder until we figure out the plug

RulesMapping = namedtuple("RulesMapping", ["src", "dest"])


class GrafanaAgentReloadError(Exception):
    """Custom exception to indicate that grafana agent config couldn't be reloaded."""

    def __init__(self, message="could not reload configuration"):
        self.message = message
        super().__init__(self.message)


@dataclass
class CompoundStatus:
    """'Dumb struct' for helping with centralized status setting."""

    # None = good; do not use ActiveStatus here.
    update_config: Optional[Union[BlockedStatus, WaitingStatus]] = None
    validation_error: Optional[BlockedStatus] = None
    config_error: Optional[BlockedStatus] = None


class GrafanaAgentCharm(CharmBase):
    """Grafana Agent Charm."""

    _name = "agent"
    _http_listen_port = 3500
    _grpc_listen_port = 3600
    # TODO Change to a more suitable location once the snap gets access (#216).
    _cert_path = "/tmp/agent/grafana-agent.pem"
    _key_path = "/tmp/agent/grafana-agent.key"
    _ca_path = "/usr/local/share/ca-certificates/grafana-agent-operator.crt"
    _ca_folder_path = "/usr/local/share/ca-certificates"
    _snap_cert_path = "/var/snap/grafana-agent/common/grafana-agent.pem"
    _snap_key_path = "/var/snap/grafana-agent/common/grafana-agent.key"
    _snap_ca_path = "/var/snap/grafana-agent/common/grafana-agent-operator.crt"
    _snap_folder_path = "/var/snap/grafana-agent/common/"
    # We have a `limit: 1` on the cloud integrator relation so we expect only one such cert.
    _cloud_ca_path = "/usr/local/share/ca-certificates/cloud-integrator.crt"

    # mapping from tempo-supported receivers to the receiver ports to be opened on the grafana-agent host
    # to ingest traces for them. Note that we 'support' more receivers here than tempo currently does, so
    # that if in the future we decide to enable the receivers in tempo, we don't need to make changes
    # to grafana-agent.
    _tracing_receivers_ports = {
        # OTLP receiver: see
        #   https://github.com/open-telemetry/opentelemetry-collector/tree/v0.96.0/receiver/otlpreceiver
        "otlp_http": 4318,
        "otlp_grpc": 4317,
        # Jaeger receiver: see
        #   https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.96.0/receiver/jaegerreceiver
        "jaeger_grpc": 14250,
        "jaeger_thrift_http": 14268,
        # Zipkin receiver: see
        #   https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.96.0/receiver/zipkinreceiver
        "zipkin": 9411,
    }

    # Pairs of (incoming, [outgoing]) relation names. If any 'incoming' is joined without at least
    # one matching 'outgoing', the charm will block. Without any matching outgoing relation we may
    # incur data loss.
    # Property to facilitate centralized status update.
    # 'outgoing' are OR-ed, 'incoming' are AND-ed.
    mandatory_relation_pairs: Dict[str, List[Set[str]]]  # overridden

    def __new__(cls, *args: Any, **kwargs: Dict[Any, Any]):
        """Forbid the usage of GrafanaAgentCharm directly."""
        if cls is GrafanaAgentCharm:
            raise TypeError("This is a base class and cannot be instantiated directly.")
        return super().__new__(cls)

    def __init__(self, *args):
        super().__init__(*args)
        os.umask(0o077)

        # Property to facilitate centralized status update
        self.status = CompoundStatus()

        charm_root = self.charm_dir.absolute()
        self._forward_alert_rules = cast(bool, self.config["forward_alert_rules"])
        self.loki_rules_paths = RulesMapping(
            src=charm_root.joinpath(*LOKI_RULES_SRC_PATH.split("/")),
            dest=charm_root.joinpath(*LOKI_RULES_DEST_PATH.split("/")),
        )
        self.metrics_rules_paths = RulesMapping(
            src=charm_root.joinpath(*METRICS_RULES_SRC_PATH.split("/")),
            dest=charm_root.joinpath(*METRICS_RULES_DEST_PATH.split("/")),
        )
        self.dashboard_paths = RulesMapping(
            src=charm_root.joinpath(*DASHBOARDS_SRC_PATH.split("/")),
            dest=charm_root.joinpath(*DASHBOARDS_DEST_PATH.split("/")),
        )
        self.cert_transfer = CertificateTransferRequires(self, "receive-ca-cert")

        for rules in [self.loki_rules_paths, self.dashboard_paths]:
            if not os.path.isdir(rules.dest):
                rules.src.mkdir(parents=True, exist_ok=True)
                shutil.copytree(rules.src, rules.dest, dirs_exist_ok=True)

        alert_rules_path = self.metrics_rules_paths.dest
        self._remote_write = PrometheusRemoteWriteConsumer(
            self,
            alert_rules_path=alert_rules_path,
            forward_alert_rules=self._forward_alert_rules,
            refresh_event=[self.on.config_changed],
        )

        self._loki_consumer = LokiPushApiConsumer(
            self,
            relation_name="logging-consumer",
            alert_rules_path=self.loki_rules_paths.dest,
            forward_alert_rules=self._forward_alert_rules,
            refresh_event=[self.on.config_changed],
        )

        self._grafana_dashboards_provider = GrafanaDashboardProvider(
            self,
            relation_name="grafana-dashboards-provider",
            dashboards_path=self.dashboard_paths.dest,
        )

        self.cert = CertHandler(
            self,
            key="grafana-agent-cert",
            peer_relation_name="peers",
        )
        self.framework.observe(self.cert.on.cert_changed, self._on_cert_changed)  # pyright: ignore

        self.tracing = TracingEndpointRequirer(
            self,
            protocols=[
                "otlp_http",  # for charm traces
                "otlp_grpc",  # for forwarding workload traces
            ],
        )
        self._charm_tracing_endpoint, self._server_cert = charm_tracing_config(
            self.tracing, self._ca_path
        )

        self._cloud = GrafanaCloudConfigRequirer(self)

        self.framework.observe(
            self._cloud.on.cloud_config_available,  # pyright: ignore
            self._on_cloud_config_available,
        )
        self.framework.observe(
            self._cloud.on.cloud_config_revoked,  # pyright: ignore
            self._on_cloud_config_revoked,
        )

        self.framework.observe(
            self._grafana_dashboards_provider.on.dashboard_status_changed,  # pyright: ignore
            self._on_dashboard_status_changed,
        )

        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        self.framework.observe(
            self._remote_write.on.endpoints_changed,  # pyright: ignore
            self.on_remote_write_changed,
        )

        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_joined,  # pyright: ignore
            self._on_loki_push_api_endpoint_joined,
        )
        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_departed,  # pyright: ignore
            self._on_loki_push_api_endpoint_departed,
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        self.framework.observe(
            self.cert_transfer.on.certificate_available,  # pyright: ignore
            self._on_cert_transfer_available,
        )
        self.framework.observe(
            self.cert_transfer.on.certificate_removed,  # pyright: ignore
            self._on_cert_transfer_removed,
        )

        # Register status observers
        for incoming, outgoings in self.mandatory_relation_pairs.items():
            self.framework.observe(self.on[incoming].relation_joined, self._update_status)
            self.framework.observe(self.on[incoming].relation_broken, self._update_status)
            for outgoing_list in outgoings:
                for outgoing in outgoing_list:
                    self.framework.observe(self.on[outgoing].relation_joined, self._update_status)
                    self.framework.observe(self.on[outgoing].relation_broken, self._update_status)

    def _on_cert_changed(self, _event):
        """Event handler for cert change."""
        self._update_config()
        self._update_ca()
        self._update_status()

    def _on_mandatory_relation_event(self, _event=None):
        """Event handler for any mandatory relation event."""
        self._update_config()
        self._update_status()

    def _on_upgrade_charm(self, _event=None):
        """Refresh alerts if the charm is updated."""
        self._update_metrics_alerts()
        self._update_loki_alerts()
        self._update_config()
        self._update_status()

    def _on_loki_push_api_endpoint_joined(self, _event=None):
        """Rebuild the config with correct Loki sinks."""
        self._update_config()
        self._update_status()

    def _on_loki_push_api_endpoint_departed(self, _event=None):
        """Rebuild the config with correct Loki sinks."""
        self._update_config()
        self._update_status()

    def _on_config_changed(self, _event=None):
        """Rebuild the config."""
        self._verify_snap_track()
        self._update_config()
        self._update_status()

    def _on_cloud_config_available(self, _) -> None:
        logger.info("cloud config available")
        # Write CA from cloud config
        if self._cloud.tls_ca_ready:
            self.write_file(self._cloud_ca_path, self._cloud.tls_ca)
        else:
            self._delete_file_if_exists(self._cloud_ca_path)
        self.run(["update-ca-certificates", "--fresh"])
        self._update_config()

    def _on_cloud_config_revoked(self, _) -> None:
        logger.info("cloud config revoked")
        self._update_config()

    def _on_cert_transfer_available(self, event: CertificateTransferAvailableEvent):
        cert_filename = (
            f"{self._ca_folder_path}/receive-ca-cert-{self.model.uuid}-{event.relation_id}-ca.crt"
        )
        self.write_file(cert_filename, event.ca)
        self.run(["update-ca-certificates", "--fresh"])

    def _on_cert_transfer_removed(self, event: CertificateTransferRemovedEvent):
        cert_filename = (
            f"{self._ca_folder_path}/receive-ca-cert-{self.model.uuid}-{event.relation_id}-ca.crt"
        )
        self.delete_file(cert_filename)
        self.run(["update-ca-certificates", "--fresh"])

    # Abstract Methods
    def _verify_snap_track(self) -> None:
        raise NotImplementedError("Please override the _verify_snap_track method")

    @property
    def is_k8s(self) -> bool:
        """Is this a k8s charm."""
        raise NotImplementedError("Please override the is_k8s method")

    def agent_version_output(self) -> str:
        """Gets the raw output from `agent -version`."""
        raise NotImplementedError("Please override the agent_version_output method")

    @property
    def is_ready(self):
        """Checks if the charm is ready for configuration."""
        raise NotImplementedError("Please override the is_ready method")

    def read_file(self, filepath: Union[str, pathlib.Path]):
        """Read a file's contents.

        Returns:
            A string with the file's contents
        """
        raise NotImplementedError("Please override the read_file method")

    def write_file(self, path: Union[str, pathlib.Path], text: str) -> None:
        """Write text to a file.

        Args:
            path: file path to write to
            text: text to write to the file
        """
        raise NotImplementedError("Please override the write_file method")

    def delete_file(self, path: Union[str, pathlib.Path]):
        """Delete a file.

        Args:
            path: file to be deleted
        """
        raise NotImplementedError("Please override the delete_file method")

    def stop(self) -> None:
        """Stop grafana agent."""
        raise NotImplementedError("Please override the stop method")

    def restart(self) -> None:
        """Restart grafana agent."""
        raise NotImplementedError("Please override the restart method")

    @property
    def _additional_integrations(self) -> Dict[str, Any]:
        """Additional per-type integrations to inject."""
        raise NotImplementedError("Please override the _additional_integrations method")

    @property
    def _additional_log_configs(self) -> List[Dict[str, Any]]:
        """Additional per-type integrations to inject."""
        raise NotImplementedError("Please override the _additional_log_configs method")

    def metrics_rules(self) -> Dict[str, Any]:
        """Return a list of metrics rules."""
        raise NotImplementedError("Please override the metrics_rules method")

    def metrics_jobs(self) -> list:
        """Return a list of metrics scrape jobs."""
        raise NotImplementedError("Please override the metrics_jobs method")

    def logs_rules(self) -> Dict[str, Any]:
        """Return a list of logging rules."""
        raise NotImplementedError("Please override the logs_rules method")

    @property
    def requested_tracing_protocols(self) -> set:
        """Return a list of requested tracing receivers."""
        raise NotImplementedError("Please override the requested_receivers method")

    @property
    def dashboards(self) -> list:
        """Return a list of dashboards."""
        raise NotImplementedError("Please override the dashboards method")

    def positions_dir(self) -> str:
        """Return the positions directory."""
        raise NotImplementedError("Please override the positions_dir method")

    def run(self, cmd: List[str]):
        """Run cmd on the workload.

        Args:
            cmd: Command to be run.
        """
        raise NotImplementedError("Please override the run method")

    # End: Abstract Methods

    def _update_metrics_alerts(self):
        self.update_alerts_rules(
            alerts_func=self.metrics_rules,
            reload_func=self._remote_write.reload_alerts,
            mapping=self.metrics_rules_paths,
            copy_files=self.is_k8s,  # TODO: This is ugly
        )

    def _update_loki_alerts(self):
        self.update_alerts_rules(
            alerts_func=self.logs_rules,
            reload_func=self._loki_consumer._reinitialize_alert_rules,
            mapping=self.loki_rules_paths,
            copy_files=True,
        )

    def _update_grafana_dashboards(self):
        self.update_dashboards(
            dashboards=self.dashboards,
            reload_func=self._grafana_dashboards_provider._update_all_dashboards_from_dir,
            mapping=self.dashboard_paths,
        )

    def _recurse_call_chain(self, maybe_func: Any) -> Dict[str, Any]:
        """Recurse through wrappers until we find a real object, not a Callable."""
        if callable(maybe_func):
            return self._recurse_call_chain(maybe_func())
        return maybe_func

    def update_alerts_rules(
        self,
        alerts_func: Any,
        reload_func: Callable,
        mapping: RulesMapping,
        copy_files: bool = False,
    ):
        """Copy alert rules from relations and save them to disk."""
        # MetricsEndpointConsumer.alerts is not @property, but Loki is, so
        # do the right thing. With an additional layer of indirection, recurse
        # to the bottom until we find a real List|Dict|not-Callable
        rules = self._recurse_call_chain(alerts_func)

        if os.path.exists(mapping.dest):
            shutil.rmtree(mapping.dest)
        if copy_files:
            shutil.copytree(mapping.src, mapping.dest)
        else:
            os.mkdir(mapping.dest)
        for topology_identifier, rule in rules.items():
            file_handle = pathlib.Path(mapping.dest, "juju_{}.rules".format(topology_identifier))
            file_handle.write_text(yaml.dump(rule))
            logger.debug("updated alert rules file {}".format(file_handle.absolute()))
        reload_func()

    def update_dashboards(
        self, dashboards: Any, reload_func: Callable, mapping: RulesMapping
    ) -> None:
        """Copy dashboards from relations, save them to disk, and update."""
        shutil.rmtree(mapping.dest)
        shutil.copytree(mapping.src, mapping.dest)
        for dash in dashboards:
            # Build dashboard custom filename
            charm = dash.get("charm", "charm-name")
            rel_id = dash.get("relation_id", "rel_id")
            title = dash.get("title").replace(" ", "_").replace("/", "_").lower()
            filename = f"juju_{title}-{charm}-{rel_id}.json"

            with open(pathlib.Path(mapping.dest, filename), mode="w", encoding="utf-8") as f:
                f.write(json.dumps(dash["content"]))
                logger.debug("updated dashboard file %s", f.name)

        reload_func()

    def on_scrape_targets_changed(self, _event) -> None:
        """Event handler for the scrape targets changed event."""
        self._update_config()
        self._update_status()
        self._update_metrics_alerts()

    def on_remote_write_changed(self, _event) -> None:
        """Event handler for the remote write changed event."""
        self._update_config()
        self._update_status()
        self._update_metrics_alerts()

    def _update_status(self, *_):
        """Determine the charm status based on relation health and grafana-agent service readiness.

        This is a centralized status setter. Status should only be calculated here, or, if you need
        to temporarily change the status (e.g. during snap install), always call this method after
        so the status is re-calculated (exceptions: on_install, on_remove).
        TODO: Rework this when "compound status" is implemented
         https://github.com/canonical/operator/issues/665
        """
        if not self.is_ready:
            self.unit.status = WaitingStatus("waiting for agent to start")
            return

        if self.status.update_config:
            self.unit.status = self.status.update_config
            return

        if self.status.validation_error:
            self.unit.status = self.status.validation_error
            return

        if self.status.config_error:
            self.unit.status = self.status.config_error
            return

        # Put charm in blocked status if all incoming relations are missing
        active_relations = {k for k, v in self.model.relations.items() if v}
        if not set(self.mandatory_relation_pairs.keys()).intersection(active_relations):
            self.unit.status = BlockedStatus(
                "Missing incoming ('requires') relation: {}".format(
                    "|".join(self.mandatory_relation_pairs.keys())
                )
            )
            return

        if missing := MandatoryRelationPairs(self.mandatory_relation_pairs).get_missing_as_str(
            *active_relations
        ):
            self.unit.status = BlockedStatus(f"Missing {missing}")
            return

        if not self.is_ready:
            self.unit.status = WaitingStatus("waiting for the agent to start")
            return

        # If only _some_ of the COS relations are present, we do not want to block, but we do want
        # to inform via the Active message that they are in fact missing ("soft" warning).
        cos_rels = {
            "send-remote-write",
            "tracing",
            "logging-consumer",
            "grafana-dashboards-provider",
        }
        missing_rels = (
            cos_rels.difference(active_relations)
            if cos_rels.intersection(active_relations)
            else set()
        )
        self.unit.status = ActiveStatus(", ".join([f"{x}: off" for x in missing_rels]))

    def _update_config(self) -> None:
        if not self.is_ready:
            # Grafana-agent is not yet available so no need to update config
            return

        # Write TLS files
        if self.cert.enabled:
            if not (self.cert.cert and self.cert.key and self.cert.ca):
                self.status.update_config = WaitingStatus("Waiting for TLS certificate.")
                self.stop()
                return
            self.write_file(self._cert_path, self.cert.cert)
            self.write_file(self._key_path, self.cert.key)
            self.write_file(self._ca_path, self.cert.ca)
            if os.path.exists(self._snap_folder_path):
                # copy cert files within the snap context as well until snap is able to connect to certificate files.
                # ref: https://github.com/canonical/grafana-agent-snap/issues/71
                self.write_file(self._snap_cert_path, self.cert.cert)
                self.write_file(self._snap_key_path, self.cert.key)
                self.write_file(self._snap_ca_path, self.cert.ca)
        else:
            # Delete TLS related files if they exist
            self._delete_file_if_exists(self._cert_path)
            self._delete_file_if_exists(self._key_path)
            self._delete_file_if_exists(self._ca_path)
            self._delete_file_if_exists(self._snap_cert_path)
            self._delete_file_if_exists(self._snap_key_path)
            self._delete_file_if_exists(self._snap_ca_path)

        config = self._generate_config()

        try:
            old_config = yaml.safe_load(self.read_file(CONFIG_PATH))
        except (FileNotFoundError, PathError, ParserError):
            # File does not yet exist? Processing a deferred event?
            old_config = None

        if config == old_config:
            # Nothing changed, possibly new installation. Move on.
            self.status.update_config = None
            return

        try:
            self.write_file(CONFIG_PATH, yaml.dump(config))
            # FIXME: change this to self._reload_config when #19 is fixed
            # Restart the service to pick up the new config
            self.restart()
        except GrafanaAgentReloadError as e:
            logger.error(str(e))
            self.status.update_config = BlockedStatus(str(e))
        except APIError as e:
            logger.warning(str(e))
            self.status.update_config = WaitingStatus(str(e))

        self.status.update_config = None

    def _delete_file_if_exists(self, file_path):
        try:
            self.read_file(file_path)
        except (FileNotFoundError, PathError):
            pass
        else:
            self.delete_file(file_path)

    def _on_dashboard_status_changed(self, _event=None):
        """Re-initialize dashboards to forward."""
        # TODO: add constructor arg for `inject_dropdowns=False` instead of 'private' method?
        self._grafana_dashboards_provider._reinitialize_dashboard_data(inject_dropdowns=False)  # noqa
        self._update_status()

    def _enhance_endpoints_with_tls(self, endpoints) -> List[Dict[str, Any]]:
        for endpoint in endpoints:
            endpoint["tls_config"] = {
                "insecure_skip_verify": self.model.config.get("tls_insecure_skip_verify")
            }
        return endpoints

    def _prometheus_endpoints_with_tls(self) -> List[Dict[str, Any]]:
        """Add TLS information to Prometheus endpoints.

        Also, injects the grafana-cloud-integrator endpoints into those we get from juju relations.
        FIXME: these should be separate concerns.
        """
        prometheus_endpoints: List[Dict[str, Any]] = self._remote_write.endpoints

        if self._cloud.prometheus_ready:
            prometheus_endpoint: Dict[str, Any] = {"url": self._cloud.prometheus_url}
            if self._cloud.credentials:
                prometheus_endpoint["basic_auth"] = {
                    "username": self._cloud.credentials.username,
                    "password": self._cloud.credentials.password,
                }
            prometheus_endpoints.append(prometheus_endpoint)
        return self._enhance_endpoints_with_tls(prometheus_endpoints)

    def _loki_endpoints_with_tls(self) -> List[Dict[str, Any]]:
        """Add TLS information to Loki endpoints.

        Also, injects the grafana-cloud-integrator endpoints into those we get from juju relations.
        FIXME: these should be separate concerns.
        """
        loki_endpoints = self._loki_consumer.loki_endpoints

        if self._cloud.loki_ready:
            loki_endpoint = {
                "url": self._cloud.loki_url,
                "headers": {
                    "Content-Encoding": "snappy",
                },
            }
            if self._cloud.credentials:
                loki_endpoint["basic_auth"] = {
                    "username": self._cloud.credentials.username,
                    "password": self._cloud.credentials.password,
                }
            loki_endpoints.append(loki_endpoint)

        return self._enhance_endpoints_with_tls(loki_endpoints)

    def _tempo_endpoints_with_tls(self) -> List[Dict[str, Any]]:
        """Add TLS information to Tempo endpoints.

        Also, injects the grafana-cloud-integrator endpoints into those we get from juju relations.
        FIXME: these should be separate concerns.
        """
        tempo_endpoints = []
        if self.tracing.is_ready():
            tempo_endpoints.append(
                {
                    # outgoing traces are all otlp/grpc
                    # cit: While Tempo and the Agent both can ingest in multiple formats,
                    #  the Agent only exports in OTLP gRPC and HTTP.
                    "endpoint": self.tracing.get_endpoint("otlp_grpc"),
                    "insecure": False if self.cert.enabled else True,
                }
            )

        if self._cloud.tempo_ready:
            tempo_endpoint: Dict[str, Any] = {
                "endpoint": self._cloud.tempo_url,
            }

            if self._cloud.credentials:
                tempo_endpoint["basic_auth"] = {
                    "username": self._cloud.credentials.username,
                    "password": self._cloud.credentials.password,
                }
            tempo_endpoints.append(tempo_endpoint)
        return self._enhance_endpoints_with_tls(tempo_endpoints)

    def _cli_args(self) -> str:
        """Return the cli arguments to pass to agent.

        Returns:
            The arguments as a string
        """
        args = [f"-config.file={CONFIG_PATH}"]
        if self.cert.enabled:
            args.append("-server.http.enable-tls")
            args.append("-server.grpc.enable-tls")
        return " ".join(args)

    def _generate_config(self) -> Dict[str, Any]:
        """Generates config file str.

        Returns:
            A yaml string with grafana agent config
        """
        config = {
            "server": self._server_config,
            "integrations": self._integrations_config,
            "metrics": {
                "wal_directory": "/tmp/agent/data",
                "global": {
                    "scrape_timeout": self.model.config.get("global_scrape_timeout"),
                    "scrape_interval": self.model.config.get("global_scrape_interval"),
                },
                "configs": [
                    {
                        "name": "agent_scraper",
                        "scrape_configs": self.metrics_jobs(),
                        "remote_write": self._prometheus_endpoints_with_tls(),
                    }
                ],
            },
            "logs": self._loki_config,
            "traces": self._tempo_config,
        }
        return config

    @property
    def _server_config(self) -> dict:
        """Return the server section of the config.

        Returns:
            The dict representing the config
        """
        server_config: Dict[str, Any] = {"log_level": self.log_level}
        if self.cert.enabled:
            server_config["http_tls_config"] = self.tls_config
            server_config["grpc_tls_config"] = self.tls_config
        return server_config

    @property
    def _integrations_config(self) -> dict:
        """Return the integrations section of the config.

        Returns:
            The dict representing the config
        """
        juju_model = self.model.name
        juju_model_uuid = self.model.uuid
        juju_application = self.model.app.name

        # Align the "job" name with those of prometheus_scrape
        job_name = f"juju_{juju_model}_{juju_model_uuid}_{juju_application}_self-monitoring"

        endpoints = self._prometheus_endpoints_with_tls()

        conf = {
            "agent": {
                "enabled": True,
                "relabel_configs": [
                    {
                        "target_label": "job",
                        "regex": "(.*)",
                        "replacement": job_name,
                    },
                    {  # Align the "instance" label with the rest of the Juju-collected metrics
                        "target_label": "instance",
                        "regex": "(.*)",
                        "replacement": self._instance_name,
                    },
                    {  # To add a label, we create a relabelling that replaces a built-in
                        "source_labels": ["__address__"],
                        "target_label": "juju_charm",
                        "replacement": self.meta.name,
                    },
                    {  # To add a label, we create a relabelling that replaces a built-in
                        "source_labels": ["__address__"],
                        "target_label": "juju_model",
                        "replacement": self.model.name,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_model_uuid",
                        "replacement": self.model.uuid,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_application",
                        "replacement": self.model.app.name,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_unit",
                        "replacement": self.model.unit.name,
                    },
                ],
            },
            "prometheus_remote_write": endpoints,
            **self._additional_integrations,
        }
        return conf

    @property
    def _tracing_receivers(self) -> Dict[str, Union[Any, List[Any]]]:
        """Receivers configuration for tracing.

        Returns:
            a dict with the receivers config.
        """
        if not self.tracing.is_ready():
            return {}

        receivers_set = self.requested_tracing_protocols

        if not receivers_set:
            logger.warning("No tempo receivers enabled: grafana-agent cannot ingest traces.")
            return {}

        if self.cert.enabled:
            base_receiver_config: Dict[str, Union[str, Dict]] = {
                "tls": {
                    "ca_file": str(self._snap_ca_path),
                    "cert_file": str(self._snap_cert_path),
                    "key_file": str(self._snap_key_path),
                    "min_version": "",
                }
            }
        else:
            base_receiver_config = {}

        def _receiver_config(protocol: str):
            endpoint = "0.0.0.0:" + str(self._tracing_receivers_ports[protocol])  # type: ignore
            receiver_config = base_receiver_config.copy()
            receiver_config["endpoint"] = endpoint
            return receiver_config

        config = {}

        if "zipkin" in receivers_set:
            config["zipkin"] = _receiver_config("zipkin")

        otlp_config = {}
        if "otlp_http" in receivers_set:
            otlp_config["http"] = _receiver_config("otlp_http")
        if "otlp_grpc" in receivers_set:
            otlp_config["grpc"] = _receiver_config("otlp_grpc")
        if otlp_config:
            config["otlp"] = {"protocols": otlp_config}

        jaeger_config = {}
        if "jaeger_thrift_http" in receivers_set:
            jaeger_config["thrift_http"] = _receiver_config("jaeger_thrift_http")
        if "jaeger_grpc" in receivers_set:
            jaeger_config["grpc"] = _receiver_config("jaeger_grpc")
        if jaeger_config:
            config["jaeger"] = {"protocols": jaeger_config}

        return config

    @property
    def _tracing_sampling(self) -> Dict[str, Any]:
        # policies, as defined by tail sampling processor definition:
        # https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor
        # each of them is evaluated separately and processor decides whether to pass the trace through or not
        # see the description of tail sampling processor above for the full decision tree
        return {
            "policies": [
                {
                    "name": "error-traces-policy",
                    "type": "and",
                    "and": {
                        "and_sub_policy": [
                            {
                                "name": "trace-status-policy",
                                "type": "status_code",
                                "status_code": {"status_codes": ["ERROR"]},
                                # status_code processor is using span_status property of spans within a trace
                                # see https://opentelemetry.io/docs/concepts/signals/traces/#span-status for reference
                            },
                            {
                                "name": "probabilistic-policy",
                                "type": "probabilistic",
                                "probabilistic": {
                                    "sampling_percentage": self.config.get(
                                        "tracing_sample_rate_error"
                                    )
                                },
                            },
                        ]
                    },
                },
                {
                    "name": "charm-traces-policy",
                    "type": "and",
                    "and": {
                        "and_sub_policy": [
                            {
                                "name": "service-name-policy",
                                "type": "string_attribute",
                                "string_attribute": {
                                    "key": "service.name",
                                    "values": [".+-charm"],
                                    "enabled_regex_matching": True,
                                },
                            },
                            {
                                "name": "probabilistic-policy",
                                "type": "probabilistic",
                                "probabilistic": {
                                    "sampling_percentage": self.config.get(
                                        "tracing_sample_rate_charm"
                                    )
                                },
                            },
                        ]
                    },
                },
                {
                    "name": "workload-traces-policy",
                    "type": "and",
                    "and": {
                        "and_sub_policy": [
                            {
                                "name": "service-name-policy",
                                "type": "string_attribute",
                                "string_attribute": {
                                    "key": "service.name",
                                    "values": [".+-charm"],
                                    "enabled_regex_matching": True,
                                    "invert_match": True,
                                },
                            },
                            {
                                "name": "probabilistic-policy",
                                "type": "probabilistic",
                                "probabilistic": {
                                    "sampling_percentage": self.config.get(
                                        "tracing_sample_rate_workload"
                                    )
                                },
                            },
                        ]
                    },
                },
            ]
        }

    @property
    def _tempo_config(self) -> Dict[str, Union[Any, List[Any]]]:
        """The tracing section of the config.

        Returns:
            a dict with the tracing config.
        """
        endpoints = self._tempo_endpoints_with_tls()
        receivers = self._tracing_receivers
        sampling = self._tracing_sampling

        if not receivers:
            # pushing a config with an empty receivers section will cause gagent to error out
            return {}

        return {
            "configs": [
                {
                    "name": "tempo",
                    "remote_write": endpoints,
                    "receivers": receivers,
                    "tail_sampling": sampling,
                }
            ]
        }

    @property
    def _loki_config(self) -> Dict[str, Union[Any, List[Any]]]:
        """Modifies the loki section of the config.

        Returns:
            a dict with Loki config
        """
        endpoints = self._loki_endpoints_with_tls()

        configs = []
        if self._loki_consumer.loki_endpoints or self._cloud.loki_ready:
            configs.append(
                {
                    "name": "push_api_server",
                    "clients": endpoints,
                    "scrape_configs": [
                        {
                            "job_name": "loki",
                            "loki_push_api": {
                                "server": {
                                    "http_listen_port": self._http_listen_port,
                                    "grpc_listen_port": self._grpc_listen_port,
                                },
                            },
                        }
                    ],
                }
            )

        if self.cert.enabled:
            for config in configs:
                for scrape_config in config.get("scrape_configs", []):
                    if scrape_config.get("loki_push_api"):
                        scrape_config["loki_push_api"]["server"]["http_tls_config"] = (
                            self.tls_config
                        )
                        scrape_config["loki_push_api"]["server"]["grpc_tls_config"] = (
                            self.tls_config
                        )

        configs.extend(self._additional_log_configs)  # type: ignore
        return (
            {
                "positions_directory": f"{self.positions_dir()}/grafana-agent-positions",
                "configs": configs,
            }
            if configs
            else {}
        )

    @property
    def tls_config(self):
        """Generates the TLS config."""
        return {
            "cert_file": self._cert_path,
            "key_file": self._key_path,
        }

    @property
    def _instance_topology(self) -> Dict[str, str]:
        """Return a default topology which may be overridden by children."""
        return {
            "juju_model": self.model.name,
            "juju_model_uuid": self.model.uuid,
            "juju_application": self.model.app.name,
            "juju_unit": self.model.unit.name,
            "juju_charm": self.meta.name,
        }

    @property
    def _instance_name(self) -> str:
        """Return the instance name as interpolated topology values."""
        # While in grafana-agent-k8s we want the instance name to made up of the topology, for
        # machine charms we simply want the fqdn, as for VMs it's a vital part of the fingerprint.

        return socket.getfqdn()

    @property
    def log_level(self) -> str:
        """The log level configured for the charm."""
        # Valid upstream log levels in server_config
        # https://grafana.com/docs/agent/latest/static/configuration/server-config/#server_config
        allowed_log_levels = ["debug", "info", "warn", "error"]
        log_level = cast(str, self.config.get("log_level")).lower()

        if log_level not in allowed_log_levels:
            message = "log_level must be one of {}".format(allowed_log_levels)
            self.status.config_error = BlockedStatus(message)
            logging.warning(message)
            log_level = "info"
        return log_level

    def _reload_config(self, attempts: int = 10) -> None:
        """Reload the config file.

        Args:
            attempts: number of attempts to reload

        Raises:
            GrafanaAgentReloadError: if configuration could not be reloaded.
        """
        try:
            logger.debug("reloading agent configuration")
            url = "http://localhost/-/reload"
            errors = list(range(400, 452)) + list(range(500, 513))
            s = Session()
            retries = Retry(total=attempts, backoff_factor=0.1, status_forcelist=errors)
            s.mount("http://", HTTPAdapter(max_retries=retries))
            s.post(url)
        except Exception as e:
            message = f"could not reload configuration: {str(e)}"
            raise GrafanaAgentReloadError(message)

    @property
    def _agent_version(self) -> Optional[str]:
        """Returns the version of the agent.

        Returns:
            A string equal to the agent version
        """
        if not self.is_ready:
            return None
        # Output looks like this:
        # agent, version v0.26.1 (branch: HEAD, revision: 2b88be37)
        result = re.search(r"v(\d*\.\d*\.\d*)", self.agent_version_output())
        if result is None:
            return result
        return result.group(1)

    def _update_ca(self) -> None:
        """Updates the CA cert on disk from cert_manager."""
        if (not self.cert.enabled) or (not self.cert.ca):
            try:
                self.read_file(self._ca_path)
            except (FileNotFoundError, PathError):
                pass
            else:
                self.delete_file(self._ca_path)
        else:
            self.write_file(self._ca_path, self.cert.ca)
        self.run(["update-ca-certificates", "--fresh"])
