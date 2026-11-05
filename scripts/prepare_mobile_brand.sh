#!/bin/sh
# macOS asset preparation: retain the original logo aspect ratio and safe padding.
set -eu
cd "$(dirname "$0")/.."
command -v sips >/dev/null || { echo "Requires macOS sips" >&2; exit 1; }
asset_dir=apps/mobile-agent/assets
mkdir -p "$asset_dir/brand"
cp apps/web/public/brand/logo.png "$asset_dir/brand/logo.png"
cp apps/web/public/brand/banner.jpg "$asset_dir/brand/banner.jpg"
sips -Z 620 "$asset_dir/brand/logo.png" --out "$asset_dir/icon.png" >/dev/null
sips --padToHeightWidth 1024 1024 --padColor FFFFFF "$asset_dir/icon.png" >/dev/null
cp "$asset_dir/icon.png" "$asset_dir/android-icon-foreground.png"
