#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Build a disposable, ad-hoc-signed app-bundled PAPPL LaunchDaemon prototype.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
BUILD_ROOT=$(mktemp -d /private/tmp/hplj1020-lifecycle-build.XXXXXX)
SOURCE_ROOT="$BUILD_ROOT/sources"
PREFIX_ROOT="$BUILD_ROOT/prefix"
APP_PATH="$BUILD_ROOT/HP LJ 1020 Lifecycle Prototype.app"
JOBS=$(sysctl -n hw.logicalcpu 2>/dev/null || echo 4)

OPENSSL_VERSION=3.6.3
OPENSSL_SHA256=243a86649cf6f23eeb6a2ff2456e09e5d77dd9018a54d3d96b0c6bdd6ba6c7f1
OPENSSL_URL="https://github.com/openssl/openssl/releases/download/openssl-$OPENSSL_VERSION/openssl-$OPENSSL_VERSION.tar.gz"
LIBUSB_VERSION=1.0.30
LIBUSB_SHA256=fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf
LIBUSB_URL="https://github.com/libusb/libusb/releases/download/v$LIBUSB_VERSION/libusb-$LIBUSB_VERSION.tar.bz2"
PAPPL_TAG=v1.4.12
PAPPL_COMMIT=6db8e137557ad84662e78d24fdb2a591c621f4ac

mkdir -p "$SOURCE_ROOT" "$PREFIX_ROOT"

download_verified() {
  local url="$1" sha256="$2" output="$3" observed
  curl --fail --location --silent --show-error "$url" --output "$output"
  observed=$(shasum -a 256 "$output" | awk '{print $1}')
  if [[ "$observed" != "$sha256" ]]; then
    printf 'Checksum mismatch for %s\n' "$url" >&2
    exit 1
  fi
}

if [[ -n "${OPENSSL_PREFIX_OVERRIDE:-}" ]]; then
  OPENSSL_PREFIX="$OPENSSL_PREFIX_OVERRIDE"
else
  OPENSSL_ARCHIVE="$SOURCE_ROOT/openssl-$OPENSSL_VERSION.tar.gz"
  download_verified "$OPENSSL_URL" "$OPENSSL_SHA256" "$OPENSSL_ARCHIVE"
  tar -xzf "$OPENSSL_ARCHIVE" -C "$SOURCE_ROOT"
  OPENSSL_SOURCE="$SOURCE_ROOT/openssl-$OPENSSL_VERSION"
  OPENSSL_PREFIX="$PREFIX_ROOT/openssl"
  (
    cd "$OPENSSL_SOURCE"
    ./Configure darwin64-arm64-cc no-shared no-tests --prefix="$OPENSSL_PREFIX"
    make -j"$JOBS" build_sw
    make install_sw
  )
fi

if [[ -n "${LIBUSB_PREFIX_OVERRIDE:-}" ]]; then
  LIBUSB_PREFIX="$LIBUSB_PREFIX_OVERRIDE"
else
  LIBUSB_ARCHIVE="$SOURCE_ROOT/libusb-$LIBUSB_VERSION.tar.bz2"
  download_verified "$LIBUSB_URL" "$LIBUSB_SHA256" "$LIBUSB_ARCHIVE"
  tar -xjf "$LIBUSB_ARCHIVE" -C "$SOURCE_ROOT"
  LIBUSB_SOURCE="$SOURCE_ROOT/libusb-$LIBUSB_VERSION"
  LIBUSB_PREFIX="$PREFIX_ROOT/libusb"
  (
    cd "$LIBUSB_SOURCE"
    ./configure --prefix="$LIBUSB_PREFIX" --disable-shared --enable-static
    make -j"$JOBS"
    make install
  )
fi

if [[ -n "${PAPPL_SOURCE_DIR_OVERRIDE:-}" ]]; then
  PAPPL_SOURCE="$PAPPL_SOURCE_DIR_OVERRIDE"
else
  PAPPL_SOURCE="$SOURCE_ROOT/pappl"
  git clone --quiet --depth 1 --branch "$PAPPL_TAG" https://github.com/michaelrsweet/pappl.git "$PAPPL_SOURCE"
fi

if [[ "$(git -C "$PAPPL_SOURCE" rev-parse HEAD)" != "$PAPPL_COMMIT" ]]; then
  printf 'PAPPL source is not the pinned commit %s\n' "$PAPPL_COMMIT" >&2
  exit 1
fi

PAPPL_PREFIX="$PREFIX_ROOT/pappl"
(
  cd "$PAPPL_SOURCE"
  make clean >/dev/null 2>&1 || true
  PKG_CONFIG_PATH="$LIBUSB_PREFIX/lib/pkgconfig:$OPENSSL_PREFIX/lib/pkgconfig" \
    ./configure \
      --prefix="$PAPPL_PREFIX" \
      --enable-libusb \
      --disable-shared \
      --disable-libjpeg \
      --disable-libpng \
      --disable-libpam \
      --with-papplstatedir="/Library/Application Support/HP-LJ-1020/State" \
      CFLAGS='-mmacosx-version-min=26.0 -arch arm64' \
      CPPFLAGS="-I$LIBUSB_PREFIX/include -I$OPENSSL_PREFIX/include" \
      LDFLAGS="-mmacosx-version-min=26.0 -arch arm64 -L$LIBUSB_PREFIX/lib -L$OPENSSL_PREFIX/lib"
  make -C pappl -j"$JOBS" libpappl.a
  make -C testsuite -j"$JOBS" testmainloop.o pwg-driver.o
)

COMMON_LIBS=(
  "$PAPPL_SOURCE/pappl/libpappl.a"
  "$OPENSSL_PREFIX/lib/libssl.a"
  "$OPENSSL_PREFIX/lib/libcrypto.a"
  "$LIBUSB_PREFIX/lib/libusb-1.0.a"
  -lcups -lpthread -lz
  -framework AppKit
  -framework CoreFoundation
  -framework Foundation
  -framework IOKit
  -framework Security
  -framework SystemConfiguration
)

mkdir -p \
  "$APP_PATH/Contents/MacOS" \
  "$APP_PATH/Contents/Library/LaunchDaemons" \
  "$APP_PATH/Contents/Resources" \
  "$BUILD_ROOT/swift-module-cache"

clang -mmacosx-version-min=26.0 -arch arm64 \
  -o "$APP_PATH/Contents/MacOS/hplj1020-pappl" \
  "$PAPPL_SOURCE/testsuite/testmainloop.o" \
  "$PAPPL_SOURCE/testsuite/pwg-driver.o" \
  "${COMMON_LIBS[@]}"

clang -mmacosx-version-min=26.0 -arch arm64 \
  -I"$PAPPL_SOURCE" -I"$LIBUSB_PREFIX/include/libusb-1.0" \
  -o "$APP_PATH/Contents/MacOS/hplj1020-usb-probe" \
  "$SCRIPT_DIR/pappl-usb-probe.c" \
  "${COMMON_LIBS[@]}"

swiftc -O -target arm64-apple-macosx26.0 \
  -module-cache-path "$BUILD_ROOT/swift-module-cache" \
  -framework Foundation -framework ServiceManagement \
  "$SCRIPT_DIR/controller.swift" \
  -o "$APP_PATH/Contents/MacOS/hplj1020-lifecycle"

cp "$SCRIPT_DIR/Info.plist" "$APP_PATH/Contents/Info.plist"
cp "$SCRIPT_DIR/com.bartekpapierski.hplj1020.lifecycle.daemon.plist" \
  "$APP_PATH/Contents/Library/LaunchDaemons/"

cat > "$APP_PATH/Contents/Resources/build-manifest.txt" <<EOF
prototype=personal-installation-lifecycle
architecture=arm64
minimum_macos=26.0
pappl_tag=$PAPPL_TAG
pappl_commit=$PAPPL_COMMIT
openssl_version=$OPENSSL_VERSION
openssl_sha256=$OPENSSL_SHA256
libusb_version=$LIBUSB_VERSION
libusb_sha256=$LIBUSB_SHA256
signing=adhoc+hardened-runtime
EOF

codesign --force --sign - --options runtime \
  --identifier com.bartekpapierski.hplj1020.lifecycle.pappl \
  "$APP_PATH/Contents/MacOS/hplj1020-pappl"
codesign --force --sign - --options runtime \
  --identifier com.bartekpapierski.hplj1020.lifecycle.usb-probe \
  "$APP_PATH/Contents/MacOS/hplj1020-usb-probe"
codesign --force --sign - --options runtime \
  --identifier com.bartekpapierski.hplj1020.lifecycle.controller \
  "$APP_PATH/Contents/MacOS/hplj1020-lifecycle"
codesign --force --sign - --options runtime "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

printf 'APP_PATH=%s\n' "$APP_PATH"
