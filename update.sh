#!/usr/bin/env bash
# Auto-update: when a new release tag appears on the origin remote, pull it.
# Runs as ExecStartPre of the pandatalk user service, so it checks on login.
# Best-effort: any failure just exits and pandatalk starts normally.
APP_DIR="${PANDATALK_DIR:-$HOME/.local/share/pandatalk}"

[ -d "$APP_DIR/.git" ] || exit 0

# Newest tag upstream (git version sort handles v1.9 < v1.10). Quiet when offline.
REMOTE_TAG="$(git -C "$APP_DIR" ls-remote --tags --refs --sort=-v:refname origin 2>/dev/null \
    | head -1 | cut -f2 | sed 's|refs/tags/||')"
[ -n "$REMOTE_TAG" ] || exit 0

LOCAL_TAG="$(git -C "$APP_DIR" describe --tags --abbrev=0 2>/dev/null)"
[ -n "$LOCAL_TAG" ] || exit 0
[ "$LOCAL_TAG" = "$REMOTE_TAG" ] && exit 0

echo "==> pandatalk update available ($LOCAL_TAG -> $REMOTE_TAG)"
git -C "$APP_DIR" fetch --depth 1 origin tag "$REMOTE_TAG" || exit 0
git -C "$APP_DIR" reset --hard "$REMOTE_TAG" || exit 0
[ -x "$APP_DIR/.venv/bin/pip" ] \
    && "$APP_DIR/.venv/bin/pip" install --quiet --upgrade \
        -r "$APP_DIR/requirements.txt" 2>/dev/null || true
echo "==> pandatalk updated to $REMOTE_TAG"