#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Prepare pinned AndroidX FileProvider source for an API-28-or-newer app.

The provider's URI, permission, path-containment and file-opening code stays
upstream. Compatibility calls become their equivalent platform calls, available
before API 28. Source-only annotations require no AndroidX/Kotlin dependency.
Input is the base64 text returned by Gitiles, not a binary Maven artifact.
"""

import argparse
import base64
from pathlib import Path
import re


def decode(path):
    return base64.b64decode(b"".join(path.read_bytes().split()), validate=True)


def adapt(source):
    replacements = {
        "import static androidx.core.util.ObjectsCompat.requireNonNull;":
            "import static java.util.Objects.requireNonNull;",
        "ResourcesCompat.ID_NULL": "0",
        "ContextCompat.getExternalFilesDirs(context, null)": "context.getExternalFilesDirs(null)",
        "ContextCompat.getExternalCacheDirs(context)": "context.getExternalCacheDirs()",
    }
    for old, new in replacements.items():
        if old not in source:
            raise ValueError(f"Pinned FileProvider compatibility call not found: {old}")
        source = source.replace(old, new)
    source = re.sub(r"^import (?:androidx\.|org\.jspecify\.|android\.annotation\.)[^;]+;\n",
                    "", source, flags=re.MULTILINE)
    source = re.sub(r"@(NonNull|Nullable|CallSuper|GuardedBy|VisibleForTesting|XmlRes|SuppressLint)\b(?:\([^)]*\))?",
                    "", source)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--license", type=Path)
    parser.add_argument("--license-output", type=Path)
    args = parser.parse_args()
    if bool(args.license) != bool(args.license_output):
        parser.error("--license and --license-output must be supplied together")
    source = adapt(decode(args.source).decode("utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="utf-8", newline="\n")
    if args.license:
        args.license_output.parent.mkdir(parents=True, exist_ok=True)
        args.license_output.write_bytes(decode(args.license))


if __name__ == "__main__":
    main()
