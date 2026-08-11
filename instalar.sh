#!/bin/bash
# Instala el reportero del tablero de cuentas de Claude en este Mac. Idempotente.
set -euo pipefail

RAW="https://raw.githubusercontent.com/santiago-prolibu/claude-tablero/main"
DIR="$HOME/.claude-tablero"
PLIST="$HOME/Library/LaunchAgents/com.prolibu.claude-tablero.plist"
LABEL="com.prolibu.claude-tablero"

mkdir -p "$DIR" "$HOME/Library/LaunchAgents"

# 1. PAT (solo la primera vez)
if [ ! -s "$DIR/token" ]; then
  printf "Pega el PAT de GitHub (scope gist): "
  read -r -s TOKEN < /dev/tty
  echo
  printf '%s' "$TOKEN" > "$DIR/token"
  chmod 600 "$DIR/token"
fi

# 2. Scripts
curl -fsSL "$RAW/reportar.py" -o "$DIR/reportar.py"
DESTINO_CMD="/usr/local/bin/cuentas"
if ! curl -fsSL "$RAW/cuentas.py" -o "$DESTINO_CMD" 2>/dev/null; then
  mkdir -p "$HOME/.local/bin"
  DESTINO_CMD="$HOME/.local/bin/cuentas"
  curl -fsSL "$RAW/cuentas.py" -o "$DESTINO_CMD"
  echo "aviso: instalado en $DESTINO_CMD — asegúrate de tener ~/.local/bin en el PATH"
fi
chmod +x "$DESTINO_CMD"

# 3. launchd
curl -fsSL "$RAW/com.prolibu.claude-tablero.plist" | sed "s|__HOME__|$HOME|g" > "$PLIST.tmp" && mv "$PLIST.tmp" "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# 4. Primer reporte (aquí macOS pregunta por el Keychain → "Permitir siempre")
echo "Primer reporte…"
/usr/bin/python3 "$DIR/reportar.py" && echo "ok — mira el tablero" || echo "fallo; revisa $DIR/reportar.log"
