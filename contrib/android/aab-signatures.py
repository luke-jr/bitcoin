#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
"""Transport JAR signature entries for a canonical Android App Bundle.

Cryptographic verification is performed by android-aab-verify, not this module.
The expected leaf certificate digest and release timestamp come independently
from the release configuration, never from this detached JSON alone.
"""

import argparse
import base64
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import stat
import zipfile

HERE = Path(__file__).resolve().parent
MAX_METADATA = 16 * 1024 * 1024
METADATA = {'META-INF/MANIFEST.MF', 'META-INF/KNOTS.SF'}
BLOCKS = {'META-INF/KNOTS.RSA', 'META-INF/KNOTS.EC', 'META-INF/KNOTS.DSA'}
FIELDS = {'version', 'unsigned_sha256', 'signed_sha256', 'certificate_sha256', 'epoch', 'signature_entries'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def certificate_digest(value):
    value = value.replace(':', '').lower()
    require(re.fullmatch(r'[0-9a-f]{64}', value), 'Expected a SHA-256 certificate digest')
    return value


def entries(data, signed=False):
    require(22 <= len(data) < 0xFFFFFFFF, 'Expected a nonempty ZIP32 bundle')
    result = {}
    names = set()
    safe_name = runpy.run_path(str(HERE / 'aab.py'))['safe_name']
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        require(not archive.comment, 'ZIP comments are unsupported')
        for entry in archive.infolist():
            safe_name(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
            require(entry.filename not in names, 'Duplicate ZIP entry')
            names.add(entry.filename)
            require(not entry.flag_bits & 1, 'Encrypted ZIP entries are unsupported')
            require(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unsupported ZIP compression')
            mode = entry.external_attr >> 16
            require(not stat.S_ISLNK(mode), 'ZIP symlinks are forbidden')
            if entry.is_dir():
                continue
            if entry.filename.upper().startswith('META-INF/'):
                require(signed and entry.filename in METADATA | BLOCKS, 'Unexpected signing metadata')
                require(entry.file_size <= MAX_METADATA, 'Signature metadata exceeds size limit')
            else:
                require(entry.filename == 'BundleConfig.pb' or entry.filename.startswith(('base/', 'BUNDLE-METADATA/')),
                        'Unexpected bundle root entry')
            result[entry.filename] = archive.read(entry)
    require({'BundleConfig.pb', 'base/manifest/AndroidManifest.xml', 'base/resources.pb'} <= result.keys(),
            'Missing base App Bundle structure')
    if signed:
        require(METADATA <= result.keys() and len(BLOCKS & result.keys()) == 1, 'Missing or ambiguous JAR signature entries')
    return result


def canonical(data, epoch):
    timestamp = datetime.datetime.fromtimestamp(max(epoch, 315532800), datetime.timezone.utc)
    require(timestamp.year <= 2107, 'Release timestamp exceeds the ZIP date range')
    date = (timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second & ~1)
    # Unlike ordinary ZIP ordering, JAR streaming verification needs the
    # manifest first. Emit the SF and signature block next, then sorted payload.
    leading = ['META-INF/MANIFEST.MF', 'META-INF/KNOTS.SF'] + sorted(BLOCKS & data.keys())
    order = [name for name in leading if name in data] + sorted(set(data) - set(leading), key=lambda name: name.encode('utf-8'))
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', allowZip64=False) as archive:
        for name in order:
            info = zipfile.ZipInfo(name, date)
            info.create_system = 3
            info.create_version = info.extract_version = 20
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED if name.endswith('.so') else zipfile.ZIP_DEFLATED
            archive.writestr(info, data[name], compresslevel=9)
    return output.getvalue()


def normalize(data, epoch):
    return canonical(entries(data, signed=True), epoch)


def extract(unsigned, signed, certificate, epoch):
    original = entries(unsigned)
    complete = entries(signed, signed=True)
    signatures = {name: value for name, value in complete.items() if name in METADATA | BLOCKS}
    require({name: value for name, value in complete.items() if name not in signatures} == original,
            'Signing changed the bundle payload')
    require(canonical(complete, epoch) == signed, 'Signed bundle is not canonical for this release timestamp')
    return {'version': 1, 'unsigned_sha256': digest(unsigned), 'signed_sha256': digest(signed),
            'certificate_sha256': certificate_digest(certificate), 'epoch': epoch,
            'signature_entries': {name: base64.b64encode(value).decode('ascii') for name, value in sorted(signatures.items())}}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON field')
        result[key] = value
    return result


def load_payload(path):
    require(path.stat().st_size <= MAX_METADATA, 'Detached signature metadata exceeds size limit')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)


def apply(unsigned, payload, certificate, epoch):
    require(isinstance(payload, dict) and set(payload) == FIELDS and type(payload['version']) is int and payload['version'] == 1,
            'Unsupported detached signature payload')
    require(type(payload['epoch']) is int and payload['epoch'] == epoch, 'Release timestamp mismatch')
    require(payload['certificate_sha256'] == certificate_digest(certificate), 'Release certificate mismatch')
    require(payload['unsigned_sha256'] == digest(unsigned), 'Unsigned bundle digest mismatch')
    original = entries(unsigned)
    signatures = payload['signature_entries']
    require(isinstance(signatures, dict) and METADATA <= signatures.keys()
            and len(BLOCKS & signatures.keys()) == 1 and set(signatures) <= METADATA | BLOCKS,
            'Invalid JAR signature entry set')
    decoded = {}
    for name, value in signatures.items():
        require(isinstance(value, str) and len(value) <= MAX_METADATA, 'Invalid signature entry')
        decoded[name] = base64.b64decode(value, validate=True)
    require(sum(map(len, decoded.values())) <= MAX_METADATA, 'Signature metadata exceeds size limit')
    result = canonical(original | decoded, epoch)
    require(payload['signed_sha256'] == digest(result), 'Reconstructed signed bundle digest mismatch')
    return result


def write_new(path, data):
    with path.open('xb') as output:
        output.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    normalizer = commands.add_parser('normalize')
    normalizer.add_argument('source', type=Path)
    normalizer.add_argument('output', type=Path)
    extractor = commands.add_parser('extract')
    extractor.add_argument('unsigned', type=Path)
    extractor.add_argument('signed', type=Path)
    extractor.add_argument('output', type=Path)
    applier = commands.add_parser('apply')
    applier.add_argument('unsigned', type=Path)
    applier.add_argument('payload', type=Path)
    applier.add_argument('output', type=Path)
    for command in (normalizer, extractor, applier):
        command.add_argument('--epoch', type=int, default=os.environ.get('SOURCE_DATE_EPOCH'))
    for command in (extractor, applier):
        command.add_argument('--certificate-sha256', required=True)
    args = parser.parse_args()
    if args.epoch is None:
        parser.error('Set SOURCE_DATE_EPOCH or supply --epoch')
    if args.command == 'normalize':
        write_new(args.output, normalize(args.source.read_bytes(), args.epoch))
    elif args.command == 'extract':
        payload = extract(args.unsigned.read_bytes(), args.signed.read_bytes(), args.certificate_sha256, args.epoch)
        write_new(args.output, (json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n').encode())
    else:
        write_new(args.output, apply(args.unsigned.read_bytes(), load_payload(args.payload), args.certificate_sha256, args.epoch))


if __name__ == '__main__':
    main()
