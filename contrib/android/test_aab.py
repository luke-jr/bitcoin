#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
"""AAB assembly and real JAR signature tests; Java tests need a JDK on PATH/JAVA_HOME.

No Android SDK or bundletool is required. Integration with those tools is a
separate development oracle, not a dependency of the release helpers.
"""

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import shlex
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
EPOCH = 1700000000


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assembler = load('aab_assembler', 'aab.py')
signatures = load('aab_signatures', 'aab-signatures.py')


def archive(entries):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as output:
        for name, data in entries.items():
            output.writestr(name, data)
    return result.getvalue()


def unsigned():
    return archive({'BundleConfig.pb': b'config fixture',
                    'base/manifest/AndroidManifest.xml': b'manifest fixture',
                    'base/resources.pb': b'resource fixture',
                    'base/dex/classes.dex': b'dex fixture'})


def extracted_production_kit(destination):
    """Copy exactly the helpers selected by the release's kit assembly command.

    Reading the actual command avoids a second independently maintained file
    list that could conceal a missing transitive dependency in release kits.
    """
    script = HERE.parent / 'guix/libexec/build-android.sh'
    lines = iter(script.read_text(encoding='utf-8').splitlines())
    for line in lines:
        if line.strip().startswith('cp --target-directory=codesigning '):
            command = line.strip()
            while command.endswith('\\'):
                command = command[:-1] + next(lines).strip()
            arguments = shlex.split(command)
            break
    else:
        raise AssertionError('Production signing kit copy command missing')
    destination.mkdir()
    for source in arguments[2:]:
        path = HERE.parents[1] / source
        if path.parent != HERE or not path.is_file():
            raise AssertionError(f'Unexpected kit helper input: {source}')
        shutil.copyfile(path, destination / path.name)


def elf():
    data = bytearray(128)
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 16, 3)
    struct.pack_into('<H', data, 18, 183)
    struct.pack_into('<I', data, 20, 1)
    struct.pack_into('<Q', data, 32, 64)
    struct.pack_into('<HHH', data, 52, 64, 56, 1)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 0, 0, 0, 128, 128, 16384)
    return data


class AssemblyTests(unittest.TestCase):
    def test_extracted_kit_python_helper_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            kit = Path(directory) / 'kit'
            extracted_production_kit(kit)
            (kit / 'unsigned.aab').write_bytes(unsigned())
            values = signatures.entries(unsigned())
            values.update({'META-INF/MANIFEST.MF': b'manifest fixture',
                           'META-INF/KNOTS.SF': b'signature fixture',
                           'META-INF/KNOTS.RSA': b'block fixture'})
            (kit / 'raw.aab').write_bytes(archive(values))
            env = dict(os.environ, SOURCE_DATE_EPOCH=str(EPOCH))
            for arguments in (
                ('normalize', 'raw.aab', 'signed.aab'),
                ('extract', 'unsigned.aab', 'signed.aab', 'signature.json', '--certificate-sha256', 'a1' * 32),
                ('apply', 'unsigned.aab', 'signature.json', 'reconstructed.aab', '--certificate-sha256', 'a1' * 32),
            ):
                subprocess.run([sys.executable, str(kit / 'aab-signatures.py'), *arguments],
                               cwd=kit, env=env, check=True, capture_output=True)
            self.assertEqual((kit / 'signed.aab').read_bytes(), (kit / 'reconstructed.aab').read_bytes())
            # APK's standalone CLI must also load with only the packaged files.
            subprocess.run([sys.executable, str(kit / 'apk-signatures.py'), '--help'],
                           cwd=kit, check=True, capture_output=True)
            # Reproduce the original incomplete-kit defect and prove no source
            # tree fallback can hide the missing transitive helper.
            (kit / 'aab.py').unlink()
            result = subprocess.run([sys.executable, str(kit / 'aab-signatures.py'),
                                     'normalize', 'raw.aab', 'must-not-exist.aab'],
                                    cwd=kit, env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'aab.py', result.stderr)
            self.assertFalse((kit / 'must-not-exist.aab').exists())

    def test_reproducible_layout_and_no_compiler_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = root / 'resources.zip'
            resources.write_bytes(archive({'AndroidManifest.xml': b'proto fixture', 'resources.pb': b'proto resources',
                                          'res/xml/config.xml': b'proto XML'}))
            dex, native, assets = (root / name for name in ('dex', 'native', 'assets'))
            for path in (dex, native, assets):
                path.mkdir()
            dex_data = bytearray(112)
            dex_data[:8] = b'dex\n039\0'
            struct.pack_into('<III', dex_data, 32, len(dex_data), 112, 0x12345678)
            dex_data[12:32] = hashlib.sha1(dex_data[32:]).digest()
            struct.pack_into('<I', dex_data, 8, zlib.adler32(dex_data[12:]) & 0xffffffff)
            (dex / 'classes.dex').write_bytes(dex_data)
            (native / 'libfixture.so').write_bytes(elf())
            (assets / 'data.rcc').write_bytes(b'asset fixture')
            first, second = root / 'one.aab', root / 'two.aab'
            assembler.assemble(resources, dex, native, assets, first, EPOCH)
            for path in (dex / 'classes.dex', native / 'libfixture.so', assets / 'data.rcc'):
                path.chmod(0o600)
                os.utime(path, (1, 1))
            assembler.assemble(resources, dex, native, assets, second, EPOCH)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as result:
                self.assertIn('base/native.pb', result.namelist())
                self.assertIn('base/assets.pb', result.namelist())
                self.assertIn('base/dex/classes.dex', result.namelist())
                self.assertFalse(any(name.endswith(('.jar', '.apk')) for name in result.namelist()))
            with zipfile.ZipFile(resources, 'a') as result:
                result.writestr('android.jar', b'compiler-only input')
            with self.assertRaisesRegex(ValueError, 'Unexpected resource'):
                assembler.assemble(resources, dex, native, assets, root / 'bad.aab', EPOCH)

    def test_archive_paths_and_duplicate_payload_fields(self):
        for name in ('../escape', '/absolute', 'base/../escape', 'res//file', 'a\\b'):
            with self.assertRaises(ValueError):
                assembler.safe_name(name)
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / 'duplicate.json'
            payload.write_text('{"version":1,"version":1}')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
                signatures.load_payload(payload)


def jdk_tool(name):
    if os.environ.get('JAVA_HOME'):
        path = Path(os.environ['JAVA_HOME']) / 'bin' / name
        return str(path) if path.is_file() else None
    return shutil.which(name)


@unittest.skipUnless(all(jdk_tool(name) for name in ('java', 'javac', 'keytool', 'jarsigner')), 'JDK tools unavailable')
class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='aab-signature-tests-')
        cls.root = Path(cls.temporary.name)
        cls.classes = cls.root / 'classes'
        cls.run_tool('javac', '--release', '17', '-d', cls.classes, HERE / 'aab-verify.java')
        cls.unsigned = unsigned()
        (cls.root / 'unsigned.aab').write_bytes(cls.unsigned)
        cls.keys = {}
        for algorithm in ('RSA', 'EC'):
            store = cls.root / (algorithm + '.p12')
            options = ('-keysize', '2048') if algorithm == 'RSA' else ('-groupname', 'secp256r1')
            cls.run_tool('keytool', '-genkeypair', '-noprompt', '-keystore', store,
                         '-storepass', 'fixture-password', '-alias', 'fixture', '-keyalg', algorithm,
                         *options, '-dname', 'CN=AAB fixture', '-validity', '36500')
            certificate = cls.root / (algorithm + '.der')
            cls.run_tool('keytool', '-exportcert', '-keystore', store, '-storepass', 'fixture-password',
                         '-alias', 'fixture', '-file', certificate)
            signed = cls.root / (algorithm + '.aab')
            cls.run_tool('jarsigner', '-keystore', store, '-storepass', 'fixture-password', '-sigfile', 'KNOTS',
                         '-digestalg', 'SHA-256', '-signedjar', signed, cls.root / 'unsigned.aab', 'fixture')
            pin = hashlib.sha256(certificate.read_bytes()).hexdigest()
            cls.keys[algorithm] = (signatures.normalize(signed.read_bytes(), EPOCH), pin)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def run_tool(name, *args):
        return subprocess.run([jdk_tool(name), *map(str, args)], check=True, capture_output=True)

    def verify(self, data, pin, success=True):
        source = self.root / 'verify.aab'
        source.write_bytes(data)
        result = subprocess.run([jdk_tool('java'), '-cp', str(self.classes), 'AabVerifier', str(source), pin],
                                capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode(errors='replace'))

    def test_rsa_ec_transport_and_manifest_first(self):
        for signed, pin in self.keys.values():
            payload = signatures.extract(self.unsigned, signed, pin, EPOCH)
            reconstructed = signatures.apply(self.unsigned, payload, pin, EPOCH)
            self.assertEqual(signed, reconstructed)
            self.verify(reconstructed, pin)
            with zipfile.ZipFile(io.BytesIO(reconstructed)) as result:
                self.assertEqual(result.namelist()[0], 'META-INF/MANIFEST.MF')

    def test_reject_payload_and_signature_tampering(self):
        signed, pin = self.keys['RSA']
        values = signatures.entries(signed, signed=True)
        values['base/resources.pb'] = b'tampered resources'
        self.verify(signatures.canonical(values, EPOCH), pin, success=False)
        payload = signatures.extract(self.unsigned, signed, pin, EPOCH)
        for changed_unsigned, changed_pin, changed_epoch in ((self.unsigned + b'x', pin, EPOCH),
                                                            (self.unsigned, '00' * 32, EPOCH),
                                                            (self.unsigned, pin, EPOCH + 2)):
            with self.assertRaises(ValueError):
                signatures.apply(changed_unsigned, payload, changed_pin, changed_epoch)
        changed = copy.deepcopy(payload)
        changed['signature_entries']['META-INF/KNOTS.SF'] = 'dGFtcGVyZWQ='
        with self.assertRaisesRegex(ValueError, 'digest'):
            signatures.apply(self.unsigned, changed, pin, EPOCH)

    def test_reject_unsigned_entries_including_meta_inf(self):
        signed, pin = self.keys['RSA']
        for name in ('base/extra.txt', 'META-INF/NOTICE'):
            values = signatures.entries(signed, signed=True)
            values[name] = b'unsigned addition'
            self.verify(signatures.canonical(values, EPOCH), pin, success=False)
        self.verify(signed, '00' * 32, success=False)
        self.verify(self.unsigned, pin, success=False)

    def test_duplicate_zip_names_and_multiple_signature_blocks(self):
        signed, pin = self.keys['RSA']
        output = io.BytesIO(signed)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(output, 'a') as result:
                result.writestr('BundleConfig.pb', b'duplicate')
        self.verify(output.getvalue(), pin, success=False)
        with self.assertRaisesRegex(ValueError, 'Duplicate ZIP'):
            signatures.entries(output.getvalue(), signed=True)
        values = signatures.entries(signed, signed=True)
        values['META-INF/KNOTS.EC'] = b'additional block'
        self.verify(signatures.canonical(values, EPOCH), pin, success=False)

    def test_apply_does_not_publish_forged_detached_signature(self):
        signed, pin = self.keys['RSA']
        payload = signatures.extract(self.unsigned, signed, pin, EPOCH)
        payload['signature_entries']['META-INF/KNOTS.SF'] = 'dGFtcGVyZWQ='
        values = signatures.entries(signed, signed=True)
        values['META-INF/KNOTS.SF'] = b'tampered'
        payload['signed_sha256'] = signatures.digest(signatures.canonical(values, EPOCH))
        path = self.root / 'forged.json'
        path.write_text(json.dumps(payload))
        output = self.root / 'must-not-exist.aab'
        verifier = self.root / 'verifier.sh'
        verifier.write_text('#!/usr/bin/env bash\nexec ' + shlex.quote(jdk_tool('java')) + ' -cp ' + shlex.quote(str(self.classes)) + ' AabVerifier "$@"\n')
        verifier.chmod(0o755)
        environment = dict(os.environ, SOURCE_DATE_EPOCH=str(EPOCH), AAB_VERIFIER=str(verifier))
        result = subprocess.run([str(HERE / 'aab-apply-sigs.sh'), str(self.root / 'unsigned.aab'), str(path), str(output), pin],
                                env=environment, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_extracted_kit_real_detached_signing_roundtrip(self):
        kit = self.root / 'extracted-kit'
        extracted_production_kit(kit)
        (kit / 'unsigned').mkdir()
        source = kit / 'unsigned/fixture.aab'
        source.write_bytes(self.unsigned)
        verifier = self.root / 'kit-verifier.sh'
        verifier.write_text('#!/usr/bin/env bash\nexec ' + shlex.quote(jdk_tool('java'))
                            + ' -cp ' + shlex.quote(str(self.classes)) + ' AabVerifier "$@"\n')
        verifier.chmod(0o755)
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(EPOCH), HOST='aarch64-linux-android',
                   AAB_VERIFIER=str(verifier), JARSIGNER=jdk_tool('jarsigner'),
                   PYTHON=sys.executable, KNOTS_ANDROID_KEYSTORE_PASSWORD='fixture-password')
        env.pop('TAR_OPTIONS', None)
        env.pop('KNOTS_ANDROID_KEY_PASSWORD', None)
        pin = self.keys['RSA'][1]
        subprocess.run(['bash', str(kit / 'aab-detached-sig-create.sh'),
                        str(self.root / 'RSA.p12'), 'fixture', pin],
                       cwd=kit, env=env, check=True, capture_output=True)
        signature_tar = kit / 'signature-android-aab-aarch64-linux-android.tar.gz'
        with tarfile.open(signature_tar) as archive:
            name = 'android/aarch64-linux-android/fixture.aab.json'
            payload = kit / 'fixture.json'
            payload.write_bytes(archive.extractfile(name).read())
        output = kit / 'reconstructed.aab'
        subprocess.run(['bash', str(kit / 'aab-apply-sigs.sh'), str(source),
                        str(payload), str(output), pin], cwd=kit, env=env,
                       check=True, capture_output=True)
        # JAR signing metadata may contain a new signing time. Reapplication
        # must reproduce this signing session's exact recorded output digest.
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(),
                         json.loads(payload.read_text())['signed_sha256'])
        self.verify(output.read_bytes(), pin)


if __name__ == '__main__':
    unittest.main()
