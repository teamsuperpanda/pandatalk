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

__version__ = "1.1"

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
STREAM_TICK = 0.8   # how often incremental transcription runs while held

pressed = threading.Event()   # set while an accepted PTT key press is held
held = threading.Event()      # set only for presses that started a capture
busy = threading.Lock()       # one transcription session at a time

# Streaming state for the current session, guarded by _state.
_state = threading.Lock()
_session_id = 0               # bumped on each press; stale loops bail out
_frames = []                  # every int16 frame captured this session
_new_frames = []              # frames not yet transcribed
_typed = []                   # tokens already sent to the keyboard
_capture_done = threading.Event()   # mic has stopped feeding audio
_capture_cond = threading.Condition(_state)


def assemble(frames):
    if not frames:
        return np.array([], dtype=np.int16)
    return np.concatenate(frames).astype(np.float32) / 32768.0


# Spoken-word -> punctuation. Whisper's .en models emit no punctuation, so we
# recognise the spoken words and turn them into symbols.
_WORD_TO_SYM = {
    "question mark": "?", "question": "?", "qm": "?",
    "comma": ",", "period": ".", "dot": ".", "full stop": ".",
    "exclamation point": "!", "exclamation mark": "!", "exclamation": "!",
    "colon": ":", "semicolon": ";",
    "open parenthesis": "(", "open paren": "(", "left paren": "(",
    "close parenthesis": ")", "close paren": ")", "right paren": ")",
    "open bracket": "[", "close bracket": "]",
    "new line": "\n", "new paragraph": "\n\n", "newline": "\n",
    "hyphen": "-", "dash": "-",
    "at sign": "@", "hashtag": "#", "hash tag": "#", "pound sign": "#",
    "dollar sign": "$", "percent": "%", "percent sign": "%",
    "ampersand": "&", "and sign": "&",
    "asterisk": "*", "star": "*",
    "slash": "/", "backslash": "\\", "back slash": "\\",
    "underscore": "_", "equals": "=", "equal sign": "=",
    "apostrophe": "'", "quote": '"', "open quote": '"', "close quote": '"',
}
_PHRASES = sorted(_WORD_TO_SYM, key=len, reverse=True)


def _replace_spoken_punct(words):
    """Turn phrases like 'question mark' into single written tokens."""
    out = []
    i = 0
    n = len(words)
    while i < n:
        matched = False
        for phrase in _PHRASES:
            plen = len(phrase.split())
            if i + plen <= n and " ".join(words[i:i + plen]) == phrase:
                out.append(_WORD_TO_SYM[phrase])
                i += plen
                matched = True
                break
        if not matched:
            out.append(words[i])
            i += 1
    return out


def _render(tokens, start=False, prev=None):
    """Join tokens into typing text. Punctuation glues correctly: no space
    before , . ! ? ; : ) ] \\ / and no space after ( [ ". The first word of
    a sentence is capitalised (start of text, after . ! ? or a newline).
    `prev` is the last token already typed, for cross-chunk context."""
    if not tokens:
        return ""
    left_glue = {',', '.', '!', '?', ';', ':', ')', ']', '\\', '/'}
    right_glue = {'(', '['}
    out = ""
    cap_next = prev is None or prev in {'.', '!', '?'} or prev == '\n'
    glue_right = False
    for i, tok in enumerate(tokens):
        if tok == '\n':
            out = out.rstrip() + '\n'
            cap_next = True
            glue_right = False
            continue
        if cap_next and tok[:1].isalpha():
            tok = tok[:1].upper() + tok[1:]
        if tok not in left_glue and not glue_right \
                and (not start or i > 0 or out):
            if not out.endswith((' ', '\n')):
                out += ' '
        out += tok
        cap_next = tok in {'.', '!', '?'}
        glue_right = tok in right_glue
    return out


def postprocess(words):
    """Turn a list of raw words into separate tokens (words + punctuation)."""
    return _replace_spoken_punct(words)


def _prefix_match(new_tokens, typed_tokens):
    """Longest prefix of typed_tokens that new_tokens still agrees with."""
    i = 0
    while i < len(typed_tokens) and i < len(new_tokens) \
            and new_tokens[i] == typed_tokens[i]:
        i += 1
    return i


def type_text(text):
    if not text:
        return
    debug(f"typing {len(text)} chars")
    result = subprocess.run(["ydotool", "type", "--key-delay", "10",
                             "--escape", "0", text],
                            capture_output=True, text=True)
    debug(f"ydotool exit {result.returncode}: {result.stderr.strip()}")
    if result.returncode != 0:
        print(f"[pandatalk] typing failed: {result.stderr.strip()}",
              file=sys.stderr, flush=True)


def _transcribe(model, audio):
    """Transcribe a float32 array, returning a token list (words and
    punctuation as separate tokens)."""
    if len(audio) == 0:
        return []
    segments, _ = model.transcribe(
        audio, beam_size=1, vad_filter=True,
        condition_on_previous_text=True)
    words = []
    for seg in segments:
        words.extend(seg.text.split())
    return postprocess(words)


def _commit(tokens, force=False):
    """Type the part of `tokens` that extends what is already on screen.
    If the model revised earlier words, skip (do not type over what is
    already on screen) unless `force`, which the final authoritative pass
    uses so no words are lost."""
    with _state:
        old = list(_typed)
    common = _prefix_match(tokens, old)
    if common < len(old) and not force:
        return                              # revision: leave screen as is
    to_type = tokens[common:]
    if to_type:
        type_text(_render(to_type, start=not old,
                          prev=old[-1] if old else None))
    with _state:
        _typed[:] = tokens


def stream_loop(model, session_id):
    """The only thread that transcribes. Types stable words while holding,
    delayed by one pass so revisions never double-type, then a final pass on
    release catches the tail. Releases `busy` exactly once when finished."""
    staged = None
    try:
        while True:
            with _state:
                if session_id != _session_id:
                    break                      # stale session, bail out
                if _new_frames:
                    audio = assemble(_frames)  # full & consistent view
                    _new_frames.clear()
                    final = False
                elif _capture_done.is_set():
                    audio = assemble(_frames)
                    final = True
                else:
                    _capture_cond.wait(STREAM_TICK)
                    continue
            if len(audio) == 0:
                if final:
                    break                  # nothing was captured
                continue
            tokens = _transcribe(model, audio)
            if final:
                # Authoritative: force-commit the full last transcription so
                # no tail words are lost even if the model revised earlier ones.
                _commit(tokens, force=True)
                break
            if staged is not None:
                _commit(staged)
            staged = tokens
    except Exception as e:
        debug(f"stream_loop error: {type(e).__name__}: {e}")
    finally:
        busy.release()
        debug("session done")


def capture(model):
    """Mic thread: read audio while the key is held and feed the streamer."""
    start = time.monotonic()
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                            dtype="int16") as stream:
            while pressed.is_set() and (time.monotonic() - start) < MAX_HOLD_S:
                data, _ = stream.read(1600)
                chunk = data[:, 0].copy()
                with _state:
                    _frames.append(chunk)
                    _new_frames.append(chunk)
                    _capture_cond.notify_all()
    except Exception as e:
        debug(f"capture error: {type(e).__name__}: {e}")
    debug(f"captured {time.monotonic() - start:.2f}s")
    with _state:
        _capture_done.set()
        _capture_cond.notify_all()


def _deferred_start(model, sid):
    """Wait out the tap-debounce, then start capture. `busy` is acquired here
    (not in on_press) so a re-press during the debounce is not dropped."""
    time.sleep(MIN_HOLD_S)
    if not busy.acquire(blocking=False):
        debug("press ignored, busy")
        with _state:
            if sid == _session_id:
                held.clear()
                pressed.clear()
        return
    with _state:
        if sid != _session_id or not held.is_set():
            busy.release()          # a tap: the mic never opened
            debug("tap: mic never opened")
            return
        _frames.clear()
        _new_frames.clear()
        _typed.clear()
        _capture_done.clear()
    debug("press: starting capture")
    threading.Thread(target=capture, args=(model,), daemon=True).start()
    threading.Thread(target=stream_loop, args=(model, sid), daemon=True).start()


def on_press(model):
    global _session_id
    with _state:
        _session_id += 1
        sid = _session_id
    held.set()
    pressed.set()
    threading.Thread(target=_deferred_start, args=(model, sid), daemon=True).start()


def on_release():
    if held.is_set():
        held.clear()
        pressed.clear()
        with _capture_cond:
            _capture_cond.notify_all()


def selftest():
    chunk = np.full(1600, 1000, dtype=np.int16)
    audio = assemble([chunk, chunk])
    assert len(audio) == 3200, f"got {len(audio)}"
    assert audio.min() == 1000 / 32768.0 and audio.max() == 1000 / 32768.0
    assert len(assemble([])) == 0
    assert keycode_for("KEY_A") is not None
    assert keycode_for("NOT_A_KEY") is None
    assert postprocess(["hello", "world", "question", "mark"]) == \
        ["hello", "world", "?"]
    assert postprocess(["is", "it", "comma", "or", "period"]) == \
        ["is", "it", ",", "or", "."]
    assert _render(["hello", "world", ",", "ok"], True) == "Hello world, ok"
    assert _render(["hello", ".", "how", "are", "you"], True) == \
        "Hello. How are you"
    assert _render(["new", "line"], start=False, prev=".") == " New line"
    assert _render(["(", "hi", ")"], True) == "(hi)"
    assert _render(["this", "is"], start=False, prev="word") == " this is"
    assert _render([","], start=False, prev="test") == ","
    assert _prefix_match(["a", "b", "c"], ["a", "b"]) == 2
    assert _prefix_match(["x", "b"], ["a", "b"]) == 0
    print("selftest OK")
    return 0


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
