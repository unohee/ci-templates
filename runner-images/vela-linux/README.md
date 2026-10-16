# vela-linux runner image

The image behind the `vela-linux` ARC scale set on vela's k3s (`runs-on: vela-linux`,
runner group `vela-k3s`). Every job gets a fresh pod from it.

| File | Holds |
|---|---|
| `Dockerfile` | The stock `actions-runner` image (pinned by digest), plus the tools jobs cannot install themselves, plus pre-warmed Python and Node tool caches. |
| `values.yaml` | The scale set's Helm values. The image line is filled in by `deploy.sh`. |
| `deploy.sh` | Build, import into k3s's containerd, `helm upgrade`. |

## Why a custom image

Pods run without sudo (`allowPrivilegeEscalation: false`). The stock image lacks `file`,
`gh`, `ss`, `lsof`, `zsh` and `fish`. On vega-cli PR #15 (2026-10-16) the release's Mach-O
check and publish step, `vega daemon start`, and the zsh/fish completion tests all needed
these tools. Every pod also started with an empty tool cache, so setup-python cost 7 s and
setup-node cost 5 s per job.

The pre-warmed versions are Python 3.12.15 and Node 22.23.3. A workflow that asks for
another version still downloads it, so a stale image is slower but never wrong.

## Updating

```bash
./deploy.sh 20261016          # tag = build date
```

Jobs that are already running keep the image they started with. Bump `PYTHON_*` and
`NODE_VERSION` together with the URLs. The base digest moves only on purpose.
