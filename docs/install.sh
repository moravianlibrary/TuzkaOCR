#!/bin/sh
set -eu

main() {
    repo="moravianlibrary/TuzkaOCR"
    python_version="3.13"
    docs="https://moravianlibrary.github.io/TuzkaOCR"

    check_platform
    need_downloader

    uv=$(find_uv)
    if [ -z "$uv" ]; then
        say "Installing uv, the tool that installs TuzkaOCR and its Python..."
        download https://astral.sh/uv/install.sh | sh || fail "uv could not be installed."
        uv=$(find_uv)
        [ -n "$uv" ] || fail "uv was installed but cannot be found. Open a new terminal and run this line again."
    fi

    tag="${TUZKAOCR_VERSION:-}"
    if [ -z "$tag" ]; then
        tag=$(latest_tag) || fail "could not reach GitHub to find the latest TuzkaOCR release."
    fi
    case "$tag" in
        v[0-9]*) ;;
        *) fail "could not find the latest TuzkaOCR release (got '$tag')." ;;
    esac

    bin=$("$uv" tool dir --bin)
    PATH=$(path_without "$bin") "$uv" tool update-shell >/dev/null 2>&1 || true
    PATH="$bin:$PATH"
    export PATH

    say "Installing TuzkaOCR $tag. This downloads a few hundred megabytes and takes a few minutes..."
    "$uv" tool install --force --python "$python_version" \
        "https://github.com/$repo/archive/refs/tags/$tag.zip" \
        || fail "uv could not install TuzkaOCR $tag."

    "$bin/tuzkaocr" --help >/dev/null 2>&1 || fail "TuzkaOCR was installed but does not start."

    say ""
    say "TuzkaOCR $tag is installed."
    say "Close this terminal window, open a new one, and type:  tuzkaocr app"
}

say() {
    printf '%s\n' "$*"
}

fail() {
    printf '\nTuzkaOCR install failed: %s\n' "$*" >&2
    printf 'Help: %s/troubleshooting/\n' "$docs" >&2
    exit 1
}

check_platform() {
    os=$(uname -s)
    arch=$(uname -m)
    case "$os" in
        Linux) ;;
        Darwin)
            if [ "$arch" != "arm64" ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" != "1" ]; then
                fail "Intel Macs are not supported. Use the Docker image instead: $docs/docker/"
            fi
            if [ "$arch" != "arm64" ]; then
                fail "this Terminal runs under Rosetta. Open Terminal without 'Open using Rosetta' and run this line again."
            fi
            ;;
        *) fail "unsupported system '$os'. On Windows, use the PowerShell line from $docs/beginners/" ;;
    esac
}

need_downloader() {
    if command -v curl >/dev/null 2>&1; then
        return
    fi
    if command -v wget >/dev/null 2>&1; then
        return
    fi
    fail "neither curl nor wget is installed."
}

download() {
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "$1"
    else
        wget -qO- "$1"
    fi
}

latest_tag() {
    url="https://github.com/$repo/releases/latest"
    if command -v curl >/dev/null 2>&1; then
        final=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "$url") || return 1
    else
        final=$(wget -S --spider "$url" 2>&1 | sed -n 's/^ *[Ll]ocation: *//p' | tail -n 1 | tr -d '\r' | sed 's/ .*//') || return 1
    fi
    printf '%s\n' "${final##*/}"
}

path_without() {
    printf '%s\n' "$PATH" | tr ':' '\n' | grep -vxF "$1" | grep -vxF "$1/" | paste -sd: -
}

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return
    fi
    for dir in "${XDG_BIN_HOME:-}" "$HOME/.local/bin" "${CARGO_HOME:-$HOME/.cargo}/bin"; do
        if [ -n "$dir" ] && [ -x "$dir/uv" ]; then
            printf '%s\n' "$dir/uv"
            return
        fi
    done
}

main "$@"
