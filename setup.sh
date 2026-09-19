#!/bin/sh
# Find a Python new enough to run the setup check, and run it.
#
# Linux and macOS. Everything this project needs is checked by
# mild-setup.py, which is Python -- so the only job here is the one job
# that cannot be done in Python: getting there on a machine that has none,
# or that has one too old to be worth running.
#
# POSIX sh on purpose. A stock macOS has bash 3.2 and nothing newer, and
# this runs before anything is installed, so it asks for as little as it
# can: no arrays, no [[, no substitutions bash added later.
#
# Anything passed here is passed straight on:
#     ./setup.sh --check
#     ./setup.sh --venv --heavy
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NEED_MAJOR=3
NEED_MINOR=10

# Each candidate is asked its own version rather than being trusted by name:
# `python3` is 3.9 on machines still in service, and `python` is whatever
# was linked to it decades ago.
new_enough() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= ('"$NEED_MAJOR"', '"$NEED_MINOR"') else 1)' 2>/dev/null
}

PY=""
for try in python3 python3.13 python3.12 python3.11 python3.10 python; do
    if command -v "$try" >/dev/null 2>&1 && new_enough "$try"; then
        PY=$(command -v "$try")
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[ !!!! ] Python  no $NEED_MAJOR.$NEED_MINOR or newer on PATH"
    echo
    if [ "$(uname -s)" = "Darwin" ]; then
        echo "         macOS ships one, and the one it ships is old and is"
        echo "         Apple's own. Get a current one either way:"
        echo "             brew install python"
        echo "         or the installer from https://www.python.org/downloads/"
    else
        for mgr in apt dnf pacman zypper apk; do
            command -v "$mgr" >/dev/null 2>&1 || continue
            case "$mgr" in
                apt)    echo "             sudo apt install python3 python3-pip python3-venv" ;;
                dnf)    echo "             sudo dnf install python3 python3-pip" ;;
                pacman) echo "             sudo pacman -S --needed python python-pip" ;;
                zypper) echo "             sudo zypper install python3 python3-pip" ;;
                apk)    echo "             sudo apk add python3 py3-pip" ;;
            esac
            break
        done
        echo
        echo "         (a version is printed by: python3 --version)"
    fi
    exit 1
fi

exec "$PY" "$HERE/mild-setup.py" "$@"
