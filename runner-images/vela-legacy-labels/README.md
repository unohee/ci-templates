# vela-legacy-labels runner scale set

A second ARC scale set on vela's k3s, running the **same image** as `vela-linux`
(`localhost/vela-linux-runner:<tag>`), that answers the three labels the persistent
systemd runners on vela carried until 2026-10-27:

| Label | What asks for it |
|---|---|
| `de-artifact-linux` | `de-artifact/.github/workflows/ci-rust.yml` → `build (linux)` (native GUI link step) |
| `cost-linux-secure` | `de-artifact` release → "verify GitHub Release assets" |
| `cost-linux` | `de-artifact` CodeQL and code-quality default setup (`runner_type: labeled`, `runner_label: cost-linux`) |

`self-hosted`, `Linux` and `X64` come for free — ARC adds them to every runner.

## Why a second scale set instead of more labels on `vela-linux`

ARC registers a scale set's labels **once**, in the `CreateRunnerScaleSet` call. Editing
`runnerScaleSetLabels` and running `helm upgrade` updates the Kubernetes object and
nothing in GitHub: the pods keep being created with the old labels, so the jobs asking
for the new ones stay queued while the scale set reports `Running`
(actions/actions-runner-controller#4424 — the controller only reads those labels when the
scale set does not exist yet). Measured here on 2026-10-27: after adding the labels to
`vela-linux` and upgrading, two `cost-linux` jobs stayed queued for 10 minutes while that
scale set cheerfully started and stopped nine pods.

The only way to change a scale set's labels in place is to recreate it, which kills every
job running on it. `vela-linux` carries most of the org's Linux CI, so these labels got
their own object. This one is disposable: delete it once the callers above are pointed at
`vela-linux`.

## Files

| File | Holds |
|---|---|
| `values.yaml` | Helm values. The image line is filled in by `deploy.sh`. |
| `deploy.sh` | `helm upgrade --install` against an image `vela-linux`'s deploy already imported. |

## Deploy

```bash
# the image must already exist in k3s's containerd:
~/dev/ci-templates/runner-images/vela-linux/deploy.sh 20261027
./deploy.sh 20261027
```

`deploy.sh` refuses to run when the image is missing: k3s cannot pull
`localhost/...`, so the failure would otherwise appear as `ImagePullBackOff` on the
first job instead of at the terminal.

## Verify

```bash
# a job is the only honest test — ARC labels are invisible to the runner API:
gh run list --repo Intrect-io/de-artifact --limit 5
gh api repos/Intrect-io/de-artifact/actions/runs/<id>/jobs \
  -q '.jobs[] | [.name,.status,.runner_name] | @tsv'
```

`runner_name` starts with `vela-legacy-labels-runner-` when a pod served it.
