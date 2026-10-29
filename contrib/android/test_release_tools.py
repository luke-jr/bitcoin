#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Run with python3 contrib/android/test_release_tools.py; no SDK or keys needed.

These test signature transport, not cryptography. Release scripts additionally
verify real APK signatures and the release certificate using apksigner.
"""

import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signatures = load("apk_signatures", "apk-signatures.py")
canonical_zip = load("apk_zip", "zip.py")
framework = load("framework_resources", "build-framework-res.py")
CERTIFICATE = "a1" * 32


def unsigned_apk():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"fixture manifest")
        archive.writestr("classes.dex", b"fixture dex")
    return output.getvalue()


def signed_apk(unsigned, padding=0):
    cd, _ = signatures.zip_sections(unsigned)
    pairs = b"".join(struct.pack("<QI", 8, identifier) + b"test" for identifier in (signatures.V2, signatures.V3))
    size = len(pairs) + 24
    block = struct.pack("<Q", size) + pairs + struct.pack("<Q", size) + signatures.MAGIC
    insertion = b"\0" * padding + block
    result = bytearray(unsigned[:cd] + insertion + unsigned[cd:])
    _, eocd = signatures.zip_sections(unsigned)
    struct.pack_into("<I", result, eocd + len(insertion) + 16, cd + len(insertion))
    return bytes(result)


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.unsigned = unsigned_apk()
        self.signed = signed_apk(self.unsigned, padding=37)
        self.payload = signatures.extract(self.unsigned, self.signed, CERTIFICATE)

    def test_roundtrip_including_padding(self):
        self.assertEqual(signatures.apply(self.unsigned, self.payload, CERTIFICATE), self.signed)
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.json"
            payload.write_text(json.dumps(self.payload), encoding="utf-8")
            self.assertEqual(signatures.load_payload(payload), self.payload)

    def test_unsigned_tampering(self):
        with self.assertRaisesRegex(ValueError, "digest"):
            signatures.apply(self.unsigned.replace(b"fixture dex", b"altered dex"), self.payload, CERTIFICATE)

    def test_payload_tampering_and_wrong_certificate(self):
        payload = dict(self.payload)
        insertion = bytearray(base64.b64decode(payload["insertion_base64"]))
        insertion[0] ^= 1
        payload["insertion_base64"] = base64.b64encode(insertion).decode("ascii")
        with self.assertRaisesRegex(ValueError, "digest"):
            signatures.apply(self.unsigned, payload, CERTIFICATE)
        with self.assertRaisesRegex(ValueError, "certificate"):
            signatures.apply(self.unsigned, self.payload, "b2" * 32)

    def test_modified_signed_entry(self):
        with self.assertRaisesRegex(ValueError, "entry bytes"):
            signatures.extract(self.unsigned, self.signed.replace(b"fixture dex", b"altered dex"), CERTIFICATE)

    def test_modified_central_directory(self):
        cd, _ = signatures.zip_sections(self.signed)
        changed = bytearray(self.signed)
        changed[cd + 12] ^= 1  # DOS time, central directory only.
        with self.assertRaisesRegex(ValueError, "central directory"):
            signatures.extract(self.unsigned, changed, CERTIFICATE)

    def test_modified_eocd_comment(self):
        _, eocd = signatures.zip_sections(self.signed)
        changed = bytearray(self.signed + b"comment")
        struct.pack_into("<H", changed, eocd + 20, 7)
        with self.assertRaisesRegex(ValueError, "EOCD"):
            signatures.extract(self.unsigned, changed, CERTIFICATE)

    def test_nonzero_padding_and_unsupported_block(self):
        cd, _ = signatures.zip_sections(self.unsigned)
        changed = bytearray(self.signed)
        changed[cd] = 1
        with self.assertRaisesRegex(ValueError, "padding"):
            signatures.extract(self.unsigned, changed, CERTIFICATE)
        changed = bytearray(self.signed)
        struct.pack_into("<I", changed, cd + 37 + 16, 0x12345678)
        with self.assertRaisesRegex(ValueError, "block ID"):
            signatures.extract(self.unsigned, changed, CERTIFICATE)

    def test_resigning_rejected(self):
        with self.assertRaises(ValueError):
            signatures.extract(self.signed, signed_apk(self.signed), CERTIFICATE)

    def test_zip64_and_v1_rejected(self):
        _, eocd = signatures.zip_sections(self.unsigned)
        changed = bytearray(self.unsigned)
        struct.pack_into("<I", changed, eocd + 16, 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, "ZIP64"):
            signatures.zip_sections(changed)
        output = io.BytesIO(self.unsigned)
        with zipfile.ZipFile(output, "a") as archive:
            archive.writestr("META-INF/CERT.SF", "v1")
        with self.assertRaisesRegex(ValueError, "v1"):
            signatures.zip_sections(output.getvalue())

    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.json"
            payload.write_text('{"version": 1, "version": 1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
                signatures.load_payload(payload)

    def test_verifier_report(self):
        report = ("Verified using v2 scheme (APK Signature Scheme v2): true\n"
                  "Verified using v3 scheme (APK Signature Scheme v3): true\n"
                  f"Signer #1 certificate SHA-256 digest: {CERTIFICATE}\n")
        signatures.verify_certificate_report(report, CERTIFICATE)
        for invalid in (report.replace(CERTIFICATE, "b2" * 32), report.replace("true", "false"),
                        report + f"Signer #2 certificate SHA-256 digest: {CERTIFICATE}\n"):
            with self.assertRaises(ValueError):
                signatures.verify_certificate_report(invalid, CERTIFICATE)


class ZipTests(unittest.TestCase):
    def test_apk_alignment_preserves_contents_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "lib/arm64-v8a").mkdir(parents=True)
            contents = {
                "AndroidManifest.xml": b"fixture manifest",
                "resources.arsc": b"fixture resources",
                "lib/arm64-v8a/lib\u00e9.so": b"fixture native library",
            }
            for name, data in contents.items():
                (source / name).write_bytes(data)
            canonical_zip.build_archive(source, root / "unaligned.apk", 1700000000)
            with self.assertRaisesRegex(ValueError, "aligned"):
                signatures.validate_alignment((root / "unaligned.apk").read_bytes())
            for number in (1, 2):
                canonical_zip.build_archive(source, root / f"aligned-{number}.apk", 1700000000, apk=True)
            aligned = (root / "aligned-1.apk").read_bytes()
            self.assertEqual(aligned, (root / "aligned-2.apk").read_bytes())
            signatures.validate_alignment(aligned)
            with zipfile.ZipFile(io.BytesIO(aligned)) as archive:
                for name, data in contents.items():
                    self.assertEqual(archive.read(name), data)
            # Signature insertion must preserve this alignment exactly.
            signed = signed_apk(aligned)
            payload = signatures.extract(aligned, signed, CERTIFICATE)
            reconstructed = signatures.apply(aligned, payload, CERTIFICATE)
            signatures.validate_alignment(reconstructed)

    def test_reproducible_despite_input_metadata_and_creation_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ("AndroidManifest.xml", "lib/arm64-v8a/libbitcoin.so", "resources.arsc", "assets/\u00e9.txt")
            outputs = []
            for number in range(2):
                source = root / str(number)
                source.mkdir()
                for name in names[::1 if number == 0 else -1]:
                    path = source / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((name * 20).encode("utf-8"))
                    path.chmod(0o600 if number == 0 else 0o755)
                    os.utime(path, (123456789 + number, 987654321 + number))
                output = root / f"{number}.apk"
                canonical_zip.build_archive(source, output, 1700000001)
                outputs.append(output.read_bytes())
            self.assertEqual(*outputs)
            with zipfile.ZipFile(io.BytesIO(outputs[0])) as archive:
                self.assertEqual(archive.namelist(), sorted(names, key=lambda name: name.encode("utf-8")))
                for entry in archive.infolist():
                    self.assertEqual(entry.external_attr >> 16, stat.S_IFREG | 0o644)
                    self.assertEqual(entry.date_time[-1] % 2, 0)
                    self.assertEqual(entry.extra, b"")
                    self.assertEqual(entry.comment, b"")
                self.assertEqual(archive.getinfo(names[1]).compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.getinfo("resources.arsc").compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.getinfo(names[0]).compress_type, zipfile.ZIP_DEFLATED)

    def test_symlinks_and_output_in_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "link").symlink_to(root)
            with self.assertRaisesRegex(ValueError, "regular files"):
                canonical_zip.build_archive(source, root / "output.apk", 0)
            (source / "link").unlink()
            with self.assertRaisesRegex(ValueError, "outside"):
                canonical_zip.build_archive(source, source / "output.apk", 0)

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            output = root / "output.apk"
            output.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                canonical_zip.build_archive(source, output, 0)
            self.assertEqual(output.read_bytes(), b"existing")


class FrameworkResourceTests(unittest.TestCase):
    def test_public_ids_use_final_declarations_and_reject_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "public.xml"
            path.write_text('<resources><public type="attr" name="mode" id="0x01010001"/>'
                            '<staging-public-group-final type="attr" first-id="0x01ff0000">'
                            '<public name="mode"/></staging-public-group-final></resources>')
            self.assertEqual(framework.public_resources(path), [(0x01010001, "attr", "mode")])
            path.write_text('<resources><public type="attr" name="mode" id="0x01010001"/>'
                            '<public type="attr" name="other" id="0x01010001"/></resources>')
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                framework.public_resources(path)

    def test_formats_ranges_symbols_and_empty_style_parents_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attrs = root / "attrs.xml"
            attrs.write_text('<resources><declare-styleable name="Example">'
                             '<attr name="mode" format="integer" min="1">'
                             '<enum name="one" value="1"/></attr></declare-styleable>'
                             '<attr name="mode"/></resources>')
            definitions = framework.attributes([attrs])
            output = root / "generated"
            framework.write_inputs([(0x01010001, "attr", "mode"),
                                    (0x01030001, "style", "Example.MissingParent")], definitions, output)
            generated = ET.parse(output / "res/values/framework.xml").getroot()
            self.assertEqual(generated.find("attr").attrib, {"name": "mode", "format": "integer", "min": "1"})
            self.assertEqual(generated.find("attr/enum").attrib, {"name": "one", "value": "1"})
            self.assertEqual(generated.find("style").get("parent"), "")
            attrs.write_text('<resources><attr name="mode"><enum name="one" value="1"/></attr>'
                             '<attr name="mode"><enum name="one" value="2"/></attr></resources>')
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                framework.attributes([attrs])

    def test_compiled_id_validation_rejects_changes_missing_and_extra_entries(self):
        public = [(0x01010001, "attr", "mode")]
        valid = "    resource 0x01010001 attr/mode PUBLIC\n"
        framework.verify_dump(public, valid)
        for text in ("", valid.replace("01010001", "01010002"), valid + valid):
            with self.assertRaisesRegex(ValueError, "differ"):
                framework.verify_dump(public, text)


if __name__ == "__main__":
    unittest.main()
