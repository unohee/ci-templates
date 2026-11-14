# vela-platform runner

The `vela-platform` ARC scale set on vela's k3s (`runs-on: vela-platform`, runner group `vela-k3s`).
It serves intrect-platform's CI after GitHub-hosted jobs stopped starting on 2026-10-25 (billing block).

| File | Holds |
|---|---|
| `Dockerfile` | `vela-linux-runner` plus ffmpeg, libchromaprint-tools (fpcalc) and libsndfile1, which the pytest job used to `sudo apt-get install` on a hosted VM. The pod runs as uid 1001 without sudo. |
| `values.yaml` | Helm values. Redis and Postgres run as **native sidecars** (`initContainers` + `restartPolicy: Always`): each passes a startupProbe before the runner starts and stops when the runner exits. |
| `deploy.sh` | `./deploy.sh <tag> <vela-linux base tag>`: build on top of the vela-linux image, import into k3s's containerd, `helm upgrade --install vela-platform`. Never touches vela-linux or vela-ci. |

## Why sidecars
An ARC pod has no Docker, so a workflow's `services:` and `docker run` cannot work. The databases
ride in the pod and answer on localhost: Redis on 6379 (the pytest job's
`redis://localhost:6379/15`), Postgres on 5432 (`CI_SIDECAR_PG_URL`, read only by
`scripts/ci-local.sh wallet-pg`). Plain extra containers would keep the pod Running after the job and
ARC would never see the ephemeral runner finish; native sidecars avoid that.

## Sizing
vela also serves paid inference (GPU) and is a workstation: 60 GB RAM, ~11 GB available, load 8-10
on 16 cores (2026-10-26). Pods live under k3s `cgroup-root=/ci` with `system-reserved=30Gi`, so
eviction removes CI pods, never host services. Runner limit 6 Gi / 2 CPU, sidecars 256 Mi + 768 Mi,
`maxRunners: 2`. Measure a full pytest run in the pod and adjust.

## k3s eviction (fixed 2026-10-26)
ARC was dead from 2026-10-23: the node carried a DiskPressure taint because the root disk (3.6 TB) had
172 GB free, under a `nodefs.available<5%` threshold (180 GB). The threshold is now absolute
(`<30Gi`) in `/etc/rancher/k3s/config.yaml`. The same pressure had garbage-collected the
`vela-ci-runner` image; rebuild it with `../vela-ci/deploy.sh`.
