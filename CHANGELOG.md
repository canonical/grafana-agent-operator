# Changelog

Changes on `track/0.44` since the common ancestor with `track/2` (`0d60680`).

## Features

- feat: add charms blueprint ([#412](https://github.com/canonical/grafana-agent-operator/pull/412))
- feat(terraform): Support for Juju provider v2 ([#395](https://github.com/canonical/grafana-agent-operator/pull/395))
- feat(terraform): add channel validation and split outputs ([#389](https://github.com/canonical/grafana-agent-operator/pull/389))
- feat: change default track to 'dev' in release workflow ([a762ffd](https://github.com/canonical/grafana-agent-operator/commit/a762ffdc5385070142fd40432bc5b31580232ff9))

## Fixes

- fix: fixes gagent panic on loki relation ([#384](https://github.com/canonical/grafana-agent-operator/pull/384))
- fix: Always set a `job_name` for all scrape_configs ([#383](https://github.com/canonical/grafana-agent-operator/pull/383))
- fix: automatically render job_name for metrics_endpoints ([#371](https://github.com/canonical/grafana-agent-operator/pull/371))
- fix: clone rather than ref mutable generic alert groups ([#370](https://github.com/canonical/grafana-agent-operator/pull/370))
- fix: bump LIBPATCH ([#358](https://github.com/canonical/grafana-agent-operator/pull/358))

## Others

- chore: update terraform-docs ([b1617d9](https://github.com/canonical/grafana-agent-operator/commit/b1617d94dea48e2f4388419f3d91bb4098d3efbf))
- chore(blueprints): refresh charms.just ([ce195d3](https://github.com/canonical/grafana-agent-operator/commit/ce195d35da328d593590c7060d7dc33a3361a6fd))
- chore: refresh charms.just from canonical/observability ([ae7e156](https://github.com/canonical/grafana-agent-operator/commit/ae7e156259d684b78cd8298c579e091cbef681de))
- ci: fix the secrets in the release workflow ([8ebb108](https://github.com/canonical/grafana-agent-operator/commit/8ebb108296821009799417e9bb7e94c7e8ee3e38))
- chore: update charm libraries ([#411](https://github.com/canonical/grafana-agent-operator/pull/411))
- chore: update charm libraries ([#410](https://github.com/canonical/grafana-agent-operator/pull/410))
- chore: update charm libraries ([#409](https://github.com/canonical/grafana-agent-operator/pull/409))
- chore: update charm libraries ([#408](https://github.com/canonical/grafana-agent-operator/pull/408))
- chore: update charm libraries ([#406](https://github.com/canonical/grafana-agent-operator/pull/406))
- chore: update charm libraries ([#404](https://github.com/canonical/grafana-agent-operator/pull/404))
- chore: update charm libraries ([#403](https://github.com/canonical/grafana-agent-operator/pull/403))
- chore: update charm libraries ([#402](https://github.com/canonical/grafana-agent-operator/pull/402))
- chore: update charm libraries ([#401](https://github.com/canonical/grafana-agent-operator/pull/401))
- chore: update charm libraries ([#400](https://github.com/canonical/grafana-agent-operator/pull/400))
- chore: update charm libraries ([#399](https://github.com/canonical/grafana-agent-operator/pull/399))
- chore: update charm libraries ([#398](https://github.com/canonical/grafana-agent-operator/pull/398))
- chore: update charm libraries ([#397](https://github.com/canonical/grafana-agent-operator/pull/397))
- chore: update charm libraries ([#396](https://github.com/canonical/grafana-agent-operator/pull/396))
- chore: update charm libraries ([#388](https://github.com/canonical/grafana-agent-operator/pull/388))
- ci: fix token permissions for release workflow ([#394](https://github.com/canonical/grafana-agent-operator/pull/394))
- ci: add explicit workflow permissions for CodeQL ([#393](https://github.com/canonical/grafana-agent-operator/pull/393))
- ci: remove unused quality gate workflow ([efeff10](https://github.com/canonical/grafana-agent-operator/commit/efeff109f8c0d7e2fbea27786da0c45d7ad543ff))
- Revise end of life date in README ([6cf5855](https://github.com/canonical/grafana-agent-operator/commit/6cf585506189c0606164882f9584f3f6346dc72a))
- Add eol warning ([#392](https://github.com/canonical/grafana-agent-operator/pull/392))
- chore(ci): bump reusable workflows to v2 ([#391](https://github.com/canonical/grafana-agent-operator/pull/391))
- chore: update charm libraries ([#381](https://github.com/canonical/grafana-agent-operator/pull/381))
- chore: update charm libraries ([#373](https://github.com/canonical/grafana-agent-operator/pull/373))
- chore: update charm libraries ([#372](https://github.com/canonical/grafana-agent-operator/pull/372))
- Transfer ownership ([#368](https://github.com/canonical/grafana-agent-operator/pull/368))
- test: refactor e2e unit tests to avoid ops.testing.Context.charm_spec ([#355](https://github.com/canonical/grafana-agent-operator/pull/355))
- chore: update charm libraries ([#364](https://github.com/canonical/grafana-agent-operator/pull/364))
- Add more platforms ([#337](https://github.com/canonical/grafana-agent-operator/pull/337))
- Fix config status being overwritten after exception handling ([#352](https://github.com/canonical/grafana-agent-operator/pull/352))
- Add checklist to PR template ([#353](https://github.com/canonical/grafana-agent-operator/pull/353))
- chore: update charm libraries ([#350](https://github.com/canonical/grafana-agent-operator/pull/350))
- chore: update charm libraries ([#348](https://github.com/canonical/grafana-agent-operator/pull/348))
- chore: update charm libraries ([#347](https://github.com/canonical/grafana-agent-operator/pull/347))
- chore: implement new prometheus remote write requirements ([#343](https://github.com/canonical/grafana-agent-operator/pull/343))
- excluded k8s csi mountpoints from disk usage monitoring ([#342](https://github.com/canonical/grafana-agent-operator/pull/342))

