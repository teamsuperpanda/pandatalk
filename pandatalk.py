#!/usr/bin/env python3
"""pandatalk - hold a key, talk, and the words get typed into the focused window.

Wayland (GNOME) and X11 both work: keys are read from raw evdev devices and
text is injected with ydotool, so there is no X11 dependency.

Privacy: the microphone is ONLY open while the PTT key is held. Nothing is
recorded or stored while idle, and nothing is kept after typing.

Fedora install:
  curl -fsSL https://raw.githubusercontent.com/teamsuperpanda/pandatalk/main/install.sh | bash

Usage:
  pandatalk                              # hold LEFT CTRL and talk
  pandatalk --set-key KEY_CAPSLOCK       # make CAPSLOCK your key (persistent)
  pandatalk --key KEY_CAPSLOCK           # override the key for this run only
  pandatalk --model tiny.en              # smaller/faster model
  pandatalk --selftest
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import threading
import time

import evdev
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

__version__ = "1.0.0"

LOG_PATH = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "pandatalk", "pandatalk.log")
CONFIG_PATH = os.path.join(os.path.expanduser("~/.config/pandatalk"), "config.json")
DEFAULT_KEY = "KEY_LEFTCTRL"


def keycode_for(name):
    return getattr(evdev.ecodes, name, None)


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def debug(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), mode=0o700, exist_ok=True)
        fd = os.open(LOG_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass

SAMPLE_RATE = 16000
MIN_HOLD_S = 0.2    # shorter holds are treated as accidental taps
MAX_HOLD_S = 60.0   # hard cap on mic-open time per press (privacy safety net)

pressed = threading.Event()   # set while an accepted PTT key press is held
held = threading.Event()      # set only for presses that started a capture
busy = threading.Lock()       # one transcription at a time


def assemble(frames):
    if not frames:
        return np.array([], dtype=np.int16)
    return np.concatenate(frames).astype(np.float32) / 32768.0


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--key", default=None,
                   help="evdev key name to hold (overrides config; default KEY_LEFTCTRL)")
    p.add_argument("--set-key", metavar="KEY", default=None,
                   help="save a push-to-talk key to your config and exit, "
                        "e.g. --set-key KEY_CAPSLOCK")
    p.add_argument("--model", default="base.en",
                   help="whisper model size (default base.en)")
    p.add_argument("--device", default=None,
                   help="evdev device path, e.g. /dev/input/event4")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--version", action="version", version=f"pandatalk {__version__}")
    return p.parse_args()


def pick_keyboard(device):
    paths = [device] if device else sorted(glob.glob("/dev/input/event*"))
    denied = False
    for path in paths:
        try:
            dev = evdev.InputDevice(path)
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        if "ydotoold" in dev.name:
            continue  # virtual device ydotool types through; never listen to our own output
        if evdev.ecodes.KEY_A in dev.capabilities().get(evdev.ecodes.EV_KEY, []):
            return dev
    if denied:
        print("[pandatalk] cannot read input devices. Run:",
              "  sudo usermod -aG input $USER   # then log out and back in",
              sep="\n", file=sys.stderr)
    sys.exit("no keyboard device found")


def type_text(text):
    debug(f"typing {len(text)} chars")
    result = subprocess.run(["ydotool", "type", "--key-delay", "10",
                             "--escape", "0", text],
                            capture_output=True, text=True)
    debug(f"ydotool exit {result.returncode}: {result.stderr.strip()}")
    if result.returncode != 0:
        print(f"[pandatalk] typing failed: {result.stderr.strip()}",
              file=sys.stderr, flush=True)


def capture(model):
    try:
        debug("capture thread started")
        start = time.monotonic()
        frames = []
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
            while pressed.is_set() and (time.monotonic() - start) < MAX_HOLD_S:
                data, _ = stream.read(1600)
                frames.append(data[:, 0].copy())
        duration = time.monotonic() - start
        samples = sum(len(f) for f in frames)
        debug(f"captured {samples} samples ({duration:.2f}s)")
        if duration < MIN_HOLD_S or not frames:
            debug("too short, treating as tap")
            return  # accidental tap or nothing recorded
        audio = assemble(frames)
        segments, _ = model.transcribe(audio)
        text = " ".join(seg.text for seg in segments).strip()
        debug(f"transcribed {len(text)} chars")
        if text:
            print(f"[pandatalk] {text}", flush=True)
            type_text(text)
    except Exception as e:
        debug(f"ERROR in capture: {type(e).__name__}: {e}")
        print(f"[pandatalk] capture failed: {e}", file=sys.stderr, flush=True)
    finally:
        busy.release()


def on_press(model):
    if not busy.acquire(blocking=False):
        debug("press ignored, busy")
        return  # still transcribing the previous utterance
    debug("press: starting capture")
    held.set()
    pressed.set()
    threading.Thread(target=capture, args=(model,), daemon=True).start()


def on_release():
    if held.is_set():
        held.clear()
        pressed.clear()
        debug("release: capture will stop")


def selftest():
    chunk = np.full(1600, 1000, dtype=np.int16)
    audio = assemble([chunk, chunk])
    assert len(audio) == 3200, f"got {len(audio)}"
    assert audio.min() == 1000 / 32768.0 and audio.max() == 1000 / 32768.0
    assert len(assemble([])) == 0
    assert keycode_for("KEY_A") is not None
    assert keycode_for("NOT_A_KEY") is None
    print("selftest OK")
    return 0


def main():
    args = parse_args()
    if args.selftest:
        return selftest()

    if args.set_key:
        if keycode_for(args.set_key) is None:
            sys.exit(f"unknown key {args.set_key}")
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), mode=0o700, exist_ok=True)
            fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"key": args.set_key}, f, indent=2)
        except OSError as e:
            sys.exit(f"could not save key to {CONFIG_PATH}: {e}")
        print(f"[pandatalk] push-to-talk key saved: {args.set_key}", flush=True)
        return 0

    key_name = args.key or load_config().get("key") or DEFAULT_KEY
    keycode = keycode_for(key_name)
    if keycode is None:
        sys.exit(f"unknown key {key_name}")

    keyboard = pick_keyboard(args.device)
    try:
        model = WhisperModel(args.model, device="cpu", compute_type="int8")
    except Exception as e:
        sys.exit(f"failed to load whisper model '{args.model}': {e}")

    print(f"[pandatalk] listening on {keyboard.path}. "
          f"Mic is open only while you hold {key_name}. Ctrl+C to quit.",
          flush=True)

    try:
        for event in keyboard.read_loop():
            if (event.type == evdev.ecodes.EV_KEY
                    and event.code == keycode and event.value in (0, 1)):
                if event.value == 1:
                    on_press(model)
                else:
                    on_release()
    except OSError as e:
        sys.exit(f"input device lost: {e}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[pandatalk] stopped", flush=True)