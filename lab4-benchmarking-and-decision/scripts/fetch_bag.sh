#!/usr/bin/env bash
# fetch_bag.sh - download the pre-published workshop benchmark bag (no generation
# wait during the workshop). Use `scripts/workshop gen-bag` instead if you'd rather make
# your own, or just drop a bag of your own into docker/bags/.
#
# The bag is never committed to git (repo .gitignore excludes *.mcap/*.bag - see
# "Publishing a new benchmark bag" in docker/RUNNING.md for how it gets published).
# It ships as a GitHub Release ASSET instead: one tarball of a docker/bags/<name>/
# directory (metadata.yaml + *.mcap), attached to a dedicated data release so it can
# be updated independently of the software version tags (v0.1.0, v0.2.0, ...).
#
# Usage: bash fetch_bag.sh [name] [release-tag]
# Env:   WORKSHOP_BAG_REPO   override the source repo (owner/name)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # lab4/scripts
DOCKER_ROOT="$(cd "$SCRIPT_DIR/../../docker" && pwd)"       # docker/
SCRIPTS_DIR="$DOCKER_ROOT/scripts"                            # docker/scripts
# shellcheck source=../lib.sh
. "$SCRIPTS_DIR/lib.sh"

REPO="${WORKSHOP_BAG_REPO:-clearpathrobotics/roscon2026-workshop-mastering-the-jazzy-rmw}"
NAME="${1:-benchmark}"
TAG="${2:-workshop-bags}"
ASSET="${NAME}.tar.gz"
BAGS_DIR="$DOCKER_ROOT/bags"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$BAGS_DIR"

if command -v gh >/dev/null 2>&1; then
    info "fetching '$ASSET' via gh release download ($TAG, repo $REPO)"
    gh release download "$TAG" --repo "$REPO" --pattern "$ASSET" --dir "$TMP" --clobber \
        || die "gh release download failed - is tag '$TAG' published with asset '$ASSET'? See docker/RUNNING.md, 'Publishing a new benchmark bag'."
else
    URL="https://github.com/$REPO/releases/download/$TAG/$ASSET"
    info "gh CLI not found, falling back to curl: $URL"
    curl -fsSL "$URL" -o "$TMP/$ASSET" \
        || die "curl failed - is tag '$TAG' published with asset '$ASSET'? See docker/RUNNING.md, 'Publishing a new benchmark bag'."
fi

info "extracting into docker/bags/$NAME/"
rm -rf "${BAGS_DIR:?}/${NAME:?}"
tar -xzf "$TMP/$ASSET" -C "$BAGS_DIR"

if [[ -f "$BAGS_DIR/$NAME/metadata.yaml" ]]; then
    ok "fetched docker/bags/$NAME/ - ready to replay (no generation wait)"
    printf "  scripts/workshop run --template B --bag /bags/%s --rmw cyclone,fastdds,zenoh --scale 3 --duration 30\n" "$NAME"
else
    die "extracted archive but docker/bags/$NAME/metadata.yaml is missing - was '$ASSET' packed correctly?"
fi
