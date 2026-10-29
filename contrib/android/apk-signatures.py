#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Transport APK v2/v3 signatures without changing any ZIP entry bytes.

This is not a cryptographic signature verifier. The accompanying shell scripts
run apksigner and check the independently supplied release certificate digest.
Only ordinary, single-disk ZIP32 APKs with v2/v3 signatures are supported.
"""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import zipfile


MAGIC = b"APK Sig Block 42"
MAX_PAYLOAD = 16 * 1024 * 1024
V2 = 0x7109871A
V3 = 0xF05368C0
PADDING = 0x42726577
FIELDS = {
    "version", "unsigned_sha256", "signed_sha256", "certificate_sha256",
    "unsigned_size", "signed_size", "unsigned_cd_offset", "signed_cd_offset",
    "insertion_base64",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def certificate_digest(value):
    value = value.replace(":", "").lower()
    require(re.fullmatch(r"[0-9a-f]{64}", value), "Expected a SHA-256 certificate digest")
    return value


def zip_sections(data):
    """Return (central-directory offset, EOCD offset), rejecting ambiguous ZIPs."""
    require(22 <= len(data) < 0xFFFFFFFF, "APK must be a nonempty ZIP32 archive")
    candidates = []
    for offset in range(max(0, len(data) - 65557), len(data) - 21):
        if data[offset:offset + 4] != b"PK\x05\x06":
            continue
        _, disk, cd_disk, disk_count, count, cd_size, cd_offset, comment_size = struct.unpack_from("<4s4H2IH", data, offset)
        if offset + 22 + comment_size != len(data):
            continue
        require(disk == cd_disk == 0 and disk_count == count, "Split ZIP archives are unsupported")
        require(count not in (0, 0xFFFF) and cd_size != 0xFFFFFFFF and cd_offset != 0xFFFFFFFF, "ZIP64 or empty archives are unsupported")
        require(cd_offset + cd_size == offset, "Unexpected data between ZIP central directory and EOCD")
        candidates.append((cd_offset, offset, count))
    require(len(candidates) == 1, "Missing or ambiguous ZIP end record")
    cd_offset, eocd_offset, count = candidates[0]
    names = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        require(len(entries) == count, "ZIP entry count mismatch")
        for entry in entries:
            name = entry.filename
            require(name == entry.orig_filename and name and "\x00" not in name and "\\" not in name and not name.startswith("/") and
                    all(part not in ("", ".", "..") for part in name.rstrip("/").split("/")), "Unsafe ZIP entry name")
            require(name not in names, "Duplicate ZIP entry")
            names.add(name)
            require(not entry.flag_bits & 1, "Encrypted ZIP entries are unsupported")
            require(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "Unsupported APK compression method")
            require(entry.extract_version < 45 and entry.header_offset < cd_offset, "ZIP64 or invalid local header")
            require(not re.fullmatch(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", name, re.IGNORECASE), "APK v1 signing entries are unsupported")
            with archive.open(entry):
                # Opening validates the local header and its name against the CD.
                name_size, extra_size = struct.unpack_from("<HH", data, entry.header_offset + 26)
                data_offset = entry.header_offset + 30 + name_size + extra_size
                require(data_offset + entry.compress_size <= cd_offset, "ZIP entry overlaps the central directory")
        require(min(entry.header_offset for entry in entries) == 0, "Unexpected prefix before ZIP entries")
    require("AndroidManifest.xml" in names, "APK has no AndroidManifest.xml")
    return cd_offset, eocd_offset


def normalized_eocd(data, offset):
    result = bytearray(data[offset:])
    result[16:20] = b"\0" * 4
    return result


def validate_alignment(data):
    """Check stored-entry offsets without relying on an Android SDK zipalign."""
    zip_sections(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or entry.compress_type != zipfile.ZIP_STORED:
                continue
            name_size, extra_size = struct.unpack_from("<HH", data, entry.header_offset + 26)
            offset = entry.header_offset + 30 + name_size + extra_size
            alignment = 16384 if entry.filename.endswith(".so") else 4
            require(offset % alignment == 0, f"Stored ZIP entry is not {alignment}-byte aligned: {entry.filename}")


def signing_block_start(data, cd_offset):
    require(cd_offset >= 32 and data[cd_offset - 16:cd_offset] == MAGIC, "Missing APK signing block")
    size = struct.unpack_from("<Q", data, cd_offset - 24)[0]
    require(24 <= size <= MAX_PAYLOAD and size + 8 <= cd_offset, "Invalid APK signing block size")
    start = cd_offset - size - 8
    require(struct.unpack_from("<Q", data, start)[0] == size, "APK signing block sizes differ")
    cursor = start + 8
    ids = set()
    while cursor < cd_offset - 24:
        require(cursor + 12 <= cd_offset - 24, "Truncated signing block pair")
        pair_size, pair_id = struct.unpack_from("<QI", data, cursor)
        require(pair_size >= 4 and cursor + 8 + pair_size <= cd_offset - 24, "Invalid signing block pair size")
        require(pair_id not in ids and pair_id in (V2, V3, PADDING), "Unexpected or duplicate signing block ID")
        ids.add(pair_id)
        cursor += 8 + pair_size
    require(cursor == cd_offset - 24 and {V2, V3} <= ids, "Both APK v2 and v3 signatures are required")
    return start


def validate_pair(unsigned, signed):
    unsigned_cd, unsigned_eocd = zip_sections(unsigned)
    signed_cd, signed_eocd = zip_sections(signed)
    require(unsigned[unsigned_cd - 16:unsigned_cd] != MAGIC, "Input APK is already signed")
    block_start = signing_block_start(signed, signed_cd)
    require(unsigned_cd <= block_start and 0 < signed_cd - unsigned_cd <= MAX_PAYLOAD, "Invalid signature insertion offset or size")
    require(signed[:unsigned_cd] == unsigned[:unsigned_cd], "Signing changed ZIP entry bytes")
    require(not any(signed[unsigned_cd:block_start]), "Unexpected nonzero padding before signing block")
    require(signed[signed_cd:signed_eocd] == unsigned[unsigned_cd:unsigned_eocd], "Signing changed the ZIP central directory")
    require(normalized_eocd(signed, signed_eocd) == normalized_eocd(unsigned, unsigned_eocd), "Signing changed ZIP EOCD fields other than the central directory offset")
    return unsigned_cd, signed_cd


def extract(unsigned, signed, certificate):
    unsigned_cd, signed_cd = validate_pair(unsigned, signed)
    return {
        "version": 1,
        "unsigned_sha256": digest(unsigned),
        "signed_sha256": digest(signed),
        "certificate_sha256": certificate_digest(certificate),
        "unsigned_size": len(unsigned),
        "signed_size": len(signed),
        "unsigned_cd_offset": unsigned_cd,
        "signed_cd_offset": signed_cd,
        "insertion_base64": base64.b64encode(signed[unsigned_cd:signed_cd]).decode("ascii"),
    }


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def load_payload(path):
    require(path.stat().st_size <= MAX_PAYLOAD * 2, "Signature payload is too large")
    result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    require(isinstance(result, dict) and result.keys() == FIELDS, "Unexpected signature payload fields")
    require(type(result["version"]) is int and result["version"] == 1, "Unsupported payload version")
    for key in ("unsigned_size", "signed_size", "unsigned_cd_offset", "signed_cd_offset"):
        require(type(result[key]) is int and 0 <= result[key] < 0xFFFFFFFF, "Invalid payload size or offset")
    for key in ("unsigned_sha256", "signed_sha256", "certificate_sha256"):
        require(isinstance(result[key], str) and re.fullmatch(r"[0-9a-f]{64}", result[key]), "Invalid payload SHA-256 digest")
    require(isinstance(result["insertion_base64"], str), "Invalid signature insertion encoding")
    return result


def apply(unsigned, payload, certificate):
    require(payload["certificate_sha256"] == certificate_digest(certificate), "Release certificate digest mismatch")
    require(len(unsigned) == payload["unsigned_size"] and digest(unsigned) == payload["unsigned_sha256"], "Unsigned APK digest or size mismatch")
    cd_offset, eocd_offset = zip_sections(unsigned)
    require(cd_offset == payload["unsigned_cd_offset"], "Unsigned central directory offset mismatch")
    insertion = base64.b64decode(payload["insertion_base64"], validate=True)
    require(0 < len(insertion) <= MAX_PAYLOAD and cd_offset + len(insertion) == payload["signed_cd_offset"], "Signature insertion size mismatch")
    eocd = bytearray(unsigned[eocd_offset:])
    struct.pack_into("<I", eocd, 16, cd_offset + len(insertion))
    signed = unsigned[:cd_offset] + insertion + unsigned[cd_offset:eocd_offset] + eocd
    require(len(signed) == payload["signed_size"] and digest(signed) == payload["signed_sha256"], "Reconstructed APK digest or size mismatch")
    validate_pair(unsigned, signed)
    return signed


def verify_certificate_report(report, certificate):
    found = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$", report, re.MULTILINE)
    require(len(found) == 1 and found[0].lower() == certificate_digest(certificate), "APK signer does not match the expected release certificate")
    require(re.search(r"^Verified using v2 scheme .*: true$", report, re.MULTILINE) and
            re.search(r"^Verified using v3 scheme .*: true$", report, re.MULTILINE), "APK must verify with both v2 and v3 signatures")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("extract", "apply"):
        child = commands.add_parser(command)
        child.add_argument("unsigned", type=Path)
        child.add_argument("signed" if command == "extract" else "payload", type=Path)
        child.add_argument("output", type=Path)
        child.add_argument("--certificate-sha256", required=True, type=certificate_digest)
    child = commands.add_parser("verify-report")
    child.add_argument("report", type=Path)
    child.add_argument("--certificate-sha256", required=True, type=certificate_digest)
    child = commands.add_parser("check-alignment")
    child.add_argument("apk", type=Path)
    args = parser.parse_args()
    if args.command == "extract":
        payload = extract(args.unsigned.read_bytes(), args.signed.read_bytes(), args.certificate_sha256)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    elif args.command == "apply":
        signed = apply(args.unsigned.read_bytes(), load_payload(args.payload), args.certificate_sha256)
        with args.output.open("xb") as stream:
            stream.write(signed)
    elif args.command == "verify-report":
        verify_certificate_report(args.report.read_text(encoding="utf-8"), args.certificate_sha256)
    else:
        validate_alignment(args.apk.read_bytes())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, EOFError, RuntimeError, struct.error, zipfile.BadZipFile, NotImplementedError) as error:
        sys.exit(f"APK signatures: {error}")
