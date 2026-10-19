#!/bin/bash
# Build the Arch package from the current git HEAD instead of a release tarball, to check the packaging.
# Run as a normal user (makepkg refuses root). Add NODEPS=1 to skip the dependency check.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

pkgver=$(sed -n 's/^pkgver=//p' "$here/PKGBUILD")
git -C "$repo" archive --format=tar.gz --prefix="grab-$pkgver/" -o "$work/grab-dl-$pkgver.tar.gz" HEAD
sed -e "s|^source=.*|source=(\"grab-dl-\$pkgver.tar.gz\")|" "$here/PKGBUILD" > "$work/PKGBUILD"
cd "$work"
makepkg --force --noconfirm ${NODEPS:+--nodeps}

echo "== package contents"
pacman -Qlp ./*.pkg.tar.zst | sed 's|^grab-dl ||'
if command -v namcap >/dev/null; then
  echo "== namcap"
  namcap PKGBUILD ./*.pkg.tar.zst || true
fi
[[ -n ${KEEP:-} ]] && cp ./*.pkg.tar.zst "$here/" || true
