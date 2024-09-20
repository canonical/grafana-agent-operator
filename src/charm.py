#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union, get_args

import yaml
from charms.grafana_agent.v0.cos_agent import COSAgentRequirer, ReceiverProtocol
from charms.operator_libs_linux.v2 import snap  # type: ignore
from charms.tempo_k8s.v1.charm_tracing import trace_charm
from cosl import JujuTopology
from cosl.rules import AlertRules
from ops.main import main
from ops.model import BlockedStatus, MaintenanceStatus, Relation

from grafana_agent import METRICS_RULES_SRC_PATH, GrafanaAgentCharm
from snap_management import SnapSpecError, install_ga_snap

logger = logging.getLogger(__name__)

_FsType = str
_MountOption = str
_MountOptions = List[_MountOption]


@dataclass
class _SnapFstabEntry:
    """Representation of an individual fstab entry for snap plugs."""

    source: str
    target: str
    fstype: Union[_FsType, None]
    options: _MountOptions
    dump: int
    fsck: int

    owner: str = field(init=False)
    endpoint_source: str = field(init=False)
    relative_target: str = field(init=False)

    def __post_init__(self):
        """Populate with calculated values at runtime."""
        self.owner = re.sub(
            r"^(.*?)?/snap/(?P<owner>([A-Za-z0-9_-])+)/.*$", r"\g<owner>", self.source
        )
        self.endpoint_source = re.sub(
            r"^(.*?)?/snap/([A-Za-z0-9_-])+/(?P<path>.*$)", r"\g<path>", self.source
        )
        self.relative_target = re.sub(
            r"^(.*?)?/snap/grafana-agent/\d+/shared-logs+(?P<path>/.*$)", r"\g<path>", self.target
        )


@dataclass
class SnapFstab:
    """Build a small representation/wrapper for snap fstab files."""

    fstab_file: Union[Path, str]
    entries: List[_SnapFstabEntry] = field(init=False)

    def __post_init__(self):
        """Populate with calculated values at runtime."""
        self.fstab_file = (
            self.fstab_file if isinstance(self.fstab_file, Path) else Path(self.fstab_file)
        )
        if not self.fstab_file.exists():
            self.entries = []
            return

        entries = []
        for line in self.fstab_file.read_text().split("\n"):
            if not line.strip():
                # skip whitespace-only lines
                continue
            raw_entry = line.split()
            fields = {
                "source": raw_entry[0],
                "target": raw_entry[1],
                "fstype": None if raw_entry[2] == "none" else raw_entry[2],
                "options": raw_entry[3].split(","),
                "dump": int(raw_entry[4]),
                "fsck": int(raw_entry[5]),
            }
            entry = _SnapFstabEntry(**fields)
            entries.append(entry)

        self.entries = entries

    def entry(self, owner: str, endpoint_name: Optional[str]) -> Optional[_SnapFstabEntry]:
        """Find and return a specific entry if it exists."""
        entries = [e for e in self.entries if e.owner == owner]

        if len(entries) > 1 and endpoint_name:
            # If there's more than one entry, the endpoint name may not directly map to
            # the source *or* path. charmed-kafka uses 'logs' as the plug name, and maps
            # .../common/logs to .../log inside Grafana Agent
            #
            # The only meaningful scenario in which this could happen (multiple fstab
            # entries with the same snap "owning" the originating path) is if a snap provides
            # multiple paths as part of the same plug.
            #
            # In this case, for a cheap comparison (rather than implementing some recursive
            # LCS just for this), convert all possible endpoint sources into a list of unique
            # characters, as well as the endpoint name, and build a sequence of entries with
            # a value that's the length of the intersection, the pick the first one i.e. the one
            # with the largest intersection.
            ordered_entries = sorted(
                entries,
                # descending order
                reverse=True,
                # size of the character-level similarity of the two strings
                key=lambda e: len(set(endpoint_name) & set(e.endpoint_source)),
            )
            return ordered_entries[0]

        if len(entries) > 1 or not entries:
            logger.debug(
                "Ambiguous or unknown mountpoint for snap %s at slot %s, not relabeling.",
                owner,
                endpoint_name,
            )
            return None

        return entries[0]


class GrafanaAgentError(Exception):
    """Custom exception type for Grafana Agent."""

    pass


class GrafanaAgentInstallError(GrafanaAgentError):
    """Custom exception type for install related errors."""

    pass


class GrafanaAgentServiceError(GrafanaAgentError):
    """Custom exception type for service related errors."""

    pass


@trace_charm(
    # these attrs are implemented on GrafanaAgentCharm
    tracing_endpoint="_charm_tracing_endpoint",
    server_cert="_server_cert",
    extra_types=(COSAgentRequirer, JujuTopology, SnapFstab),
)
class GrafanaAgentMachineCharm(GrafanaAgentCharm):
    """Machine version of the Grafana Agent charm."""

    service_name = "grafana-agent.grafana-agent"

    mandatory_relation_pairs = {
        "cos-agent": [  # must be paired with:
            {"grafana-cloud-config"},  # or
            {"send-remote-write"},  # or
            {"logging-consumer"},  # or
            {"grafana-dashboards-provider"},
        ],
        "juju-info": [  # must be paired with:
            {"grafana-cloud-config"},  # or
            {"send-remote-write"},  # or
            {"logging-consumer"},
        ],
    }

    def __init__(self, *args):
        super().__init__(*args)
        # technically, only one of 'cos-agent' and 'juju-info' are likely to ever be active at
        # any given time. however, for the sake of understandability, we always set _cos, and
        # we always listen to juju-info-joined events even though one of the two paths will be
        # at all effects unused.
        self._cos = COSAgentRequirer(self)
        self.framework.observe(
            self._cos.on.data_changed,  # pyright: ignore
            self._on_cos_data_changed,
        )
        self.framework.observe(
            self._cos.on.validation_error,
            self._on_cos_validation_error,  # pyright: ignore
        )
        self.framework.observe(self.on["juju_info"].relation_joined, self._on_juju_info_joined)
        self.framework.observe(self.on.install, self.on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.remove, self._on_remove)

    @property
    def snap(self):
        """Return the snap object for the Grafana Agent snap."""
        # This is handled in a property to avoid calls to snapd until they're necessary.
        return snap.SnapCache()["grafana-agent"]

    def _on_juju_info_joined(self, _event):
        """Update the config when Juju info is joined."""
        self._update_config()
        self._update_status()

    def _on_cos_data_changed(self, event):
        """Trigger renewals of all data if there is a change."""
        self._connect_logging_snap_endpoints()
        self._update_config()
        self._update_status()
        self._update_metrics_alerts()
        self._update_loki_alerts()
        self._update_grafana_dashboards()

    def _on_cos_validation_error(self, event):
        msg_text = "Validation errors for cos-agent relation - check juju debug-log."
        self.status.validation_error = BlockedStatus(msg_text)

        messages = event.message.split("\n")
        logger.error("%s:", messages[0])

        for msg in messages[1:]:
            logger.error(msg)

        self._update_status()

    def _verify_snap_track(self) -> None:
        try:
            # install_ga_snap calls snap.ensure so it should do the right thing whether the track
            # changes or not.
            install_ga_snap(classic=bool(self.config["classic_snap"]))
        except (snap.SnapError, SnapSpecError) as e:
            raise GrafanaAgentInstallError("Failed to refresh grafana-agent.") from e

    def on_install(self, _event) -> None:
        """Install the Grafana Agent snap."""
        self._install()

    def _install(self) -> None:
        """Install/refresh the Grafana Agent snap."""
        self.unit.status = MaintenanceStatus("Installing grafana-agent snap")
        try:
            install_ga_snap(classic=bool(self.config["classic_snap"]))
        except (snap.SnapError, SnapSpecError) as e:
            raise GrafanaAgentInstallError("Failed to install grafana-agent.") from e

    def _on_start(self, _event) -> None:
        # Ensure the config is up-to-date before we start to avoid racy relation
        # changes and starting with a "bare" config in ActiveStatus
        self._update_config()
        self.unit.status = MaintenanceStatus("Starting grafana-agent snap")

        try:
            self.snap.start(enable=True)
        except snap.SnapError as e:
            raise GrafanaAgentServiceError("Failed to start grafana-agent") from e

        self._update_status()

    def _on_stop(self, _event) -> None:
        self.unit.status = MaintenanceStatus("Stopping grafana-agent snap")
        try:
            self.snap.stop(disable=True)
        except snap.SnapError as e:
            raise GrafanaAgentServiceError("Failed to stop grafana-agent") from e

        self._update_status()

    def _on_remove(self, _event) -> None:
        """Uninstall the Grafana Agent snap."""
        self.unit.status = MaintenanceStatus("Uninstalling grafana-agent snap")
        try:
            self.snap.ensure(state=snap.SnapState.Absent)
        except snap.SnapError as e:
            raise GrafanaAgentInstallError("Failed to uninstall grafana-agent") from e

    def _on_upgrade_charm(self, event):
        """Upgrade the charm."""
        # This is .observe()'d in the base class and thus not observed here
        super()._on_upgrade_charm(event)
        self._install()

    def _on_cert_changed(self, event):
        """Event handler for cert change."""
        super()._on_cert_changed(event)
        # most cases are already resolved within `grafana_agent` parent object, but we don't have the notion of
        # tracing receivers in COS agent there so we need to update them separately.
        self._cos.update_tracing_receivers()

    @property
    def is_k8s(self) -> bool:
        """Is this a k8s charm."""
        return False

    def metrics_rules(self) -> Dict[str, Any]:
        """Return a list of metrics rules."""
        rules = self._cos.metrics_alerts

        topology = JujuTopology.from_charm(self)

        # Get the rules defined by Grafana Agent itself.
        own_rules = AlertRules(query_type="promql", topology=topology)
        own_rules.add_path(METRICS_RULES_SRC_PATH)
        if topology.identifier in rules:
            rules[topology.identifier]["groups"] += own_rules.as_dict()["groups"]
        else:
            rules[topology.identifier] = own_rules.as_dict()

        return rules

    def metrics_jobs(self) -> list:
        """Return a list of metrics scrape jobs."""
        return self._cos.metrics_jobs

    def logs_rules(self) -> Dict[str, Any]:
        """Return a list of logging rules."""
        return self._cos.logs_alerts

    @property
    def requested_tracing_protocols(self) -> Set[ReceiverProtocol]:
        """Return a list of requested tracing receivers."""
        protocols = self._cos.requested_tracing_protocols()
        protocols.update(
            receiver
            for receiver in get_args(ReceiverProtocol)
            if self.config.get(f"always_enable_{receiver}")
        )
        return protocols

    @property
    def dashboards(self) -> list:
        """Return a list of dashboards."""
        return self._cos.dashboards

    @property
    def is_ready(self) -> bool:
        """Checks if the charm is ready for configuration."""
        return self._is_installed

    def agent_version_output(self) -> str:
        """Runs `agent -version` and returns the output.

        Returns:
            Output of `agent -version`
        """
        return subprocess.run(["/bin/agent", "-version"], capture_output=True, text=True).stdout

    def read_file(self, filepath: Union[str, Path]):
        """Read a file's contents.

        Returns:
            A string with the file's contents
        """
        with open(filepath) as f:
            return f.read()

    def write_file(self, path: Union[str, Path], text: str) -> None:
        """Write text to a file.

        Args:
            path: file path to write to
            text: text to write to the file
        """
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def delete_file(self, path: Union[str, Path]):
        """Delete a file.

        Args:
            path: file to be deleted
        """
        os.remove(path)

    def stop(self) -> None:
        """Stop grafana agent."""
        try:
            self.snap.stop()
        except snap.SnapError as e:
            raise GrafanaAgentServiceError("Failed to restart grafana-agent") from e

    def restart(self) -> None:
        """Restart grafana agent."""
        try:
            self.snap.restart()
        except snap.SnapError as e:
            raise GrafanaAgentServiceError("Failed to restart grafana-agent") from e

    def run(self, cmd: List[str]):
        """Run cmd on the workload.

        Args:
            cmd: Command to be run.
        """
        subprocess.run(cmd)

    @property
    def _is_installed(self) -> bool:
        """Check if the Grafana Agent snap is installed."""
        return self.snap.present

    @property
    def _additional_integrations(self) -> Dict[str, Any]:
        """Additional integrations for machine charms."""
        node_exporter_job_name = (
            f"juju_{self.model.name}_{self.model.uuid}_{self.model.app.name}_node-exporter"
        )
        return {
            "node_exporter": {
                "rootfs_path": "/"
                if bool(self.config["classic_snap"])
                else "/var/lib/snapd/hostfs",
                "enabled": True,
                "enable_collectors": [
                    "logind",
                    "systemd",
                    "mountstats",
                    "processes",
                    "sysctl",
                ],
                "sysctl_include": [
                    "net.ipv4.neigh.default.gc_thresh3",
                ],
                "relabel_configs": [
                    # Align the "job" name with those of prometheus_scrape
                    {
                        "target_label": "job",
                        "regex": "(.*)",
                        "replacement": node_exporter_job_name,
                    },
                ]
                + self.relabeling_config,
            }
        }

    @property
    def _additional_log_configs(self) -> List[Dict[str, Any]]:
        """Additional logging configuration for machine charms."""
        endpoints = self._loki_endpoints_with_tls()
        return [
            {
                "name": "log_file_scraper",
                "clients": endpoints,
                "scrape_configs": [
                    {
                        "job_name": "varlog",
                        "pipeline_stages": [
                            {
                                "drop": {
                                    "expression": ".*file is a directory.*",
                                },
                            },
                        ],
                        "static_configs": [
                            {
                                "targets": ["localhost"],
                                "labels": {
                                    "__path__": "/var/log/**/*log",
                                    "job": "varlog",
                                    **self._own_labels,
                                },
                            }
                        ],
                    },
                    {
                        "job_name": "syslog",
                        "journal": {"labels": {**self._own_labels, **{"job": "syslog"}}},
                        "pipeline_stages": [
                            {
                                "drop": {
                                    "expression": ".*file is a directory.*",
                                },
                            },
                        ],
                    },
                ]
                + self._snap_plugs_logging_configs,
            }
        ]

    @property
    def _agent_relations(self) -> List[Relation]:
        """Return all relations from botih cos-agent and juju-info."""
        return self.model.relations["cos-agent"] + self.model.relations["juju-info"]

    @property
    def _own_labels(self) -> Dict[str, str]:
        """Return a dict with labels from the topology of the this charm."""
        return {
            # Dict ordering will give the appropriate result here
            "instance": self._instance_name,
            **self._instance_topology,
        }

    @property
    def relabeling_config(self) -> list:
        """Return a relabelling config with labels from the topology of the principal charm."""
        topology_relabels = (
            [
                {
                    "source_labels": ["__address__"],
                    "target_label": key,
                    "replacement": value,
                }
                for key, value in self._instance_topology.items()
            ]
            if self._own_labels
            else []
        )

        return [
            {
                "target_label": "instance",
                "regex": "(.*)",
                "replacement": self._instance_name,
            }
        ] + topology_relabels  # type: ignore

    def _evaluate_log_paths(self, paths: List[str], snap: str, app: str) -> List[str]:
        """Evaluate each log path using snap to resolve environment variables.

        Raises:
            Exception: If echo fails.
        """
        # There is a potential for shell injection here. It seems okay because the potential
        # attacking charm has root access on the machine already anyway.
        new_paths = []
        for path in paths:
            cmd = f"echo 'echo {path}' | snap run --shell {snap}.{app}"
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if p.returncode != 0:
                raise Exception(
                    f"Failed to evaluate path with command: {cmd}\nSTDOUT: {p.stdout}\nSTDERR: {p.stderr}"
                )
            new_paths.append(p.stdout.strip())
        return new_paths

    def _snap_plug_job(
        self, owner: str, target_path: str, app: str, unit: str, label_path: str
    ) -> dict:
        job_name = f"{owner}-{label_path.replace('/', '-')}"
        job = {
            "job_name": job_name,
            "static_configs": [
                {
                    "targets": ["localhost"],
                    "labels": {
                        "job": job_name,
                        "__path__": target_path,
                        **{  # from grafana-agent's topology
                            k: v
                            for k, v in self._instance_topology.items()
                            if k not in ["juju_unit", "juju_application"]
                        },
                        # from the topology of the charm owning the snap
                        "juju_application": app,
                        "juju_unit": unit,
                        "snap_name": owner,
                    },
                }
            ],
            "pipeline_stages": [
                {
                    "drop": {
                        "expression": ".*file is a directory.*",
                    },
                },
                {
                    "structured_metadata": {"filename": "filename"},
                },
                {
                    "labeldrop": ["filename"],
                },
            ],
        }

        job["relabel_configs"] = [
            {
                "source_labels": ["__path__"],
                "target_label": "path",
                "replacement": label_path if label_path.startswith("/") else f"/{label_path}",
            }
        ]
        return job

    def _path_label(self, path):
        """Best effort at figuring out what the path label should be.

        Try to make the path reflect what it would normally be with a non snap version of the
        software.
        """
        match = re.match("^.*(var/log/.*$)", path)
        if match:
            return match.group(1)
        match = re.match("^/var/snap/.*/common/(.*)$", path)
        if match:
            return match.group(1)
        # We couldn't figure it out so just use the full path.
        return path

    @property
    def _snap_plugs_logging_configs(self) -> List[Dict[str, Any]]:
        """One logging config for each separate snap connected over the "logs" endpoint."""
        agent_fstab = SnapFstab(Path("/var/lib/snapd/mount/snap.grafana-agent.fstab"))
        shared_logs_configs = []

        if self.config["classic_snap"]:
            # Iterate through each logging endpoint.
            for endpoint, topology in self._cos.snap_log_endpoints_with_topology:
                try:
                    with open(f"/snap/{endpoint.owner}/current/meta/snap.yaml") as f:
                        snap_yaml = yaml.safe_load(f)
                except FileNotFoundError:
                    logger.error(
                        f"snap file for {endpoint.owner} not found. It is likely not installed. Skipping."
                    )
                    continue
                # Get the directories we need to monitor.
                log_dirs = snap_yaml["slots"][endpoint.name]["source"]["read"]
                for key in snap_yaml["apps"].keys():
                    snap_app_name = key  # Just use any app.
                    break
                # Evaluate any variables in the paths.
                log_dirs = self._evaluate_log_paths(
                    paths=log_dirs, snap=endpoint.owner, app=snap_app_name
                )
                # Create a job for each path.
                for path in log_dirs:
                    job = self._snap_plug_job(
                        endpoint.owner,
                        f"{path}/**",
                        topology.application,
                        str(topology.unit),
                        self._path_label(path),
                    )
                    shared_logs_configs.append(job)
        else:
            endpoint_owners = {
                endpoint.owner: {
                    "juju_application": topology.application,
                    "juju_unit": topology.unit,
                }
                for endpoint, topology in self._cos.snap_log_endpoints_with_topology
            }
            for fstab_entry in agent_fstab.entries:
                if fstab_entry.owner not in endpoint_owners.keys():
                    continue

                target_path = (
                    f"{fstab_entry.target}/**"
                    if fstab_entry
                    else "/snap/grafana-agent/current/shared-logs/**"
                )

                job = self._snap_plug_job(
                    fstab_entry.owner,
                    target_path,
                    endpoint_owners[fstab_entry.owner]["juju_application"],
                    endpoint_owners[fstab_entry.owner]["juju_unit"],
                    fstab_entry.relative_target,
                )
                shared_logs_configs.append(job)

        return shared_logs_configs

    def _connect_logging_snap_endpoints(self):
        # We need to run _verify_snap_track so we make sure we have refreshed BEFORE connecting.
        self._verify_snap_track()
        if not self.config["classic_snap"]:
            for plug in self._cos.snap_log_endpoints:
                try:
                    self.snap.connect("logs", service=plug.owner, slot=plug.name)
                except snap.SnapError as e:
                    logger.error(f"error connecting plug {plug} to grafana-agent:logs")
                    logger.error(e.message)

    def positions_dir(self) -> str:
        """Return the positions directory."""
        return "${SNAP_DATA}"


if __name__ == "__main__":
    main(GrafanaAgentMachineCharm)
