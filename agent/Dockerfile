# ── Build stage ───────────────────────────────────────────────────────────────
# `rust:latest` est basé sur Debian trixie (glibc 2.41). Le runtime ci-dessous
# doit utiliser la même base (trixie) pour éviter « GLIBC_2.x not found ».
FROM rust:latest AS builder

WORKDIR /build

# Dépendances système (pour reqwest + OpenSSL si nécessaire)
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Mise en cache des dépendances Cargo avant de copier le code source.
COPY Cargo.toml ./
RUN mkdir src && echo 'fn main(){}' > src/main.rs && cargo build --release && rm -rf src

COPY src ./src
# Touch main.rs pour forcer la recompilation du binaire final.
RUN touch src/main.rs && cargo build --release

# ── Runtime stage ─────────────────────────────────────────────────────────────
# trixie-slim : même base Debian que le builder (rust:latest) → glibc compatible.
FROM debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m guardian

# Binaire dans PATH; données (config/state/queue) dans /agent monté par l'utilisateur.
COPY --from=builder /build/target/release/guardianops-agent /usr/local/bin/

WORKDIR /agent
USER guardian

ENTRYPOINT ["guardianops-agent"]
