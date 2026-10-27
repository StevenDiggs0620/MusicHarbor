#!/bin/sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 launch.py
fi
printf '%s\n' 'Install Python 3.11 or newer from https://www.python.org/downloads/, then try again.'
read -r answer
