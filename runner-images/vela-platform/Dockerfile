# vela-platform runner: the vela-linux runner plus the system packages intrect-platform's
# pytest job used to `sudo apt-get install` on a GitHub-hosted VM. An ARC pod runs as
# uid 1001 without sudo, so they are baked in here instead.
#   ffmpeg               audio decode/encode in the inference and mastering tests
#   libchromaprint-tools fpcalc (audio fingerprints)
#   libsndfile1          soundfile
ARG BASE=localhost/vela-linux-runner:20261016
FROM ${BASE}
USER root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ffmpeg libchromaprint-tools libsndfile1 \
 && rm -rf /var/lib/apt/lists/*
USER runner
