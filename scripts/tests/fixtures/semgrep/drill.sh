#!/usr/bin/env bash
# Fixture for #3549: Semgrep 1.181.0 parses no code line of this script.
set -eu
case "$1" in x) echo "x" ;; esac
echo "done"
