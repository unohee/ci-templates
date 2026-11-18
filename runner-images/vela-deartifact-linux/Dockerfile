# de-artifact ARC runner for the `build (linux)` job: the vela-linux image plus the
# native packages nih-plug (VST3/CLAP, baseview X11/Wayland, wgpu) and openssl-sys need,
# and a rustup-managed stable toolchain. Pods run with no-new-privileges, so nothing can
# be apt-installed at job time; everything the job checks with pkg-config lives here.
FROM localhost/vela-linux-runner:20261027
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential pkg-config libssl-dev \
      libx11-dev libx11-xcb-dev libxcb1-dev libxcb-icccm4-dev libxcb-util-dev \
      libxcb-dri2-0-dev libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev \
      libegl1-mesa-dev libgles2-mesa-dev libgl-dev libxcursor-dev libxrandr-dev \
      libxi-dev libasound2-dev libjack-jackd2-dev \
 && rm -rf /var/lib/apt/lists/*
USER runner
ENV CARGO_HOME=/home/runner/.cargo RUSTUP_HOME=/home/runner/.rustup
ENV PATH=/home/runner/.cargo/bin:$PATH
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable \
      --component rustfmt,clippy \
 && rustc -V && cargo -V
