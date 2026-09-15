FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm@sha256:8179b9d5f68dab0def4e113f924e6aed989a636e65ab58fbe0c8e808b046ac40

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
