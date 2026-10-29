#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Build compile-time Android framework resources from AOSP XML source.

Public IDs and attribute formats/enum values are preserved. Other resource
values are placeholders: this SDK archive is an AAPT include and must never be
packaged as application resources or installed on an Android device.
"""

import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile


VALUE_DEFAULTS = {"string": "", "bool": "false", "integer": "0", "color": "#00000000", "dimen": "0dp"}
REFERENCE_TYPES = {"drawable", "layout", "interpolator", "anim", "transition", "animator", "raw", "mipmap", "xml", "font"}


def public_resources(path):
    # Nested staging-public-group-final elements describe historical aliases,
    # including removed symbols. Canonical released IDs are direct public nodes.
    entries = []
    names, ids = set(), set()
    for item in ET.parse(path).getroot().findall("public"):
        kind, name, identifier = item.get("type"), item.get("name"), int(item.get("id"), 16)
        if not kind or not name or identifier >> 24 != 1:
            raise ValueError("Invalid Android public resource declaration")
        if (kind, name) in names or identifier in ids:
            raise ValueError("Duplicate public resource name or ID")
        names.add((kind, name))
        ids.add(identifier)
        entries.append((identifier, kind, name))
    if not entries:
        raise ValueError("No public resources found")
    return sorted(entries)


def attributes(paths):
    result = {}
    for path in paths:
        for declaration in ET.parse(path).getroot().iter("attr"):
            name = declaration.get("name")
            if not name or ":" in name:
                continue
            formats, properties, symbols = result.setdefault(name, (set(), {}, {}))
            formats.update(filter(None, declaration.get("format", "").split("|")))
            for key, value in declaration.attrib.items():
                if key in ("name", "format"):
                    continue
                if key in properties and properties[key] != value:
                    raise ValueError(f"Conflicting attribute property: {name}/{key}")
                properties[key] = value
            for child in declaration:
                if child.tag not in ("enum", "flag"):
                    continue
                key = child.get("name")
                if not key or child.get("value") is None:
                    raise ValueError(f"Invalid attribute symbol: {name}")
                if key in symbols and (symbols[key].tag != child.tag or symbols[key].attrib != child.attrib):
                    raise ValueError(f"Conflicting attribute symbol: {name}/{key}")
                symbols[key] = copy.deepcopy(child)
    return result


def write_inputs(public, definitions, directory):
    values = directory / "res/values"
    values.mkdir(parents=True)
    root = ET.Element("resources")
    for identifier, kind, name in public:
        if kind == "attr":
            if name not in definitions:
                raise ValueError(f"Public attribute has no source declaration: {name}")
            formats, properties, symbols = definitions[name]
            node = ET.SubElement(root, "attr", name=name)
            if formats:
                node.set("format", "|".join(sorted(formats)))
            for key in sorted(properties):
                node.set(key, properties[key])
            for key in sorted(symbols):
                node.append(copy.deepcopy(symbols[key]))
        elif kind == "style":
            # Empty parent prevents inferring a non-public dotted style parent.
            ET.SubElement(root, "style", name=name, parent="")
        elif kind == "array":
            ET.SubElement(root, "array", name=name)
        elif kind in VALUE_DEFAULTS:
            ET.SubElement(root, kind, name=name).text = VALUE_DEFAULTS[kind]
        elif kind == "id":
            ET.SubElement(root, "item", type=kind, name=name)
        elif kind in REFERENCE_TYPES:
            ET.SubElement(root, "item", type=kind, name=name).text = "@null"
        else:
            raise ValueError(f"Unsupported public resource type: {kind}")
        ET.SubElement(root, "public", type=kind, name=name, id=f"0x{identifier:08x}")
    ET.indent(root)
    ET.ElementTree(root).write(values / "framework.xml", encoding="utf-8", xml_declaration=True)
    (directory / "AndroidManifest.xml").write_text('<manifest package="android"/>\n', encoding="utf-8")
    (directory / "ids.txt").write_text("".join(f"android:{kind}/{name} = 0x{identifier:08x}\n" for identifier, kind, name in public), encoding="utf-8")


def verify_dump(public, text):
    matches = re.findall(r"^\s+resource (0x[0-9a-f]+) ([^/ ]+)/([^ ]+) PUBLIC$", text, re.MULTILINE)
    found = {(kind, name): int(identifier, 16) for identifier, kind, name in matches}
    expected = {(kind, name): identifier for identifier, kind, name in public}
    if len(matches) != len(expected) or found != expected:
        raise ValueError("Compiled framework public resource IDs differ from source")


def canonical_archive(source, output):
    # The SDK table is never installed, but align resources.arsc so both native
    # AAPT readers and a combined android.jar can map it without unaligned data.
    import importlib.util
    spec = importlib.util.spec_from_file_location("android_zip", Path(__file__).with_name("zip.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build_archive(source, output, 315532800, apk=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", required=True, type=Path)
    parser.add_argument("--attrs", required=True, action="append", type=Path)
    parser.add_argument("--aapt2", default="aapt2")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ids-output", type=Path)
    args = parser.parse_args()
    public = public_resources(args.public)
    definitions = attributes(args.attrs)
    with tempfile.TemporaryDirectory(prefix="android-framework-res-") as temporary:
        directory = Path(temporary)
        write_inputs(public, definitions, directory)
        subprocess.run([args.aapt2, "compile", "--dir", "res", "-o", "compiled.zip"], cwd=directory, check=True)
        subprocess.run([args.aapt2, "link", "-x", "--allow-reserved-package-id", "--stable-ids", "ids.txt",
                        "--manifest", "AndroidManifest.xml", "-o", "framework.apk", "compiled.zip"], cwd=directory, check=True)
        report = subprocess.run([args.aapt2, "dump", "resources", "framework.apk"], cwd=directory,
                                check=True, capture_output=True, text=True).stdout
        verify_dump(public, report)
        stage = directory / "archive"
        stage.mkdir()
        with zipfile.ZipFile(directory / "framework.apk") as archive:
            for name in ("AndroidManifest.xml", "resources.arsc"):
                (stage / name).write_bytes(archive.read(name))
        canonical_archive(stage, args.output.resolve())
        if args.ids_output:
            args.ids_output.write_text(json.dumps({f"{kind}/{name}": f"0x{identifier:08x}" for identifier, kind, name in public},
                                                 sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
