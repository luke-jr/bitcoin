#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
"""Assemble the staged Qt application using source-built Android tools."""

import argparse
import os
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ANDROID = '{http://schemas.android.com/apk/res/android}'
HERE = Path(__file__).resolve().parent


def invoke(*arguments):
    subprocess.run([str(arg) for arg in arguments], check=True)


def extract_resources(source, destination):
    with zipfile.ZipFile(source) as archive:
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in entry.filename:
                raise ValueError(f'Invalid compiled resource entry: {entry.filename}')
            if entry.is_dir():
                continue
            if not (entry.filename in ('AndroidManifest.xml', 'resources.arsc') or name.parts[0] == 'res'):
                raise ValueError(f'Unexpected compiled resource entry: {entry.filename}')
            output = destination / entry.filename
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as input_stream, output.open('xb') as output_stream:
                shutil.copyfileobj(input_stream, output_stream)


def copy_notices(jars, directories, destination):
    destination.mkdir(parents=True)
    shutil.copyfile(HERE.parents[1] / 'COPYING', destination / 'Bitcoin-Knots-COPYING')
    for directory in directories:
        shutil.copytree(directory, destination / directory.name)
    for jar in jars:
        with zipfile.ZipFile(jar) as archive:
            for entry in archive.infolist():
                path = PurePosixPath(entry.filename)
                if (entry.is_dir() or path.is_absolute() or '..' in path.parts
                        or not path.parts or path.parts[0] != 'META-INF'):
                    continue
                if not any(word in path.name.upper() for word in ('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')):
                    continue
                output = destination / jar.stem / Path(*path.parts[1:])
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, output.open('xb') as target:
                    shutil.copyfileobj(source, target)


def package(args):
    if args.output.exists() or args.output.is_symlink():
        raise ValueError('Output already exists')
    for dependency in (args.android_jar, args.lambda_stubs,
                       args.framework_resources, args.fileprovider):
        if not dependency.is_file():
            raise ValueError(f'Missing source-built packaging dependency: {dependency}')
    for name in ('QtActivity', 'QtApplication', 'QtService'):
        launcher = args.qt_java_source / f'org/qtproject/qt/android/bindings/{name}.java'
        if not launcher.is_file():
            raise ValueError(f'Missing Qt launcher Java source: {launcher}')
    qt_resources = args.qt_java_source.parent / 'res'
    if not (qt_resources / 'xml/qtprovider_paths.xml').is_file():
        raise ValueError('Missing Qt Android Java resources')
    if any(not directory.is_dir() for directory in args.license_directory):
        raise ValueError('Missing dependency license directory')
    args.work.mkdir(parents=True, exist_ok=False)
    manifest = (args.stage / 'AndroidManifest.xml').read_text(encoding='utf-8')
    tree = ET.fromstring(manifest)
    package_name = tree.get('package')
    if package_name != 'org.bitcoinknots.qt':
        raise ValueError('Expected the Bitcoin Knots GUI package')
    manifest = manifest.replace('${applicationId}', package_name)
    if '${' in manifest or '%%INSERT_' in manifest:
        raise ValueError('Unresolved Android manifest placeholder')
    application = tree.find('application')
    if application is None or application.get(ANDROID + 'debuggable', 'false') != 'false':
        raise ValueError('Expected a non-debuggable application')
    activity = application.find('activity')
    if activity is None or activity.get(ANDROID + 'name') != package_name + '.KnotsActivity':
        raise ValueError('Expected the release activity that filters launch configuration')
    manifest_path = args.work / 'AndroidManifest.xml'
    manifest_path.write_text(manifest, encoding='utf-8')

    compiled = args.work / 'compiled-resources.zip'
    compiled_qt = args.work / 'compiled-qt-resources.zip'
    resources = args.work / 'resources.apk'
    generated_java = args.work / 'generated-java'
    resource_ids = args.work / 'resource-ids.txt'
    invoke(args.aapt2, 'compile', '--dir', args.stage / 'res', '-o', compiled)
    # Qt 6.12 keeps the binding strings and FileProvider paths alongside its
    # launcher sources. Gradle normally adds this separate resource directory.
    invoke(args.aapt2, 'compile', '--dir', qt_resources, '-o', compiled_qt)
    invoke(args.aapt2, 'link', '-o', resources, '-I', args.framework_resources,
           '--manifest', manifest_path, '--min-sdk-version', '28', '--target-sdk-version', '36',
           '--compile-sdk-version-code', '36', '--compile-sdk-version-name', '16',
           '--emit-ids', resource_ids, '--java', generated_java, compiled_qt, compiled)
    # The AAB uses the same IDs as the APK but protobuf resources. Source paths
    # are build metadata and must not enter the reproducible upload artifact.
    invoke(args.aapt2, 'link', '-o', args.work / 'resources-proto.apk',
           '-I', args.framework_resources, '--manifest', manifest_path,
           '--min-sdk-version', '28', '--target-sdk-version', '36',
           '--compile-sdk-version-code', '36', '--compile-sdk-version-name', '16',
           '--proto-format', '--exclude-sources', '--stable-ids', resource_ids, compiled_qt, compiled)

    jars = sorted((args.stage / 'libs').glob('*.jar')) + [args.fileprovider]
    if not jars or any(not jar.is_file() for jar in jars):
        raise ValueError('Missing staged Java dependencies')
    # Qt's Gradle template normally references these launcher sources directly
    # from the Qt installation. They are separate from Qt6Android.jar.
    sources = (sorted((args.stage / 'src').rglob('*.java'))
               + sorted(args.qt_java_source.rglob('*.java'))
               + sorted(generated_java.rglob('*.java')))
    if not sources:
        raise ValueError('Missing application Java sources')
    for name in ('ConfigEditor', 'DeviceConditions', 'KnotsActivity'):
        if not (args.stage / f'src/org/bitcoinknots/qt/{name}.java').is_file():
            raise ValueError(f'Missing application Java source: {name}')
    classes = args.work / 'classes'
    invoke(args.javac, '-source', '8', '-target', '8', '-encoding', 'UTF-8',
           '-bootclasspath', os.pathsep.join(map(str, (args.android_jar, args.lambda_stubs))),
           '-classpath', os.pathsep.join(map(str, jars)), '-d', classes, *sources)
    dex = args.work / 'dex'
    dex.mkdir()
    invoke(args.d8, '--release', '--min-api', '28', '--lib', args.android_jar,
           '--lib', args.lambda_stubs, '--output', dex, *jars, *sorted(classes.rglob('*.class')))

    payload = args.work / 'apk'
    payload.mkdir()
    extract_resources(resources, payload)
    dex_files = sorted(dex.glob('classes*.dex'))
    if not dex_files:
        raise ValueError('DEX compilation produced no program')
    for file in dex_files:
        shutil.copyfile(file, payload / file.name)
    native = args.stage / 'libs/arm64-v8a'
    libraries = sorted(native.glob('*.so'))
    if not libraries or not (native / 'libbitcoin-qt_arm64-v8a.so').is_file():
        raise ValueError('Missing the native GUI or its dependencies')
    system_libraries = {
        'libc.so', 'libm.so', 'libdl.so', 'liblog.so', 'libandroid.so',
        'libEGL.so', 'libGLESv1_CM.so', 'libGLESv2.so', 'libGLESv3.so',
        'libjnigraphics.so', 'libnativewindow.so', 'libvulkan.so',
    }
    if any(library.name in system_libraries for library in libraries):
        raise ValueError('Android system libraries and linking stubs must not enter the APK')
    (payload / 'lib/arm64-v8a').mkdir(parents=True)
    for library in libraries:
        shutil.copyfile(library, payload / 'lib/arm64-v8a' / library.name)
    if (args.stage / 'assets').exists():
        shutil.copytree(args.stage / 'assets', payload / 'assets')
    copy_notices(jars, args.license_directory, payload / 'assets/licenses')
    build_archive = runpy.run_path(str(HERE / 'zip.py'))['build_archive']
    build_archive(payload, args.output, args.epoch, apk=True)
    verify = runpy.run_path(str(HERE / 'verify.py'))['verify']
    try:
        verify(args.output, check_security=True)
    except Exception:
        args.output.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stage', 'work', 'output', 'android-jar', 'lambda-stubs', 'framework-resources', 'fileprovider', 'qt-java-source'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--epoch', type=int, default=os.environ.get('SOURCE_DATE_EPOCH'))
    parser.add_argument('--aapt2', default='aapt2')
    parser.add_argument('--d8', default='d8')
    parser.add_argument('--javac', default='javac')
    parser.add_argument('--license-directory', action='append', type=Path, default=[])
    args = parser.parse_args()
    if args.epoch is None:
        parser.error('Set SOURCE_DATE_EPOCH or supply --epoch')
    # Keep every compiler path stable, including when called from a different cwd.
    for name in ('stage', 'work', 'output', 'android_jar', 'lambda_stubs', 'framework_resources', 'fileprovider', 'qt_java_source'):
        path = getattr(args, name)
        setattr(args, name, path.absolute() if name in ('work', 'output') else path.resolve())
    package(args)


if __name__ == '__main__':
    main()
