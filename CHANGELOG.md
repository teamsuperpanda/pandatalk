# Changelog

All notable changes to this project will be documented in this file.

## [1.1] - 2026-08-29
- **Streaming**: words are typed as you speak them while the key is held, instead of all at once after you release.
- **Punctuation**: say "question mark", "comma", "period", and ~30 other words or phrases and they are typed as the symbol instead of the words.
- **Smart spacing**: single spaces, punctuation glued to the word before it (no space before a comma or question mark), and sentence-start capitalization.
- **Firm tap protection**: the microphone does not open at all until the key has been held a moment, so accidental taps never arm the mic and never steal input.
- **Autostart**: pandatalk starts on login via a systemd user service. No need to start it manually after install or reboot.
- **Self-update**: pandatalk checks GitHub for a new release at login (via the systemd user service) and installs it automatically. No manual updates needed.

## [1.0.0] - 2026-08-18
- Initial release: hold a key, talk, and the words are typed into the focused window.
- Works on GNOME Wayland and X11 via raw evdev input and ydotool.
- On-device transcription with faster-whisper. The microphone is only open while the push-to-talk key is held.
- One-command Fedora installer that sets up ydotool (user service), portaudio, the input group, a virtualenv, and a `pandatalk` launcher.
- Persistent push-to-talk key via `--set-key`, with `--key` as a one-run override.
