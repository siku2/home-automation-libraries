FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:0f08c317b197f4036bca0514ef0fa52ce5cc9dc47056569c2263272f561aa8c1

SHELL ["/bin/bash", "-c"]

RUN <<EOF
set -euo pipefail

PIPX_DEPS=(
    git-cliff
    typos
    uv
)

for dep in "${PIPX_DEPS[@]}"; do
    pipx install "$dep"
done
EOF
