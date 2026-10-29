#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
"""Assemble a single-arm64 base Android App Bundle without bundletool.

The resource ZIP must come from source-built AAPT2 link --proto-format. Neither
android.jar nor framework-res.apk belong in the bundle. Only the small protobuf
messages below are generated here. Their field numbers and enum values are from
Google bundletool 1.18.3, commit 586a43a450712a1067f3d92cf7574dee68226302:
https://github.com/google/bundletool/tree/586a43a450712a1067f3d92cf7574dee68226302/src/main/proto
config.proto, files.proto, targeting.proto. The version field selects those
format semantics; this assembler does not execute or embed bundletool.
"""

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import shutil
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def message(field, value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    return varint(field * 8 + 2) + varint(len(value)) + value


def integer(field, value):
    return varint(field * 8) + varint(value)


def bundle_config():
    # BundleConfig.bundletool.version; Optimizations.uncompress_native_libraries
    # (enabled=true, alignment=PAGE_ALIGNMENT_16K); Compression.uncompressed_glob.
    return (message(1, message(2, '1.18.3'))
            + message(2, message(2, integer(1, 1) + integer(2, 2)))
            + message(3, message(1, 'assets/**')))


def native_config():
    # NativeLibraries.directory: path, targeting.abi.alias=ARM64_V8A.
    return message(1, message(1, 'lib/arm64-v8a') + message(2, message(1, integer(1, 3))))


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '\\' in name or '\x00' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError(f'Invalid bundle entry: {name!r}')
    return path


def copy_regular(source, destination):
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'Expected a regular file: {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as input_stream, destination.open('xb') as output_stream:
        shutil.copyfileobj(input_stream, output_stream)


def assemble(resources, dex, native_libraries, assets, output, epoch):
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists')
    with tempfile.TemporaryDirectory(prefix='knots-aab-') as directory:
        root = Path(directory)
        base = root / 'base'
        seen = set()
        with zipfile.ZipFile(resources) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                name = safe_name(entry.filename)
                if entry.filename in seen:
                    raise ValueError('Duplicate compiled resource entry')
                seen.add(entry.filename)
                if entry.filename == 'AndroidManifest.xml':
                    target = base / 'manifest/AndroidManifest.xml'
                elif entry.filename == 'resources.pb' or name.parts[0] == 'res':
                    target = base / entry.filename
                else:
                    raise ValueError(f'Unexpected resource input: {entry.filename}')
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as input_stream, target.open('xb') as output_stream:
                    shutil.copyfileobj(input_stream, output_stream)
        if not {'AndroidManifest.xml', 'resources.pb'} <= seen:
            raise ValueError('Expected AAPT2 protobuf manifest and resources.pb')
        dex_files = sorted(dex.iterdir())
        if not dex_files or {file.name for file in dex_files} != {
                'classes.dex' if index == 1 else f'classes{index}.dex'
                for index in range(1, len(dex_files) + 1)}:
            raise ValueError('Expected contiguous classes.dex, classes2.dex, ...')
        for file in dex_files:
            copy_regular(file, base / 'dex' / file.name)
        libraries = sorted(native_libraries.iterdir())
        if not libraries or any(not re.fullmatch(r'lib[^/]+\.so', file.name) for file in libraries):
            raise ValueError('Expected only native lib*.so files in the arm64 directory')
        for file in libraries:
            copy_regular(file, base / 'lib/arm64-v8a' / file.name)
        if assets is not None:
            if assets.is_symlink() or not assets.is_dir():
                raise ValueError('Assets must be a directory')
            asset_directories = set()
            for directory, directories, filenames in os.walk(assets, followlinks=False):
                for name in directories:
                    if (Path(directory) / name).is_symlink():
                        raise ValueError('Asset symlinks are forbidden')
                for name in filenames:
                    file = Path(directory) / name
                    relative = file.relative_to(assets).as_posix()
                    safe_name(relative)
                    if any('#' in part for part in PurePosixPath(relative).parts[:-1]):
                        raise ValueError('Targeted asset directories are unsupported')
                    copy_regular(file, base / 'assets' / relative)
                    asset_directories.add((PurePosixPath('assets') / relative).parent.as_posix())
            if asset_directories:
                (base / 'assets.pb').write_bytes(b''.join(
                    message(1, message(1, path) + message(2, b''))
                    for path in sorted(asset_directories)))
        (root / 'BundleConfig.pb').write_bytes(bundle_config())
        (base / 'native.pb').write_bytes(native_config())
        writer = runpy.run_path(str(HERE / 'zip.py'))['build_archive']
        writer(root, output, epoch)
    try:
        runpy.run_path(str(HERE / 'verify.py'))['verify'](output)
    except BaseException:
        output.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('resources', 'dex', 'native-libraries', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--epoch', type=int, default=os.environ.get('SOURCE_DATE_EPOCH'))
    args = parser.parse_args()
    if args.epoch is None:
        parser.error('Set SOURCE_DATE_EPOCH or supply --epoch')
    assemble(args.resources, args.dex, args.native_libraries, args.assets, args.output, args.epoch)


if __name__ == '__main__':
    main()
