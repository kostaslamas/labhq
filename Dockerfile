# syntax=docker/dockerfile:1.7
#
# labhq in one image (#69): `labhq serve` with its UI, git, tmux, cloudflared and the Claude
# Code binary. Node only builds the UI into the wheel; the final image carries no Node and no
# build tools. See docs/guide/containers.md.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.17

FROM ${UV_IMAGE} AS uv

# The wheel with the built UI: the build hook (tools/build_web.py) runs `npm ci` and
# `npm run build`, so this stage needs Node and a Python that uv provides.
FROM ${NODE_IMAGE} AS wheel
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON=3.12 \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY tools/ tools/
COPY migrations/ migrations/
COPY src/ src/
COPY web/ web/
RUN --mount=type=cache,target=/root/.npm \
    --mount=type=cache,target=/root/.cache/uv \
    uv build --wheel --out-dir /dist \
    && uv run --no-project python -m tools.build_web check-wheel /dist/*.whl

# Pinned binaries, each checked before it reaches the final image.
FROM ${NODE_IMAGE} AS binaries
ARG TARGETARCH
# The Claude Code build that runs pin through `cli_path` (spikes/agent_sdk/RESULTS.md); the
# SDK wheel bundles a different one. Bump with the version recorded in docs/checks/.
ARG CLAUDE_CODE_VERSION=2.1.288
ARG CLOUDFLARED_VERSION=2026.9.3
ARG CLOUDFLARED_SHA256_AMD64=77e26d8d900e0b8469f416239d14b5f296525fdf79fee6f511ef55609e3fbac2
ARG CLOUDFLARED_SHA256_ARM64=aaeb2d7d0da3614634c7e03ab13487a1522c2e79165ed2929cfe23d5e95b326d
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
# npm verifies the tarball against the registry's integrity hash; the native package holds
# one self-contained binary, so the final image needs no Node to run it.
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) claude_arch=x64; cloudflared_sha="${CLOUDFLARED_SHA256_AMD64}" ;; \
      arm64) claude_arch=arm64; cloudflared_sha="${CLOUDFLARED_SHA256_ARM64}" ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    mkdir -p /out; \
    npm pack --silent "@anthropic-ai/claude-code-linux-${claude_arch}@${CLAUDE_CODE_VERSION}"; \
    tar --extract --gzip --file ./*.tgz package/claude; \
    install -m 0755 package/claude /out/claude; \
    /out/claude --version | grep -q "^${CLAUDE_CODE_VERSION} "; \
    curl --fail --silent --show-error --location --retry 3 --output /out/cloudflared \
      "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${TARGETARCH}"; \
    echo "${cloudflared_sha}  /out/cloudflared" | sha256sum --check --strict; \
    chmod 0755 /out/cloudflared; \
    /out/cloudflared --version

# The locked runtime dependencies (`uv.lock`), then the wheel on top without resolving again.
FROM ${PYTHON_IMAGE} AS venv
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/labhq \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY --from=wheel /dist/ /dist/
RUN uv pip install --python /opt/labhq/bin/python --no-deps /dist/*.whl \
    && /opt/labhq/bin/labhq --version

FROM ${PYTHON_IMAGE} AS runtime
# Match the owner of the host directory with the project repositories, so git inside the
# container accepts them and writes files the host user owns.
ARG UID=1000
ARG GID=1000
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git openssh-client tmux \
    && rm -rf /var/lib/apt/lists/*
RUN test "${UID}" != 0 && test "${GID}" != 0 \
    && groupadd --non-unique --gid "${GID}" labhq \
    && useradd --non-unique --uid "${UID}" --gid "${GID}" --create-home \
      --home-dir /home/labhq --shell /bin/bash labhq \
    && install -d -o labhq -g labhq /data /projects
COPY --from=binaries /out/claude /out/cloudflared /usr/local/bin/
COPY --from=venv /opt/labhq /opt/labhq
# The pinned binary is on a path the user cannot write, and its updater is off, so the
# version stays the one `cli_path` names.
ENV PATH=/opt/labhq/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    LABHQ_DATA_DIR=/data \
    LABHQ_CLI_PATH=/usr/local/bin/claude \
    DISABLE_AUTOUPDATER=1
USER labhq
WORKDIR /home/labhq
EXPOSE 8787
# Inside the container the server binds every interface; compose publishes it on the host's
# 127.0.0.1 only.
CMD ["sh", "-c", "labhq init && exec labhq serve --host 0.0.0.0 --port 8787"]
