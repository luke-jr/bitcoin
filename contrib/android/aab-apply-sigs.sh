#!/usr/bin/env bash
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
set -euo pipefail
export LC_ALL=C TZ=UTC
umask 0022
if [[ $# != 4 ]]; then
    echo "Usage: $0 <unsigned.aab> <signature.json> <output.aab> <release-certificate-sha256>" >&2
    exit 1
fi
: "${SOURCE_DATE_EPOCH:?Set SOURCE_DATE_EPOCH to the release reference timestamp}"
AAB_VERIFIER="${AAB_VERIFIER:-android-aab-verify}"
PYTHON="${PYTHON:-python3}"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ ! -e "$3" && ! -L "$3" ]] || { echo "Output already exists: $3" >&2; exit 1; }
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/knots-aabsig.XXXXXXXX")
trap 'rm -rf -- "$WORKDIR"' EXIT
"$PYTHON" "$SCRIPT_DIR/aab-signatures.py" apply "$1" "$2" "$WORKDIR/signed.aab" --certificate-sha256 "$4"
"$AAB_VERIFIER" "$WORKDIR/signed.aab" "$4"
(set -o noclobber; cat "$WORKDIR/signed.aab" > "$3")
