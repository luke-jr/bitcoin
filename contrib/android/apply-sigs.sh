#!/usr/bin/env bash
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
set -euo pipefail
export LC_ALL=C TZ=UTC
umask 0022

if [[ $# != 4 ]]; then
    echo "Usage: $0 <unsigned.apk> <signature.json> <output.apk> <release-certificate-sha256>" >&2
    exit 1
fi
APKSIGNER="${APKSIGNER:-apksigner}"
PYTHON="${PYTHON:-python3}"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HELPER="$SCRIPT_DIR/apk-signatures.py"
[[ ! -e "$3" && ! -L "$3" ]] || { echo "Output already exists: $3" >&2; exit 1; }
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/knots-apksig.XXXXXXXX")
trap 'rm -rf -- "$WORKDIR"' EXIT
"$PYTHON" "$HELPER" check-alignment "$1"
"$PYTHON" "$HELPER" apply "$1" "$2" "$WORKDIR/signed.apk" --certificate-sha256 "$4"
"$APKSIGNER" verify --min-sdk-version 24 --verbose --print-certs "$WORKDIR/signed.apk" > "$WORKDIR/verify.txt"
"$PYTHON" "$HELPER" verify-report "$WORKDIR/verify.txt" --certificate-sha256 "$4"
"$PYTHON" "$HELPER" check-alignment "$WORKDIR/signed.apk"
# Publish only after all checks pass; noclobber also protects an output created
# by another process while verification was running.
(set -o noclobber; cat "$WORKDIR/signed.apk" > "$3")
