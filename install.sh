#!/bin/sh
# Mild Lyrics installer for Linux and macOS:
#     curl -fsSL https://github.com/gcoolL/mild-lyrics/releases/latest/download/install.sh | sh
# Installs the latest release into ~/.local/share/mild-lyrics (macOS:
# ~/Library/Application Support/Mild Lyrics) with its own Python environment
# and menu entries. Run it again to repair; add `-s -- --uninstall` to remove.
# Opened from a file manager it shows dialogs (zenity), or reopens itself in
# a terminal window. Why it works this way: docs/notes/install.md
set -eu

REPO=gcoolL/mild-lyrics
PY_PKG=https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg
TITLE="Mild Lyrics installer"
MAC=; [ "$(uname -s)" = Darwin ] && MAC=1
GUI=
NL='
'

say() { printf '%s\n' "$*"; }
warn() { printf '[ !!!! ] %s\n' "$*"; }

# Under `curl | sh` stdin is this script, so answers come from the terminal
# and nothing started here may read stdin.
if (: </dev/tty) 2>/dev/null; then TTY=/dev/tty; else TTY=/dev/null; fi

esc() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }
short() { case "$1" in "$HOME"/*) printf '~/%s' "${1#"$HOME"/}" ;; *) printf '%s' "$1" ;; esac; }
z() { zenity --title="$TITLE" --width=480 "$@" 2>/dev/null; }

ask() {  # ask QUESTION y|n
    if [ -n "$GUI" ]; then z --question --text="$(esc "$1")"; return; fi
    if [ "$TTY" = /dev/null ]; then [ "$2" = y ]; return; fi
    if [ "$2" = y ]; then hint=Y/n; else hint=y/N; fi
    printf '%s [%s] ' "$1" "$hint" >/dev/tty
    read -r got </dev/tty || got=
    case "$got" in
        "") [ "$2" = y ] ;;
        [Yy]*) return 0 ;;
        *) return 1 ;;
    esac
}

tell() {  # tell MESSAGE: a line in the terminal, a dialog in the GUI
    if [ -n "$GUI" ]; then z --info --text="$(esc "$1")"; else say "$1"; fi
}

fail() {  # fail MESSAGE: says why and stops
    if [ -n "$GUI" ]; then z --error --text="$(esc "$1")"; else warn "$1"; fi
    exit 1
}

as_root() {  # a password prompt that works with or without a terminal
    if [ -n "$GUI" ]; then pkexec "$@"; else sudo "$@" <"$TTY"; fi
}

run_step() {  # run_step LABEL CMD...: in the GUI, a progress window over the log while CMD runs
    label=$1; shift
    if [ -z "$GUI" ]; then "$@"; return; fi
    ( "$@" ) </dev/null &
    pid=$!
    progress "$pid" | z --progress --pulsate --auto-close --no-cancel --text="$(esc "$label")"
    wait "$pid"
}

progress() {  # progress PID: the log's latest line as zenity's label, while PID runs
    while kill -0 "$1" 2>/dev/null; do
        line=$(tail -c 3000 "$LOG" | tr '\r' '\n' | sed '/^[[:space:]]*$/d' | tail -n 1 |
               sed 's/^\(.\{90\}\).*/\1.../')
        printf '# %s\n' "$(esc "$line")"
        sleep 0.4
    done
    echo 100
}

in_terminal() {  # reopen this script in a terminal window; fails when there is none
    [ -f "$0" ] && grep -q "Mild Lyrics installer" "$0" 2>/dev/null || return 1
    self="$(cd "$(dirname "$0")" && pwd -P)/$(basename "$0")"
    if [ -n "$MAC" ]; then
        osascript -e "tell application \"Terminal\" to do script \"MILD_HOLD=1 sh '$self'\"" \
                  -e 'tell application "Terminal" to activate' >/dev/null 2>&1
        return
    fi
    case "${XDG_CURRENT_DESKTOP:-}" in
        *KDE*) first=konsole ;;
        *GNOME*) first="kgx ptyxis gnome-terminal" ;;
        *XFCE*) first=xfce4-terminal ;;
        *MATE*) first=mate-terminal ;;
        *) first= ;;
    esac
    export MILD_HOLD=1
    for t in xdg-terminal-exec $first konsole kgx ptyxis gnome-terminal xfce4-terminal \
             mate-terminal kitty alacritty foot wezterm x-terminal-emulator xterm; do
        command -v "$t" >/dev/null 2>&1 || continue
        case "$t" in
            xdg-terminal-exec|kitty|foot) set -- "$t" sh "$self" ;;
            kgx|ptyxis|gnome-terminal) set -- "$t" -- sh "$self" ;;
            xfce4-terminal|mate-terminal) set -- "$t" -x sh "$self" ;;
            wezterm) set -- wezterm start -- sh "$self" ;;
            *) set -- "$t" -e sh "$self" ;;
        esac
        "$@" </dev/null >/dev/null 2>&1 &
        return 0
    done
    return 1
}

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
if [ -n "$MAC" ]; then DEFAULT_DIR="$HOME/Library/Application Support/Mild Lyrics"
else DEFAULT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/mild-lyrics"; fi
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/mild-lyrics-install.log"

ours() { [ -f "$1/mild-lyrics/lyrics_gui.py" ]; }

installed_dir() {  # where a menu entry says an install is, else the default folder; never a git checkout
    for stem in mild-lyrics ttml-editor; do
        if [ -n "$MAC" ]; then
            case $stem in mild-lyrics) name="Mild Lyrics" ;; *) name="TTML Editor" ;; esac
            got=$(sed -n 's/^cd "\(.*\)" || exit 1$/\1/p' \
                  "$HOME/Applications/$name.app/Contents/MacOS/$stem" 2>/dev/null || true)
        else
            got=$(sed -n 's/^Path=//p' "$APPS/$stem.desktop" 2>/dev/null || true)
        fi
        if [ -n "$got" ] && ours "$got" && [ ! -e "$got/.git" ]; then say "$got"; return 0; fi
    done
    # Installed with no menu entries picked: only the default folder can be found.
    if ours "$DEFAULT_DIR" && [ ! -e "$DEFAULT_DIR/.git" ]; then say "$DEFAULT_DIR"; return 0; fi
    return 1
}

install_dir() {  # the install to remove: the one named, the one installed, or the default
    if [ -n "${MILD_DIR:-}" ]; then say "$MILD_DIR"; return; fi
    installed_dir || say "$DEFAULT_DIR"
}

resolve_target() {  # resolve_target PATH -> a writable install folder, or fails saying why on stderr
    t=$1
    case "$t" in "~") t=$HOME ;; "~/"*) t="$HOME/${t#\~/}" ;; /*) ;; *) t="$PWD/$t" ;; esac
    t=${t%/}
    # Uninstalling deletes the whole folder, so a folder that already holds
    # other things gets a mild-lyrics folder of its own inside it.
    if [ -d "$t" ] && ! ours "$t" && [ -n "$(ls -A "$t" 2>/dev/null)" ]; then
        t="$t/mild-lyrics"
        if [ -d "$t" ] && ! ours "$t" && [ -n "$(ls -A "$t" 2>/dev/null)" ]; then
            say "$t already has other files in it; pick another folder." >&2
            return 1
        fi
    fi
    if ! mkdir -p "$t" 2>/dev/null || ! touch "$t/.mild-write-test" 2>/dev/null; then
        say "Cannot write to $t; pick a folder you own." >&2
        return 1
    fi
    rm -f "$t/.mild-write-test"
    (cd "$t" && pwd -P)
}

read_install_dir() {  # where a first install goes: the default, or a typed or chosen folder
    while :; do
        if [ -n "$GUI" ]; then
            rc=0
            got=$(z --question --ok-label=Install --cancel-label=Cancel \
                    --extra-button="Choose folder..." \
                    --text="Mild Lyrics will be installed in$NL$NL$(esc "$(short "$DEFAULT_DIR")")") || rc=$?
            if [ "$rc" = 0 ]; then got=$DEFAULT_DIR
            elif [ "$got" = "Choose folder..." ]; then
                got=$(z --file-selection --directory --filename="$HOME/" \
                        --title="Where to install Mild Lyrics") || continue
            else
                return 1
            fi
        elif [ "$TTY" = /dev/null ]; then got=
        else
            say "Mild Lyrics will be installed in $DEFAULT_DIR" >/dev/tty
            printf 'Press Enter for that, or type another folder: ' >/dev/tty
            read -r got </dev/tty || got=
        fi
        if out=$(resolve_target "${got:-$DEFAULT_DIR}" 2>"$tmp/why"); then say "$out"; return 0; fi
        if [ -n "$GUI" ]; then z --error --text="$(esc "$(cat "$tmp/why")")"
        else warn "$(cat "$tmp/why")" >&2; fi
        [ "$TTY" = /dev/null ] && [ -z "$GUI" ] && return 1
    done
}

py_version() {  # prints "3.12" for a 3.10+ interpreter, fails otherwise
    "$1" -c 'import sys; v = sys.version_info; assert v >= (3, 10); print("%d.%d" % v[:2])' 2>/dev/null
}

find_python() {
    # The plain python3 when its version every dependency has wheels for,
    # since a distribution's own PyQt6 is then shared through the venv.
    if command -v python3 >/dev/null 2>&1; then
        case "$(py_version python3 || true)" in
            3.10|3.11|3.12|3.13|3.14) command -v python3; return ;;
        esac
    fi
    for try in python3.12 python3.13 python3.11 python3.14 python3.10 \
               /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
               /opt/homebrew/bin/python3 /usr/local/bin/python3 python3 python; do
        if command -v "$try" >/dev/null 2>&1 && py_version "$try" >/dev/null; then
            command -v "$try"; return
        fi
    done
    return 1
}

get_python() {
    if [ -n "$MAC" ]; then
        if command -v brew >/dev/null 2>&1; then
            ask "Install Python 3.12 with Homebrew?" y || return 1
            brew install python@3.12 </dev/null
        else
            ask "Install Python 3.12 from python.org (asks for your password)?" y || return 1
            pkg=$(mktemp -d)/python.pkg
            curl -fsSL -o "$pkg" "$PY_PKG"
            sudo installer -pkg "$pkg" -target / <"$TTY"
            rm -f "$pkg"
            # python.org's own fix for its missing certificate store.
            certs="/Applications/Python 3.12/Install Certificates.command"
            [ -x "$certs" ] && "$certs" </dev/null >/dev/null 2>&1 || true
        fi
        return 0
    fi
    for mgr in apt dnf pacman zypper apk; do
        command -v "$mgr" >/dev/null 2>&1 || continue
        case "$mgr" in
            apt)    cmd="apt install -y python3 python3-pip python3-venv" ;;
            dnf)    cmd="dnf install -y python3 python3-pip" ;;
            pacman) cmd="pacman -S --needed --noconfirm python python-pip" ;;
            zypper) cmd="zypper install -y python3 python3-pip" ;;
            apk)    cmd="apk add python3 py3-pip" ;;
        esac
        ask "Mild Lyrics needs Python 3.10 or newer, and none was found. Install it now?$NL$NL    $cmd$NL${NL}This asks for your password." y || return 1
        run_step "Installing Python..." as_root $cmd || fail "Python could not be installed. Details: $LOG"
        return 0
    done
    fail "Mild Lyrics needs Python 3.10 or newer, and this system has no package manager this installer knows. Install Python, then run this again."
}

fetch() {  # fetch URL FILE
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -H "User-Agent: mild-lyrics-installer" -o "$2" "$1"
    else
        wget -q -U mild-lyrics-installer -O "$2" "$1"
    fi
}

# Unpacks a GitHub zipball (one "<owner>-<repo>-<sha>/" folder) over DIR.
UNPACK='
import pathlib, shutil, sys, zipfile
blob, dest = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(blob) as z:
    names = [n for n in z.namelist() if not n.endswith("/")]
    top = names[0].split("/", 1)[0] + "/" if names else ""
    if top + "mild-lyrics/lyrics_gui.py" not in names:
        sys.exit("the download is not a Mild Lyrics release")
    for n in names:
        rel = pathlib.PurePosixPath(n[len(top):])
        if not rel.parts or rel.is_absolute() or ".." in rel.parts:
            continue
        out = dest.joinpath(*rel.parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        with z.open(n) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if (z.getinfo(n).external_attr >> 16) & 0o111:
            out.chmod(0o755)
'

TAG='import json, sys; print(json.load(sys.stdin)["tag_name"])'

# The release's own mild-setup.py, read out of the zipball to show its checklist.
SETUP_OF='
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    top = z.namelist()[0].split("/", 1)[0]
    sys.stdout.buffer.write(z.read(top + "/mild-setup.py"))
'

stage() {  # download the release into $tmp; fails saying why
    if [ -n "${MILD_ZIP:-}" ]; then  # a zipball on disk, to try a build before release
        say "Unpacking Mild Lyrics from $MILD_ZIP ..."
        cp "$MILD_ZIP" "$tmp/release.zip" || { warn "Could not read $MILD_ZIP."; return 1; }
    else
        say "Asking GitHub for the latest release ..."
        fetch "https://api.github.com/repos/$REPO/releases/latest" "$tmp/latest.json" \
            && tag=$("$py" -c "$TAG" <"$tmp/latest.json") \
            || { warn "Could not reach GitHub for the latest release."; return 1; }
        say "Downloading Mild Lyrics $tag ..."
        fetch "https://api.github.com/repos/$REPO/zipball/$tag" "$tmp/release.zip" \
            || { warn "The download of $tag did not finish."; return 1; }
    fi
    "$py" -c "$SETUP_OF" "$tmp/release.zip" >"$tmp/mild-setup.py" \
        || { warn "The download is not a Mild Lyrics release."; return 1; }
}

want() {  # want ID: picked, or no checklist (an older release: everything)
    [ -z "$picks" ] && return 0
    case ",$picks," in *",$1,"*) return 0 ;; *) return 1 ;; esac
}

choose_parts() {  # sets $picks from the checklist; fails when cancelled
    picks=
    "$py" "$tmp/mild-setup.py" --catalogue >/dev/null 2>&1 || return 0
    set --
    [ -f "$dir/.install-picks.json" ] && set -- --last "$dir/.install-picks.json"
    if [ -n "$GUI" ]; then
        rows=$("$py" "$tmp/mild-setup.py" --catalogue zenity-apps "$@") || return 1
        for_=$(printf '%s\n' "$rows" | z --list --radiolist --height=280 \
                --text="What do you want to install?" --column="" --column=id --column=Apps \
                --hide-column=2 --print-column=2) || return 1
        [ -n "$for_" ] || return 1
        rows=$("$py" "$tmp/mild-setup.py" --catalogue zenity --for "$for_" "$@") || return 1
        got=$(printf '%s\n' "$rows" | z --list --checklist --width=860 --height=640 \
                --text="Choose what to install. Unticking a category leaves all of it out; ticking only the category takes all of it." \
                --column="" --column=id --column=Install --column="What it is for" \
                --hide-column=2 --print-column=2 --separator=,) || return 1
        case $for_ in
            both) picks="app:lyrics,app:editor,$got" ;;
            *) picks="app:$for_,$got" ;;
        esac
        return 0
    fi
    [ "$TTY" = /dev/null ] && return 0          # nobody to ask: everything, as before
    "$py" "$tmp/mild-setup.py" --choose "$tmp/picks" "$@" <"$TTY" >"$TTY" || return 1
    picks=$(cat "$tmp/picks")
}

install_files() {  # unpack, set up and make the menu entries; fails saying why
    mkdir -p "$dir" && "$py" -c "$UNPACK" "$tmp/release.zip" "$dir" \
        || { warn "Could not unpack the release into $dir."; return 1; }

    say
    say "Installing what you picked into Mild Lyrics' own environment. This takes a few minutes the first time."
    say
    nodoc=; grep -q -- '--no-doctor' "$dir/mild-setup.py" && nodoc=--no-doctor
    export PIP_DISABLE_PIP_VERSION_CHECK=1
    code=0
    if [ -n "$picks" ]; then
        "$py" "$dir/mild-setup.py" --venv --pick "$picks" $nodoc <"$TTY" || code=$?
    else
        "$py" "$dir/mild-setup.py" --venv --yes --for both $nodoc <"$TTY" || code=$?
    fi
    echo "$code" >"$tmp/setup-code"

    vpy="$dir/.venv/bin/python3"
    if [ ! -x "$vpy" ] || ! "$vpy" -c 'import PyQt6.QtWidgets' 2>/dev/null; then
        warn "The setup above did not finish: Mild Lyrics cannot start yet."
        say  "         Its own lines above say what went wrong. Running this installer again retries."
        return 1
    fi
    say
    # A repair with less picked takes back the menu entries it made before.
    for stem in mild-lyrics ttml-editor; do
        case $stem in mild-lyrics) key=lyrics; name="Mild Lyrics" ;; *) key=editor; name="TTML Editor" ;; esac
        want "app:$key" && want shortcut:menu && continue
        if [ -n "$MAC" ]; then
            if points_here "$HOME/Applications/$name.app/Contents/MacOS/$stem"; then rm -rf "$HOME/Applications/$name.app"; fi
        elif points_here "$APPS/$stem.desktop"; then rm -f "$APPS/$stem.desktop"
        fi
    done
    if want shortcut:menu; then
        "$vpy" -c 'import sys; sys.path.insert(0, sys.argv[1]); import doctor; doctor.make_shortcut(sys.argv[2])' \
            "$dir/mild-lyrics" "$(which_apps)" </dev/null
    fi
}

which_apps() {  # lyrics, editor or both, from the picks
    if want app:lyrics && want app:editor; then say both
    elif want app:lyrics; then say lyrics
    else say editor; fi
}

app_names() {  # "Mild Lyrics and the TTML Editor", or the one picked
    case $(which_apps) in
        both) say "Mild Lyrics and the TTML Editor" ;;
        lyrics) say "Mild Lyrics" ;;
        *) say "the TTML Editor" ;;
    esac
}

start_app() {  # the first app picked
    stem=mild-lyrics; want app:lyrics || stem=ttml-editor
    (cd "$dir" && nohup "$dir/.venv/bin/python3" "$dir/$stem.pyw" </dev/null >/dev/null 2>&1 &)
}

do_install() {
    say "Mild Lyrics installer"
    say
    known=$(installed_dir || true)
    if [ -n "${MILD_DIR:-}" ]; then
        dir=$(resolve_target "$MILD_DIR" 2>"$tmp/why") || fail "$(cat "$tmp/why")"
    elif [ -n "$known" ]; then
        dir=$known
        if [ -n "$GUI" ]; then
            rc=0
            got=$(z --question --ok-label=Repair --cancel-label=Cancel --extra-button=Uninstall \
                    --text="Mild Lyrics is installed in$NL$NL$(esc "$(short "$dir")")$NL${NL}It updates itself. Repair puts its files and packages back as they should be.") || rc=$?
            if [ "$got" = Uninstall ]; then CONFIRMED=1; do_uninstall; return; fi
            [ "$rc" = 0 ] || exit 0
        else
            say "Already installed in $dir, so it is updated there. To move it, uninstall it first."
        fi
    else
        dir=$(read_install_dir) || exit 1
    fi
    say "Installing into $dir"
    say
    [ ! -e "$dir/.git" ] || fail "$dir is a git checkout. Update it with git and run ./setup.sh in it instead."

    py=$(find_python || true)
    if [ -z "$py" ]; then
        get_python || exit 1
        py=$(find_python || true)
        [ -n "$py" ] || fail "Python is still not found. Open a new terminal and run this installer again."
    fi
    say "Using Python at $py ($(py_version "$py"))"

    if ! "$py" -c 'import venv, ensurepip' 2>/dev/null; then
        # Debian and Ubuntu split venv out of python3.
        ver=$(py_version "$py")
        pkg=python3-venv; [ "$(basename "$py")" = python3 ] || pkg=python$ver-venv
        command -v apt >/dev/null 2>&1 \
            || fail "This Python cannot make virtual environments (no venv/ensurepip module)."
        ask "This Python cannot make virtual environments; Debian and Ubuntu ship that separately. Install it now?$NL$NL    apt install -y $pkg$NL${NL}This asks for your password." y \
            || exit 1
        run_step "Installing $pkg..." as_root apt install -y "$pkg" \
            || fail "$pkg could not be installed. Details: $LOG"
    fi

    run_step "Downloading Mild Lyrics..." stage \
        || fail "Mild Lyrics could not be downloaded. Details: $LOG"
    if ! choose_parts; then
        [ -n "$(ls -A "$dir" 2>/dev/null)" ] || rmdir "$dir" 2>/dev/null || true
        tell "Cancelled. Nothing was installed."
        exit 0
    fi
    if ! run_step "Installing what you picked. This takes a few minutes the first time." install_files; then
        if [ -n "$GUI" ]; then
            z --text-info --filename="$LOG" --width=780 --height=520 \
              --title="Mild Lyrics could not be installed"
        fi
        exit 1
    fi
    code=$(cat "$tmp/setup-code" 2>/dev/null || echo 0)

    names=$(app_names)
    first="Mild Lyrics"; want app:lyrics || first="TTML Editor"
    if [ -n "$MAC" ]; then where="in ~/Applications (Spotlight finds them)"
    else where="in your applications menu"; fi
    want shortcut:menu || where="in $(short "$dir") (no menu entries were picked)"
    if [ -n "$GUI" ]; then
        msg="Installed $names$NL$where.$NL${NL}It updates itself. Open this installer again to change what is installed, or to remove it."
        [ "$code" = 0 ] || msg="$msg$NL${NL}Setup left a warning or two, listed in$NL$(short "$LOG")"
        if z --question --ok-label="Start $first" --cancel-label=Close --text="$(esc "$msg")"; then
            start_app
        fi
        return
    fi
    say
    [ "$code" = 0 ] || warn "Setup left something to look at (above); Mild Lyrics itself is installed."
    say "Done. Installed $names $where."
    say "It updates itself. Run this installer again to change what is installed. To remove it:"
    if [ -f "$dir/install.sh" ]; then say "    sh \"$dir/install.sh\" --uninstall"
    else say "    curl -fsSL https://github.com/$REPO/releases/latest/download/install.sh | sh -s -- --uninstall"; fi
    if [ "$TTY" != /dev/null ] && ask "Start $first now?" y; then start_app; fi
}

points_here() {  # points_here FILE: the launcher FILE names this install
    [ -f "$1" ] && grep -qF "$dir" "$1"
}

do_uninstall() {
    dir=$(install_dir)
    if ! ours "$dir"; then tell "No Mild Lyrics installed at $dir."; exit 0; fi
    [ ! -e "$dir/.git" ] || fail "$dir is a git checkout, not an install; it is left alone."
    [ -n "${CONFIRMED:-}" ] || ask "Remove Mild Lyrics from $dir?" y || exit 0

    if [ -n "$MAC" ]; then
        for name in "Mild Lyrics" "TTML Editor"; do
            app="$HOME/Applications/$name.app"
            for run in "$app"/Contents/MacOS/*; do
                if points_here "$run"; then rm -rf "$app"; break; fi
            done
        done
        config="$HOME/Library/Application Support/mild-lyrics"
        cache="$HOME/Library/Caches/mild-lyrics"
    else
        for stem in mild-lyrics ttml-editor mild-lyrics-listen; do
            if points_here "$APPS/$stem.desktop"; then rm -f "$APPS/$stem.desktop"; fi
        done
        command -v update-desktop-database >/dev/null 2>&1 \
            && update-desktop-database "$APPS" >/dev/null 2>&1 || true
        config="${XDG_CONFIG_HOME:-$HOME/.config}/mild-lyrics"
        cache="${XDG_CACHE_HOME:-$HOME/.cache}/mild-lyrics"
    fi

    if [ -d "$config" ] || [ -d "$cache" ]; then
        kept=
        for d in "$config" "$cache"; do if [ -d "$d" ]; then kept="$kept$NL    $(short "$d")"; fi; done
        if [ -z "$GUI" ]; then say; fi
        if ask "Also delete your settings, history and caches?$kept" n; then rm -rf "$config" "$cache"; fi
    fi

    rm -rf "$dir"
    tell "Mild Lyrics is removed. If it is open, it keeps running until you close it.${NL}Spicetify's debug-port flag and its Spotify shortcut, if setup made them, are left as they are."
}

cleanup() {
    if [ -n "${tmp:-}" ]; then rm -rf "$tmp"; fi
    # A terminal window this script opened for itself would close on exit.
    if [ -n "${MILD_HOLD:-}" ] && [ "$TTY" != /dev/null ]; then
        printf '\nPress Enter to close this window. ' >/dev/tty
        read -r _ </dev/tty || true
    fi
}

# Everything runs from here, so a download cut off halfway runs nothing.
main() {
    action=install
    want_gui=
    while [ $# -gt 0 ]; do
        case "$1" in
            --uninstall) action=uninstall ;;
            --dir) [ $# -ge 2 ] || { say "--dir needs a folder"; exit 2; }; MILD_DIR=$2; shift ;;
            --dir=*) MILD_DIR=${1#--dir=} ;;
            --gui) want_gui=1 ;;
            *) say "usage: install.sh [--dir FOLDER] [--uninstall] [--gui]"; exit 2 ;;
        esac
        shift
    done

    # Opened from a file manager there is no terminal to talk in: dialogs if
    # zenity is here, else a terminal window, else a notification saying how.
    if [ -z "$want_gui" ] && [ "$TTY" = /dev/null ] && [ -z "${MILD_NO_GUI:-}" ]; then
        if [ -z "$MAC" ] && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
            if command -v zenity >/dev/null 2>&1; then want_gui=1
            elif in_terminal; then exit 0
            else
                notify-send "$TITLE" "Open a terminal and run:  sh $0" 2>/dev/null \
                    || xmessage "$TITLE: open a terminal and run:  sh $0" 2>/dev/null || true
                exit 1
            fi
        elif [ -n "$MAC" ] && in_terminal; then
            exit 0
        fi
    fi
    if [ -n "$want_gui" ]; then
        command -v zenity >/dev/null 2>&1 || { warn "--gui needs zenity"; exit 2; }
        GUI=1
        mkdir -p "$(dirname "$LOG")"
        exec >"$LOG" 2>&1
    fi

    tmp=$(mktemp -d)
    trap cleanup EXIT
    if [ "$action" = uninstall ]; then do_uninstall; else do_install; fi
}

main "$@"
