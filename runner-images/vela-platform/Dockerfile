# vela-platform runner: the vela-linux runner plus the system packages intrect-platform's
# pytest job used to `sudo apt-get install` on a GitHub-hosted VM. An ARC pod runs as
# uid 1001 without sudo, so they are baked in here instead.
#   ffmpeg               audio decode/encode in the inference and mastering tests
#   libchromaprint-tools fpcalc (audio fingerprints)
#   libsndfile1          soundfile
#   libatomic1           pnpm's standalone binary (@pnpm/exe) links it; hosted runners ship it
#   rsync                tests/test_sync_vendor_guard.py drives scripts/sync-artifactnet-vendor.sh
#   python3.12-venv      backup-freshness.yml builds a throwaway venv from /usr/bin/python3.
#                        vela-linux's current image ships it, but this layer declares it too:
#                        with the 20261016 base both backup jobs died inside `python3 -m venv`
#                        ("ensurepip is not available") before they ever reached R2
#                        (scheduled run 40380349519, 2026-10-26).
ARG BASE=localhost/vela-linux-runner:20261026d
FROM ${BASE}
USER root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ffmpeg libchromaprint-tools libsndfile1 libatomic1 rsync python3.12-venv \
 && rm -rf /var/lib/apt/lists/*
USER runner
