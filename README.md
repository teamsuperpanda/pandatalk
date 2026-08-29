# Panda Talk

<p align="center">
  <img src="assets/logo.png" alt="Panda Talk" width="160">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/Fedora-only-294172?style=flat-square" alt="Fedora only">
  <img src="https://img.shields.io/badge/version-1.1-brightgreen?style=flat-square" alt="Version">
</p>

Push-to-talk dictation for Fedora. Hold a key, speak, and your words are typed
into whatever window has focus. No cloud, no accounts, no always-on mic.

Built by [Team Super Panda](https://www.teamsuperpanda.com).

---

## What it does

- **Push to talk**: the microphone is only open while you hold the key. Tap it and nothing happens.
- **Works on Wayland and X11**: keys are read from raw input devices and text is injected with ydotool, so there is no X11 dependency.
- **On-device transcription**: runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper) locally on CPU. Nothing leaves your machine.
- **Streaming**: your words appear in the focused window as you speak, not all at once after you release.
- **Punctuation**: say "question mark", "comma", "period", or "new line" and the symbol is typed instead of the words.
- **Private by default**: nothing is recorded or stored while idle, and nothing is kept after typing.

## Requirements

- **Fedora Linux** (GNOME Wayland or X11). Other distributions are not supported.

## Install

One command:

```bash
curl -fsSL https://raw.githubusercontent.com/teamsuperpanda/pandatalk/main/install.sh | bash
```

The installer does everything: installs ydotool and portaudio, adds you to the
`input` group, sets up a virtualenv, puts `pandatalk` on your PATH, and
registers it as a systemd user service that starts on login. It then asks which
key you want to hold to talk - press Enter to keep `LEFT CTRL`, or type a key
name like `KEY_CAPSLOCK`.

pandatalk starts `ydotoold` itself, on demand, only while it is typing, and
stops it again a few seconds later. The daemon is deliberately NOT left running
as a background service: a persistent ydotoold virtual keyboard clashes with the
real keyboard on Wayland/GNOME and can lock up the input session.

If it adds you to the `input` group, log out and back in once before first use.

## Usage

```bash
pandatalk                          # hold LEFT CTRL and talk
pandatalk --set-key KEY_CAPSLOCK   # change the key permanently (saved to config)
pandatalk --key KEY_RIGHTSHIFT     # change the key for this run only
pandatalk --model tiny.en          # smaller, faster model
pandatalk --model small.en         # more accurate, slower
pandatalk --device /dev/input/event4  # pick a specific keyboard
pandatalk --version                # print the version
pandatalk --selftest               # verify the audio math, no mic needed
```

`--set-key` stores your choice in `~/.config/pandatalk/config.json`. Precedence is
`--key` (one run) over the saved config over the `KEY_LEFTCTRL` default. Valid
names are evdev key names such as `KEY_CAPSLOCK`, `KEY_RIGHTSHIFT`, or `KEY_F20`.
On machines with more than one keyboard, use `--device` to point at the one you
actually hold (see the troubleshooting table).

### Dictating

Words are typed into the focused window as you speak, then cleaned up on
release. You can dictate punctuation by saying its name: "question mark",
"comma", "period", "exclamation point", "colon", "semicolon", "new line",
"new paragraph", "open paren", "close paren", "hyphen", "underscore", "at
sign", "hashtag", and a few more. Say "new paragraph" to finish a paragraph.

The first time you run it, the whisper model downloads automatically and is cached.

### Languages

Whisper detects the spoken language automatically, so there is nothing to
configure. The default model (`base.en`) is English-only. To dictate in other
languages, switch to a multilingual model, which transcribes any of the ~99
languages Whisper supports:

```bash
pandatalk --model base     # multilingual, fast
pandatalk --model small    # multilingual, more accurate
```

## Update

Panda Talk checks GitHub for new releases each time you log in (the systemd
service runs an update check before starting) and installs them automatically.
There is nothing to run. To check right now:

```bash
systemctl --user restart pandatalk
```

Re-run the one-command installer from the [Install](#install) section if you
ever want a clean reinstall.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `cannot read input devices` | You are not in the `input` group. Run `sudo usermod -aG input $USER`, log out and back in. |
| `PortAudio library not found` | `sudo dnf install portaudio`, then re-run the installer. |
| Text does not appear when you type | pandatalk starts ydotoold on demand. If typing fails, check you are in the `input` group (`id -nG`) and that `/dev/uinput` is group-writable; log out and back in after joining the group. Do NOT run ydotoold as a persistent service - it can lock up your keyboard on Wayland. |
| `ydotool: permission denied` on the socket | The daemon must run as your user, not root. pandatalk launches it for you; if it cannot open `/dev/uinput`, fix uinput permissions (above), not a system-wide service. |
| Nothing types, or text goes to the wrong window | More than one keyboard detected. Pass `--device /dev/input/eventN` to pick the one you hold. |

## Limitations

- Dictation is typed as ASCII. Emoji and most non-Latin scripts are not
  converted to keystrokes (a limitation of ydotool's synthetic keyboard).
- The push-to-talk key still reaches the focused window while held, so avoid
  keys that trigger shortcuts in the app you are typing into.

## Privacy

The microphone is opened only while the push-to-talk key is held, and never for
more than 60 seconds at a time even if the release is missed. Audio is
transcribed in memory and discarded immediately; the transcript itself is never
written to disk. A debug log of lengths and timestamps (no speech content) is
kept at `~/.local/state/pandatalk/pandatalk.log`, private to your user.

## License

MIT License, see [`LICENSE`](LICENSE).

Privacy: see [`PRIVACY.md`](PRIVACY.md).
