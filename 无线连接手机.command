#!/bin/zsh
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/Library/Android/sdk/platform-tools:$PATH"
uv run scripts/connect_mobile_wireless.py
