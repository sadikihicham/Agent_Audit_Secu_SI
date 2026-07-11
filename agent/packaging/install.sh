#!/usr/bin/env bash
# Installe l'agent GuardianOps AI comme service systemd natif sur l'hôte à surveiller.
#
# Pourquoi natif (pas Docker) : dans un conteneur, l'agent ne voit que le réseau du conteneur
# et ne peut pas scanner le vrai LAN de l'hôte (cf. docs/runbook.md §9). Un binaire natif +
# systemd assure aussi la persistance (redémarrage automatique, survit à un reboot) — ce que
# `cargo run --release` seul ne fait pas.
#
# Usage (depuis n'importe où, sur l'hôte à monitorer, en root) :
#   sudo ./install.sh
#
# Prérequis : Rust/Cargo installés (https://rustup.rs), ou passer INSTALL_BIN=<chemin binaire
# déjà compilé> pour sauter le build (ex. binaire cross-compilé ailleurs).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/guardianops-agent"
SERVICE_USER="guardianops"
SERVICE_FILE="guardianops-agent.service"
BIN_NAME="guardianops-agent"

if [[ $EUID -ne 0 ]]; then
  echo "Ce script doit être lancé en root (sudo ./install.sh)." >&2
  exit 1
fi

# ── 1. Binaire ────────────────────────────────────────────────────────────────
if [[ -n "${INSTALL_BIN:-}" ]]; then
  echo "→ Utilisation du binaire fourni : $INSTALL_BIN"
  BIN_PATH="$INSTALL_BIN"
else
  echo "→ Compilation en mode release (cargo build --release)…"
  ( cd "$AGENT_SRC_DIR" && cargo build --release )
  BIN_PATH="$AGENT_SRC_DIR/target/release/$BIN_NAME"
fi

if [[ ! -x "$BIN_PATH" ]]; then
  echo "Binaire introuvable ou non exécutable : $BIN_PATH" >&2
  exit 1
fi

# ── 2. Utilisateur système dédié (non-root, pas de home, pas de shell) ────────
if ! id "$SERVICE_USER" &>/dev/null; then
  echo "→ Création de l'utilisateur système $SERVICE_USER"
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# ── 3. Répertoire d'installation ──────────────────────────────────────────────
echo "→ Installation dans $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
install -m 755 -o "$SERVICE_USER" -g "$SERVICE_USER" "$BIN_PATH" "$INSTALL_DIR/$BIN_NAME"

if [[ ! -f "$INSTALL_DIR/agent.toml" ]]; then
  echo "→ Copie de agent.toml.example (à éditer AVANT le premier démarrage : api_url + enroll_token)"
  install -m 640 -o "$SERVICE_USER" -g "$SERVICE_USER" \
    "$AGENT_SRC_DIR/agent.toml.example" "$INSTALL_DIR/agent.toml"
else
  echo "→ agent.toml existant conservé (non écrasé)"
fi
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 4. Service systemd ─────────────────────────────────────────────────────────
echo "→ Installation du service systemd"
install -m 644 "$SCRIPT_DIR/$SERVICE_FILE" "/etc/systemd/system/$SERVICE_FILE"
systemctl daemon-reload
systemctl enable "$SERVICE_FILE"

cat <<EOF

✅ Installé. Prochaines étapes :
  1. Éditer $INSTALL_DIR/agent.toml (api_url + enroll_token — obtenu via
     POST /machines sur l'API GuardianOps, cf. docs/runbook.md §3).
  2. Démarrer :   systemctl start $SERVICE_FILE
  3. Vérifier :   systemctl status $SERVICE_FILE   /   journalctl -u $SERVICE_FILE -f
  4. Après le premier enrôlement réussi, $INSTALL_DIR/agent_state.toml est créé
     automatiquement — enroll_token peut alors être retiré de agent.toml.
EOF
