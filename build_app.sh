#!/bin/bash
# Сборка VY Glow.app (запускать один раз, и после каждого изменения main.py)
set -e
cd "$(dirname "$0")"
source ../.venv/bin/activate
pip install pyinstaller
pyinstaller --windowed --noconfirm --name "VY Glow" main.py

APP="dist/VY Glow.app"
PLIST="$APP/Contents/Info.plist"
TEXT="VY Glow управляет LED-лентой по Bluetooth"

# без этого ключа macOS закрывает приложение при обращении к Bluetooth
plutil -replace NSBluetoothAlwaysUsageDescription -string "$TEXT" "$PLIST" 2>/dev/null \
  || plutil -insert NSBluetoothAlwaysUsageDescription -string "$TEXT" "$PLIST"

# приложение живёт только в строке меню, без иконки в Dock
# (чтобы вернуть иконку в Dock, удалите следующую строку и пересоберите)
plutil -replace LSUIElement -bool true "$PLIST"

# подпись нужна на Apple Silicon после правки Info.plist
codesign --force --deep --sign - "$APP"

