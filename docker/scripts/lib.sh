#!/usr/bin/env bash
# lib.sh - shared, TTY-safe logging helpers for the workshop scripts.
# Source it:  . "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# Messages go to stderr so they never mix with a script's real stdout.

# cspell:disable-next-line
if [ -t 2 ] && [ -z "${NO_COLOR:-}" ]; then
    _LB_RED=$'\033[31m'; _LB_GRN=$'\033[32m'; _LB_YEL=$'\033[33m'; _LB_NC=$'\033[0m'
else
    _LB_RED=''; _LB_GRN=''; _LB_YEL=''; _LB_NC=''
fi

info() { printf '%s[*]%s %s\n' "$_LB_YEL" "$_LB_NC" "$*" >&2; }
ok()   { printf '%s[+]%s %s\n' "$_LB_GRN" "$_LB_NC" "$*" >&2; }
warn() { printf '%s[!]%s %s\n' "$_LB_YEL" "$_LB_NC" "$*" >&2; }
fail() { printf '%s[x]%s %s\n' "$_LB_RED" "$_LB_NC" "$*" >&2; }
die()  { fail "$@"; exit 1; }
