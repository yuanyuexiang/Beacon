#!/bin/sh
# Local development only: restore phone-to-computer API forwarding after USB reconnect.
set -eu
adb reverse tcp:8000 tcp:8000
adb reverse --list
