# vela-linux runner image

The image behind the `vela-linux` ARC scale set on vela's k3s (`runs-on: vela-linux`,
runner group `vela-k3s`). Every job gets a fresh pod from it.

| File | Holds |
|---|---|
| `Dockerfile` | `ubuntu:26.04` (pinned by digest) rebuilt into what the stock `actions-runner` image provides (runner 2.338.2, k8s hooks, user `runner`), plus the tools jobs cannot install themselves, plus pre-warmed Python and Node tool caches. |
| `values.yaml` | The scale set's Helm values. The image line is filled in by `deploy.sh`. |
| `deploy.sh` | Build, import into k3s's containerd, `helm upgrade`. |

## Why Ubuntu 26.04 and not the stock image

vela runs Ubuntu 26.04 (glibc 2.43) since 2026-11-05. On the stock image (24.04,
glibc 2.39) about 1% of pods lost Runner.Listener mid-job: exit code 139, with the
kernel logging a general protection fault inside glibc 2.39's `abort()`. The systemd
runners on the host run the same runner tarball on glibc 2.43 and never crashed. The
stock image is built on `dotnet/runtime-deps:8.0-noble`, and MCR publishes no 8.0 tag for
26.04, so the Dockerfile rebuilds what it provides on `ubuntu:26.04`. Left out on purpose: the
Docker CLI and buildx (the pods have no Docker daemon) and the git-core PPA.

Moving the base changes the job environment too: gcc 15 instead of 13, system
`python3` 3.14 instead of 3.12 (`python3.12` now points at the tool-cache 3.12.15), fish
4.2 instead of 3.7, Rust uutils as the default coreutils, and git 2.53 from the archive
instead of the PPA's 2.55. setup-python on 26.04 can only download
versions that actions/python-versions builds for 26.04: recent patch releases of 3.10
and newer only.

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
`NODE_VERSION` together with the URLs (the Python URL is the `linux-26.04` build).
The base digest, `RUNNER_VERSION` and the hook versions move only on purpose, each with
its checksum.
