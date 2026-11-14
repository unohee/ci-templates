# ARC runner scale sets

Every scale set in vela's k3s cluster (`kubectl get autoscalingrunnersets -A`) and where
its definition lives. A scale set that is not in this table has no definition, and the
next `helm upgrade` from an old file will overwrite the live values. That is how the
arc-runners quota was lost once (AUD-2467).

| Namespace/scale set | Definition | Image |
|---|---|---|
| `arc-runners/vela-linux` | `vela-linux/` | `vela-linux/Dockerfile` |
| `arc-runners/vela-ci` | `vela-ci/` | `vela-ci/Dockerfile` |
| `arc-runners/vela-legacy-labels` | `vela-legacy-labels/` | `vela-linux` image |
| `arc-runners/vela-platform` | `vela-platform/` | `vela-platform/Dockerfile` |
| `arc-runners/vela-rust-ci` | `vela-rust-ci/` | `vela-rust-ci/Dockerfile` (+ `cargo-audit` binary, not committed) |
| `arc-runners/vela-deartifact-linux` | `vela-deartifact-linux/` | `vela-deartifact-linux/Dockerfile` |
| `arc-runners/vela-deartifact-serverless` | `vela-deartifact-serverless/` | `vela-linux` image + `docker:27.5-dind` |
| `arc-runners/mini-linux` | `mini-linux/` | stock `ghcr.io/actions/actions-runner` |
| `arc-runners/macstudio-linux` | `macstudio-linux/` | stock `ghcr.io/actions/actions-runner` |
| `arc-cgf/vela-cgf-dind` | cgf-portal `infra/ci/arc/vela-cgf-dind.values.yaml` | cgf-portal `infra/ci/arc/image/Dockerfile` |

`vela-cgf-dind` stays in cgf-portal because that repository owns its namespace, its
runner contract test and its image. It is listed here so this table covers the whole
cluster.

## Checking repository against cluster

`IMAGE_PLACEHOLDER` (and `MEMORY_LIMIT_PLACEHOLDER` in vela-ci) are filled in by each
`deploy.sh`. Everything else should equal the live release:

```bash
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm get values -n arc-runners <name> -o yaml
```

On 2026-11-15 (AGT-4910) every values file here matched its live release apart from those
placeholders. `scripts/test_runner_images.py` checks that each directory names its own
scale set and that no values file carries an inline credential (this repository is public;
the GitHub App credentials live in the `arc-github-app` Kubernetes secret).
