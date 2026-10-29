#!/usr/bin/env bash
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
set -euo pipefail
export LC_ALL=C TZ=UTC
umask 0022
if [[ $# != 3 ]]; then
    echo "Usage: $0 <keystore> <key-alias> <release-certificate-sha256>" >&2
    echo "Run in the extracted Android codesigning directory containing unsigned/." >&2
    exit 1
fi
: "${SOURCE_DATE_EPOCH:?Set SOURCE_DATE_EPOCH to the release reference timestamp}"
HOST="${HOST:-aarch64-linux-android}"
[[ "$HOST" == aarch64-linux-android ]] || { echo "Unsupported Android HOST: $HOST" >&2; exit 1; }
JARSIGNER="${JARSIGNER:-jarsigner}"
AAB_VERIFIER="${AAB_VERIFIER:-android-aab-verify}"
PYTHON="${PYTHON:-python3}"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
OUTPUT="signature-android-aab-${HOST}.tar.gz"
[[ ! -e "$OUTPUT" && ! -L "$OUTPUT" ]] || { echo "Output already exists: $OUTPUT" >&2; exit 1; }
[[ -d unsigned && ! -L unsigned ]] || { echo "Missing unsigned/." >&2; exit 1; }
if find unsigned -type l -print -quit | read -r _; then
    echo "Symlinks are forbidden in unsigned/." >&2
    exit 1
fi
mapfile -d '' BUNDLES < <(find unsigned -type f -name '*.aab' -print0 | sort -z)
[[ ${#BUNDLES[@]} != 0 ]] || { echo "No unsigned AABs found" >&2; exit 1; }
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/knots-aabsig.XXXXXXXX")
trap 'rm -rf -- "$WORKDIR"' EXIT
PASSWORD_ARGS=()
if [[ ${KNOTS_ANDROID_KEYSTORE_PASSWORD+x} ]]; then
    export KNOTS_ANDROID_KEYSTORE_PASSWORD
    PASSWORD_ARGS+=(-storepass:env KNOTS_ANDROID_KEYSTORE_PASSWORD)
fi
if [[ ${KNOTS_ANDROID_KEY_PASSWORD+x} ]]; then
    export KNOTS_ANDROID_KEY_PASSWORD
    PASSWORD_ARGS+=(-keypass:env KNOTS_ANDROID_KEY_PASSWORD)
fi
for BUNDLE in "${BUNDLES[@]}"; do
    RELATIVE=${BUNDLE#unsigned/}
    PAYLOAD="$WORKDIR/payloads/android/$HOST/$RELATIVE.json"
    mkdir -p -- "$(dirname -- "$PAYLOAD")"
    "$JARSIGNER" -keystore "$1" "${PASSWORD_ARGS[@]}" -sigfile KNOTS -digestalg SHA-256 \
        -signedjar "$WORKDIR/raw.aab" "$BUNDLE" "$2"
    "$AAB_VERIFIER" "$WORKDIR/raw.aab" "$3"
    "$PYTHON" "$SCRIPT_DIR/aab-signatures.py" normalize "$WORKDIR/raw.aab" "$WORKDIR/signed.aab"
    "$AAB_VERIFIER" "$WORKDIR/signed.aab" "$3"
    "$PYTHON" "$SCRIPT_DIR/aab-signatures.py" extract "$BUNDLE" "$WORKDIR/signed.aab" "$PAYLOAD" --certificate-sha256 "$3"
    "$PYTHON" "$SCRIPT_DIR/aab-signatures.py" apply "$BUNDLE" "$PAYLOAD" "$WORKDIR/reconstructed.aab" --certificate-sha256 "$3"
    cmp "$WORKDIR/signed.aab" "$WORKDIR/reconstructed.aab"
    rm -- "$WORKDIR/raw.aab" "$WORKDIR/signed.aab" "$WORKDIR/reconstructed.aab"
done
tar --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner \
    --mode='u+rw,go+r-w,a+X' -C "$WORKDIR/payloads" -cf - android \
    | gzip -9n > "$WORKDIR/signature.tar.gz"
(set -o noclobber; cat "$WORKDIR/signature.tar.gz" > "$OUTPUT")
echo "Created $OUTPUT"
