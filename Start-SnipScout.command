#!/bin/sh
# SnipScout launcher for Linux and macOS (Start-SnipScout.command is the same file for Finder).
# First run: installs uv into ./.uv (only with your consent), prepares Python and the dependencies.
# Then it opens SnipScout. Extra arguments are passed to the `snipscout` command (default: ui).
set -u

APPDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UVDIR="$APPDIR/.uv"
LOG="$APPDIR/snipscout-error.log"
ISSUES="https://github.com/datamauriciovaldez/SnipScout/issues"
cd "$APPDIR" || exit 1
: > "$LOG"

fail() {
  echo ""
  echo "  Algo ha fallado / Something went wrong: $1"
  echo "  Detalles / Details: $LOG"
  echo "  Puedes adjuntar ese archivo en / You can attach that file at: $ISSUES"
  echo ""
  exit 1
}

echo ""
echo "  SnipScout"
echo ""

# 1) uv: already installed, our private copy, or install it (with consent).
if command -v uv >/dev/null 2>&1; then
  UV=$(command -v uv)
elif [ -x "$UVDIR/uv" ]; then
  UV="$UVDIR/uv"
else
  echo "  SnipScout necesita \"uv\" para preparar Python la primera vez (unos 30 MB)."
  echo "  SnipScout needs \"uv\" to set up Python the first time (about 30 MB)."
  if [ "${SNIPSCOUT_ASSUME_YES:-}" != "1" ]; then
    printf "  ¿Instalarlo ahora en esta carpeta? / Install it now in this folder? [s/y/N] "
    read -r answer
    case "$answer" in
      s|S|y|Y|si|SI|yes|YES) ;;
      *) echo "  Cancelado. / Cancelled."; exit 1 ;;
    esac
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://github.com/astral-sh/uv/releases/latest/download/uv-installer.sh \
      | env UV_UNMANAGED_INSTALL="$UVDIR" sh >>"$LOG" 2>&1 || fail "uv"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://github.com/astral-sh/uv/releases/latest/download/uv-installer.sh \
      | env UV_UNMANAGED_INSTALL="$UVDIR" sh >>"$LOG" 2>&1 || fail "uv"
  else
    fail "curl/wget"
  fi
  [ -x "$UVDIR/uv" ] || fail "uv"
  UV="$UVDIR/uv"
fi

# 2) Python + dependencies (first run downloads a few hundred MB; later runs are instant).
echo "  Preparando SnipScout (la primera vez tarda unos minutos)..."
echo "  Preparing SnipScout (the first time takes a few minutes)..."
"$UV" sync --project "$APPDIR" --no-dev --managed-python --python 3.12 >>"$LOG" 2>&1 || fail "uv sync"

# 3) Run.
[ $# -eq 0 ] && set -- ui
"$UV" run --project "$APPDIR" --no-dev --no-sync snipscout "$@" 2>>"$LOG"
status=$?
[ $status -eq 0 ] || [ $status -eq 130 ] || fail "snipscout ($status)"
rm -f "$LOG"
exit 0
