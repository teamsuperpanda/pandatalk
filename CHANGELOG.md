# Changelog

All notable changes to this project will be documented in this file.

## [1.1] - 2026-08-29
- Self-update: pandatalk checks GitHub for a new release at login (via the systemd user service) and installs it automatically. No manual updates needed.
- Existing installs: re-run the installer once so the service picks up the update check.

## [1.0.1] - 2026-08-29
- Autostart pandatalk on login via a systemd user service. No need to start it manually after install or reboot.

## [1.0.0] - 2026-08-18
- Initial release: hold a key, talk, and the words are typed into the focused window.
- Works on GNOME Wayland and X11 via raw evdev input and ydotool.
- On-device transcription with faster-whisper. The microphone is only open while the push-to-talk key is held.
- One-command Fedora installer that sets up ydotool (user service), portaudio, the input group, a virtualenv, and a `pandatalk` launcher.
- Persistent push-to-talk key via `--set-key`, with `--key` as a one-run override.
