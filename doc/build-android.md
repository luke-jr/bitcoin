# Android builds

Android supports the Qt GUI application and a native node module for another
application to embed. Both currently support `arm64-v8a`, with Android 9 (API 28)
as the minimum version. The GUI targets Android 16 (API 36).

Android support is experimental. The GUI runs inside the Qt application process;
Android can suspend or terminate it after switching applications. The embedding
host owns the module's threading, storage, permissions and background execution.
See the [module contract](../src/android/README.md) before using its API.

## Release builds with Guix

Use the existing [Guix release framework](../contrib/guix/README.md), including
its pinned Guix revision. The Android manifest selects source-built LLVM/LLD,
Bionic headers and link stubs, CRT objects, compiler-rt and C++ runtimes. The GUI
also builds Qt 6.9.3, OpenJDK, AAPT2, D8, FileProvider, platform API stubs and
framework resource stubs from pinned sources. No downloaded Android SDK, NDK,
Qt installation, Gradle distribution or binary Maven library is a release input.
The normal Guix bootstrap trust model still applies.

The host Java bootstrap builds the runtime, compiler, archive and signing tools
needed by these packages. Component and module selection exclude native desktop,
audio and printing code before compilation. Legacy Java support classes needed
by the compiler and Ant remain available; modular JDK stages select the tool
modules and their runtime dependencies. This removes the GTK accessibility and
SVG-loader paths that would otherwise require Go and Rust bootstrap toolchains.

Pinned Gitiles source archives are authenticated by the recursive hash of their
extracted contents, executable bits and symlinks. Request timestamps in archive
headers do not affect source verification.

The generated SDK stubs are compile-time inputs and are never packaged in the
application. The native toolchain exposes an NDK-compatible directory layout;
its compatibility revision `1.0.0` identifies this source toolchain, rather than
a Google NDK release. Android uses Qt 6 independently of the desktop Qt 5 build.

Keep the Guix store, source downloads, caches and build directories on a
filesystem with sufficient free space. A source bootstrap and compiler builds
need substantially more space than the APK. Share downloaded sources and depends
caches between modes, and build sequentially. A linked worktree avoids copying
Git's object database:

```sh
export ANDROID_WORK=/absolute/path/on/large/filesystem/bitcoin-android
mkdir -p "$ANDROID_WORK"
git worktree add --detach "$ANDROID_WORK/source" HEAD
cd "$ANDROID_WORK/source"

export SOURCES_PATH="$ANDROID_WORK/sources"
export BASE_CACHE="$ANDROID_WORK/depends-cache"
export VAR_BASE="$ANDROID_WORK/var"
export ADDITIONAL_GUIX_COMMON_FLAGS=--no-substitutes

for mode in module gui; do
    HOSTS=aarch64-linux-android ANDROID_BUILD_MODE="$mode" \
        DISTSRC_BASE="$ANDROID_WORK/build-$mode" \
        OUTDIR_BASE="$ANDROID_WORK/output-$mode" \
        PROFILES_BASE="$ANDROID_WORK/profiles-$mode" \
        ./contrib/guix/guix-build
done
```

Install/provision Guix as described by its documentation before running these
commands. `--no-substitutes` applies to both time-machine provisioning and the
build environment through the existing common-flags variable. Keep independent
reproduction runs in distinct build/output directories; reuse source caches and
the Guix store. Build from the same commit with the same release reference time.

The module build produces an AAR containing `libknots.so`, its Java bridge,
public C header, module documentation and license. The GUI build produces an
unsigned APK, unsigned AAB, detached-signing kit and separate debug archive.
Both modes produce the framework's source archive and SHA-256 records.

The GUI packages Java through javac and D8, and resources through AAPT2.
Source-built `androiddeployqt` stages Qt's dependency graph without Gradle.
Native APK libraries are uncompressed and aligned to 16 KiB. The AAB uses
protobuf resources and declares 16 KiB native-library alignment.

### Version codes

The default Android version code derives from the Knots release date and RC
rank: `YYYYMMDD * 100 + rank`. Final releases use rank 99; RC1 through RC98 use
their number. For example, `knots20260508` final is `2026050899`. This distinguishes
Knots releases sharing a Core version and orders final releases after their RCs.
Custom CMake builds can set `ANDROID_VERSION_CODE`; it must fit Play's positive
integer range. The empty default recomputes the code when the release changes.

## Detached release signing

The unsigned APK and AAB follow the existing Guix detached-signature process.
Extract the Android `*-codesigning.tar.gz` on the signing machine. It contains
`unsigned/` and the signing helpers. Keep keys and passwords outside Git and logs.

The APK signer needs `apksigner`; the AAB signer needs JDK `jarsigner` and
`android-aab-verify`. The Android codesigning Guix environment provides these
from source without rebuilding the cross compiler or Qt. Set the same release
`SOURCE_DATE_EPOCH` used for the unsigned build, then run:

```sh
./detached-sig-create.sh /secure/release-keystore.p12 release-alias APK_CERT_SHA256
./aab-detached-sig-create.sh /secure/upload-keystore.p12 upload-alias UPLOAD_CERT_SHA256
```

The helpers can read passwords from `KNOTS_ANDROID_KEYSTORE_PASSWORD` and
`KNOTS_ANDROID_KEY_PASSWORD`. The second password is optional when the keystore
uses the same password for its key. Avoid putting passwords on command lines.

Publish the resulting signature tarballs through the project's detached-signature
repository in the normal release process. The layouts are
`android/aarch64-linux-android/<unsigned-filename>.json` for each artifact.

Reconstruct and verify with `contrib/guix/guix-codesign`, setting
`HOSTS=aarch64-linux-android`, `DETACHED_SIGS_REPO`, the GUI build's `OUTDIR_BASE`,
and `ANDROID_RELEASE_CERTIFICATE_SHA256` to the independently verified APK
certificate digest. Set `ANDROID_UPLOAD_CERTIFICATE_SHA256` for a separate Play
upload certificate; it defaults to the APK certificate. Certificate fingerprints
inside detached payloads are never trusted as the authority for verification.
The module AAR is signed as part of its embedding host's application.

APK reconstruction preserves the unsigned archive's content and offsets and
verifies APK v2/v3 signatures. AAB reconstruction preserves the unsigned payload
and verifies that every payload entry has exactly one signer with the expected
certificate. No private signing key is needed for reconstruction.

## Development toolchains

For iterative native development, the depends Android host configuration also
accepts an external NDK. NDK r28c and Qt 6.9.3 have been used for development.
Such builds are separate from the source-only Guix release workflow.

```sh
make -C depends HOST=aarch64-linux-android \
    ANDROID_NDK=/absolute/path/to/android-ndk-r28c \
    NO_QT=1 NO_ZMQ=1 NO_UPNP=1
cmake -S . -B /absolute/path/to/build-module \
    --toolchain "$PWD/depends/aarch64-linux-android/toolchain.cmake" \
    -DBUILD_ANDROID_MODULE=ON -DBUILD_GUI=OFF \
    -DENABLE_EXTERNAL_SIGNER=OFF -DENABLE_TOR_SUBPROCESS=OFF
cmake --build /absolute/path/to/build-module --target bitcoin_android
```

See [depends](../depends/README.md) for external cache/prefix path overrides.
Keep toolchains and build outputs outside the checkout. Do not reuse a CMake
build directory across toolchains.

For GUI development, use matching Qt 6 Android and host installations. Configure
with Qt's `qt-cmake`, `BUILD_GUI=ON`, `BUILD_ANDROID_MODULE=OFF`, and
`WITH_QT_VERSION=6`, pointing Qt at the Android depends prefix. The `bitcoin-qt`
target builds the native GUI; Qt's `apk` and `aab` targets use the installed
development SDK and Java tools. These targets do not establish reproducibility.

## Android behavior

The GUI starts the node after first-run setup. Release builds ignore Qt launch
extras that can change node arguments or environment; debug builds retain Qt's
development argument support. The module's explicit host-owned argument API has
ordinary node configuration semantics, including explicit RPC settings.

### Network and power preferences

Options → Network contains two Android preferences, enabled by default: pause
on cellular or metered connections, and pause on battery power. Unknown connection
or power state also pauses when the corresponding preference is on. Metered
Wi-Fi counts as metered; cellular transport takes precedence when Android
reports several transports, including a VPN.

These preferences use the existing network-active toggle. Enable networking
from the network icon to override an automatic pause. Repeated reports of the
same conditions preserve that choice; a relevant device condition or preference
change applies automatic control again. A manual disable from the active state
is not automatically undone. Startup waits for device conditions before enabling
network activity, while respecting an explicit `-networkactive=0`. These options
control P2P networking; local processing can continue.

### Configuration, storage and logs

Open Configuration File asks Android to use an external text editor, granting
read/write access to that file. The app honors Android's preferred editor and
does not include an editor. An editor must support editing content URIs.

Wallet import, export and backup currently use filesystem paths. Android document
provider integration remains necessary for convenient external storage access.
Node and wallet data default to private app storage.

By default, Android logs to logcat with tag `BitcoinKnots`, without creating
`debug.log` or duplicating output on the console. Explicit `-debuglogfile` or
`-printtoconsole` settings change those defaults:

```sh
adb logcat -s BitcoinKnots
```

On GrapheneOS, Qt regular-expression JIT is disabled when the effective process
flags report that executable memory is blocked. Otherwise Qt retains its normal
JIT behavior.

## Validation

Before publishing, compare unsigned and reconstructed signed artifacts from
independent Guix builds of the same source and parameters. Verify all native
libraries and package alignment, and run the release helper tests:

```sh
python3 contrib/android/verify.py /absolute/path/to/application.apk
python3 contrib/android/test_api_stubs.py
python3 contrib/android/test_activity_intents.py
python3 contrib/android/test_version_code.py
python3 contrib/android/test_release_tools.py
python3 contrib/android/test_aab.py
```

Test Gitiles source authentication with GNU tar, gzip and a UTF-8 locale:

```sh
guix repl -L contrib/guix/modules -- contrib/guix/tests/gitiles.scm
```

Test Android startup/shutdown, process death and database recovery, pruning and
storage exhaustion, network and power transitions, manual network overrides,
external configuration editing, dialogs and wallet flows. Include devices with
4 KiB and 16 KiB pages, and GrapheneOS with memory DCL allowed and blocked.

Google Play [requires App Bundles for new apps](https://support.google.com/googleplay/android-developer/answer/9859348)
and currently [requires target API 36](https://developer.android.com/google/play/requirements/target-sdk)
for new phone/tablet apps and updates. The AAB is the upload artifact; the APK
supports installation outside Play and device testing. Review current Play
requirements, signing enrollment and privacy disclosures before submission.
