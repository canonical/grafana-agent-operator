# External probes

These probes are meant to be run from the host where the juju client is installed,

```bash
juju export-bundle | ./probe_bundle.py
juju status --format=yaml | ./probe_status.py
```

or by piping in the bundle yaml,

```bash
cat bundle.yaml | ./probe_bundle.py
cat status.yaml | ./probe_status.py
```
