# vela-rust-ci

ARC scale set for the Rust workflows of de-leak-rt, patina and intrect-plugin
(`runs-on: vela-rust-ci`). It replaces the systemd runners `rtx-rust-ci-1/2` (label
`rust-ci`). Cargo target dirs persist on NVMe through a hostPath
(`RUST_CI_TARGET_ROOT=/cache/cargo-target`).

The Dockerfile copies a prebuilt `cargo-audit` 0.22.2 binary from this directory. The
binary is not committed (25 MB, `.gitignore`). Put it here before building:

```bash
cargo install cargo-audit --version 0.22.2 --locked --root /tmp/ca
cp /tmp/ca/bin/cargo-audit .
./deploy.sh 20261108b
```

These files were written on vela on 2026-11-08 and committed on 2026-11-15 (AGT-4910).
The values equal the live release apart from the image tag, which `deploy.sh` fills in.
