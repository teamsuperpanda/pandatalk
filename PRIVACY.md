# Panda Talk Privacy Policy

Panda Talk is local, push-to-talk dictation. This document describes what it
reads, stores, and sends.

## What it processes

- **Audio**: the microphone is opened only while the push-to-talk key is held,
  and never for more than 60 seconds at a time. The captured audio is
  transcribed on-device and discarded immediately afterwards.
- **The transcript**: the recognized text is typed into the focused window. It
  is not written to disk.

## What it stores on disk

- `~/.config/pandatalk/config.json`: your chosen push-to-talk key name only.
- `~/.local/state/pandatalk/pandatalk.log`: a debug log of timestamps and audio
  lengths. It never contains speech content, and is readable only by your user.

## Network access

- Pandatalk sends no audio, transcripts, or usage data anywhere.
- The only network request is a one-time download of the whisper speech model
  from Hugging Face on first run, cached locally afterwards.

## Third parties and telemetry

- No telemetry, analytics, or crash reporting. Nothing is sent to third parties.

## Contact

If you have privacy concerns or want to report an issue, open a GitHub issue at
https://github.com/teamsuperpanda/pandatalk.
