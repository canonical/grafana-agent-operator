# External probes

These probes are meant to be run from the host where the juju client is installed,

```bash
juju export-bundle | ./bundle/probe_bundle.py
juju status --format=yaml | ./status/probe_status.py
```

or by piping in the bundle yaml,

```bash
cat bundle.yaml | ./bundle/probe_bundle.py
cat status.yaml | ./status/probe_status.py
```
