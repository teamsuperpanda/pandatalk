#!/usr/bin/env bash
# Install or update pandatalk on Fedora. One command:
#   curl -fsSL https://raw.githubusercontent.com/teamsuperpanda/pandatalk/main/install.sh | bash
set -euo pipefail

APP_DIR="${PANDATALK_DIR:-$HOME/.local/share/pandatalk}"
REPO="https://github.com/teamsuperpanda/pandatalk.git"
USER_NAME="$(id -un)"

echo "==> pandatalk installer"

# 1. Get the code: sync an existing checkout to latest, or clone fresh.
if [ -d "$APP_DIR/.git" ]; then
    echo "==> updating existing checkout"
    git -C "$APP_DIR" fetch --depth 1 origin
    git -C "$APP_DIR" reset --hard origin/main
else
    echo "==> cloning into $APP_DIR"
    rm -rf "$APP_DIR"
    git clone --depth 1 "$REPO" "$APP_DIR"
fi

# 2. System packages: ydotool types the text, portaudio is the mic backend.
echo "==> installing system packages (ydotool, portaudio)"
sudo dnf install -y ydotool portaudio

# 3. ydotool daemon as YOUR user (not root) so the client can reach its socket.
#    The ydotool RPM only ships a system unit, which runs as root and creates a
#    root-owned socket the client cannot use. Write a user unit instead.
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/ydotool.service" <<'EOF'
[Unit]
Description=ydotoold (user)

[Service]
ExecStart=/usr/bin/ydotoold
Restart=always

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now ydotool \
    || echo "==> warning: could not start the ydotool user service (is your systemd user session running?)"

# 4. 'input' group so pandatalk can read raw keyboard events.
if id -nG "$USER_NAME" | grep -qw input; then
    echo "==> already in the 'input' group"
else
    sudo usermod -aG input "$USER_NAME"
    echo "==> added $USER_NAME to the 'input' group. Log out and back in once, then run pandatalk."
fi

# 5. Python dependencies in an isolated venv.
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade -r "$APP_DIR/requirements.txt"

# 6. Put `pandatalk` on your PATH.
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/pandatalk" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/pandatalk.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/pandatalk"

# 7. Autostart pandatalk on login via a systemd user service.
#    The whisper model is ~150 MB; first download may take a moment.
cat > "$HOME/.config/systemd/user/pandatalk.service" <<EOF
[Unit]
Description=Panda Talk push-to-talk dictation
After=ydotool.service
Requires=ydotool.service

[Service]
ExecStart=$HOME/.local/bin/pandatalk
Restart=on-failure

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now pandatalk \
    || echo "==> warning: could not enable pandatalk service (log out and back in, then: systemctl --user enable --now pandatalk)"

# 8. Pick a push-to-talk key (default LEFT CTRL). Read from /dev/tty so this
#    works even when the script is piped in via curl | bash. Falls back to the
#    default when there is no terminal (e.g. automated install).
echo
if printf 'Push-to-talk key [KEY_LEFTCTRL]: ' 2>/dev/null >/dev/tty; then
    IFS= read -r PTT_KEY </dev/tty || true
    PTT_KEY="${PTT_KEY:-KEY_LEFTCTRL}"
    if "$APP_DIR/.venv/bin/python" "$APP_DIR/pandatalk.py" --set-key "$PTT_KEY" >/dev/null 2>&1; then
        echo "Push-to-talk key: $PTT_KEY"
    else
        echo "Unknown key '$PTT_KEY', using KEY_LEFTCTRL. Change later with: pandatalk --set-key KEY"
    fi
else
    echo "No terminal to prompt on; using KEY_LEFTCTRL. Change later with: pandatalk --set-key KEY"
fi

echo
if command -v pandatalk >/dev/null 2>&1; then
    echo "Done. Run: pandatalk"
else
    echo "Done. Add $HOME/.local/bin to your PATH, then run: pandatalk"
fi
echo "  (hold the key you chose and talk; see --help for options)"
