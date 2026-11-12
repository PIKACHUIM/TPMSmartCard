#!/usr/bin/env bash
# 桌面端打包脚本（Linux / macOS）。
#
# Windows 请用 scripts/package-windows.ps1。
#
# 用法：
#   ./scripts/package-desktop.sh 2.0.0
#
# 依赖：
#   Linux  libgtk-3-dev libwebkit2gtk-4.0-dev pkg-config
#   macOS  Xcode Command Line Tools
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-2.0.0}"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
DIST="$ROOT/dist"
mkdir -p "$DIST"

echo "==> 构建前端"
cd "$ROOT"
npm ci --include=dev
npm run build -w @tpmsc/web
node scripts/prepare-ui.mjs

echo "==> 单元测试"
(cd "$ROOT/core" && go test ./...)

echo "==> 构建桌面端 ($VERSION / $COMMIT)"
cd "$ROOT/desktop/wails"
LDFLAGS="-s -w -X main.Version=${VERSION} -X main.Commit=${COMMIT}"

case "$(uname -s)" in
  Darwin)
    CGO_ENABLED=1 go build -tags desktop -trimpath -ldflags "$LDFLAGS" -o "$DIST/TPMSmartCard" .
    APP="$DIST/TPMSmartCard.app"
    rm -rf "$APP"
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
    cp "$DIST/TPMSmartCard" "$APP/Contents/MacOS/TPMSmartCard"
    cp ../packaging/macos/Info.plist "$APP/Contents/Info.plist"
    cp ../packaging/macos/entitlements.plist "$APP/Contents/Resources/entitlements.plist"
    if [[ -n "${MACOS_SIGN_IDENTITY:-}" ]]; then
      echo "==> 签名（${MACOS_SIGN_IDENTITY}）"
      codesign --force --deep --options runtime \
        --entitlements ../packaging/macos/entitlements.plist \
        --sign "$MACOS_SIGN_IDENTITY" "$APP"
      if [[ -n "${MACOS_NOTARY_PROFILE:-}" ]]; then
        echo "==> 公证"
        ditto -c -k --keepParent "$APP" "$DIST/TPMSmartCard.zip"
        xcrun notarytool submit "$DIST/TPMSmartCard.zip" \
          --keychain-profile "$MACOS_NOTARY_PROFILE" --wait
        xcrun stapler staple "$APP"
      fi
    else
      echo "!! 未设置 MACOS_SIGN_IDENTITY：Secure Enclave 将不可用（会降级为软件密钥）"
    fi
    (cd "$DIST" && zip -qry "TPMSmartCard-darwin-$(uname -m)-${VERSION}.zip" TPMSmartCard.app)
    ;;
  Linux)
    CGO_ENABLED=1 go build -tags desktop -trimpath -ldflags "$LDFLAGS" -o "$DIST/TPMSmartCard" .
    PKG="$DIST/tpmsmartcard-${VERSION}-linux-$(uname -m)"
    rm -rf "$PKG"
    mkdir -p "$PKG/usr/bin" "$PKG/usr/share/applications"
    cp "$DIST/TPMSmartCard" "$PKG/usr/bin/TPMSmartCard"
    cp ../packaging/linux/tpmsmartcard.desktop "$PKG/usr/share/applications/"
    cp "$ROOT/legacy/Config/iconer/icon01.png" "$PKG/usr/share/applications/tpmsmartcard.png"
    tar -czf "${PKG}.tar.gz" -C "$DIST" "$(basename "$PKG")"
    ;;
  *)
    echo "此脚本只支持 Linux / macOS；Windows 请使用 scripts/package-windows.ps1" >&2
    exit 1
    ;;
esac

echo "==> 产物"
ls -lh "$DIST"
