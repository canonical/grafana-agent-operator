# Smoke tests

The pupose of the smoke tests is to make sure the charms packs fine and deploys fine.
This give us coverage for:

- Python package import errors that may differ across bases compared to what we run itests on.


## Usage
From the charm's root,

```bash
charmcraft pack
juju deploy ./tests/manual/smoke/amd64.yaml
````
