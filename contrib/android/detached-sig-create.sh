#!/usr/bin/env bash
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
set -euo pipefail
export LC_ALL=C TZ=UTC
umask 0022

if [[ $# != 3 ]]; then
    echo "Usage: $0 <keystore> <key-alias> <release-certificate-sha256>" >&2
    echo "Run in the extracted Android codesigning directory containing unsigned/." >&2
    echo "Optional passwords: KNOTS_ANDROID_KEYSTORE_PASSWORD and KNOTS_ANDROID_KEY_PASSWORD." >&2
    exit 1
fi
: "${SOURCE_DATE_EPOCH:?Set SOURCE_DATE_EPOCH to the release reference timestamp}"
HOST="${HOST:-aarch64-linux-android}"
[[ "$HOST" == aarch64-linux-android ]] || { echo "Unsupported Android HOST: $HOST" >&2; exit 1; }
APKSIGNER="${APKSIGNER:-apksigner}"
PYTHON="${PYTHON:-python3}"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HELPER="$SCRIPT_DIR/apk-signatures.py"
OUTPUT="signature-android-${HOST}.tar.gz"
[[ ! -e "$OUTPUT" ]] || { echo "Output already exists: $OUTPUT" >&2; exit 1; }
[[ -d unsigned && ! -L unsigned ]] || { echo "Missing unsigned/ directory" >&2; exit 1; }
if find unsigned -type l -print -quit | read -r _; then
    echo "Symlinks are not permitted in unsigned/." >&2
    exit 1
fi
mapfile -d '' APKS < <(find unsigned -type f -name '*.apk' -print0 | sort -z)
[[ ${#APKS[@]} != 0 ]] || { echo "No unsigned APKs found" >&2; exit 1; }
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/knots-apksig.XXXXXXXX")
trap 'rm -rf -- "$WORKDIR"' EXIT
PASSWORD_ARGS=()
if [[ ${KNOTS_ANDROID_KEYSTORE_PASSWORD+x} ]]; then
    export KNOTS_ANDROID_KEYSTORE_PASSWORD
    PASSWORD_ARGS+=(--ks-pass env:KNOTS_ANDROID_KEYSTORE_PASSWORD)
fi
if [[ ${KNOTS_ANDROID_KEY_PASSWORD+x} ]]; then
    export KNOTS_ANDROID_KEY_PASSWORD
    PASSWORD_ARGS+=(--key-pass env:KNOTS_ANDROID_KEY_PASSWORD)
fi

for APK in "${APKS[@]}"; do
    RELATIVE=${APK#unsigned/}
    PAYLOAD="$WORKDIR/payloads/android/$HOST/$RELATIVE.json"
    mkdir -p -- "$(dirname -- "$PAYLOAD")"
    "$PYTHON" "$HELPER" check-alignment "$APK"
    "$APKSIGNER" sign --ks "$1" --ks-key-alias "$2" "${PASSWORD_ARGS[@]}" \
        --min-sdk-version 28 --v1-signing-enabled false --v2-signing-enabled true \
        --v3-signing-enabled true --v4-signing-enabled false \
        --alignment-preserved true --verity-enabled false --debuggable-apk-permitted false \
        --out "$WORKDIR/signed.apk" "$APK"
    # The default verifier skips v2 when the manifest requires API 28 or newer.
    # Start verification at API 24 to exercise both v2 and v3 signatures.
    "$APKSIGNER" verify --min-sdk-version 24 --verbose --print-certs "$WORKDIR/signed.apk" > "$WORKDIR/verify.txt"
    "$PYTHON" "$HELPER" verify-report "$WORKDIR/verify.txt" --certificate-sha256 "$3"
    "$PYTHON" "$HELPER" extract "$APK" "$WORKDIR/signed.apk" "$PAYLOAD" --certificate-sha256 "$3"
    "$PYTHON" "$HELPER" apply "$APK" "$PAYLOAD" "$WORKDIR/reconstructed.apk" --certificate-sha256 "$3"
    cmp "$WORKDIR/signed.apk" "$WORKDIR/reconstructed.apk"
    rm -- "$WORKDIR/signed.apk" "$WORKDIR/reconstructed.apk"
done

tar --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner \
    --mode='u+rw,go+r-w,a+X' -C "$WORKDIR/payloads" -cf - android \
    | gzip -9n > "$WORKDIR/signature.tar.gz"
(set -o noclobber; cat "$WORKDIR/signature.tar.gz" > "$OUTPUT")
echo "Created $OUTPUT"
