#!/usr/bin/env bash
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
set -e -o pipefail
export LC_ALL=C TZ=UTC
umask 0022

: "${HOST:?}" "${DISTNAME:?}" "${DISTSRC:?}" "${OUTDIR:?}"
: "${DIST_ARCHIVE_BASE:?}" "${SOURCE_DATE_EPOCH:?}" "${JOBS:?}"
MODE="${ANDROID_BUILD_MODE:-gui}"
case "$MODE" in
    module) android_no_qt=1 ;;
    gui) android_no_qt= ;;
    *) echo 'ANDROID_BUILD_MODE must be gui or module' >&2; exit 1 ;;
esac

BASEPREFIX="$PWD/depends"
ACTUAL_OUTDIR="$OUTDIR"
OUTDIR="$DISTSRC/output"
mkdir -p "$DISTSRC/tmp" "$OUTDIR"
export TMPDIR="$DISTSRC/tmp"
export ANDROID_NDK="$GUIX_ENVIRONMENT/lib/android-toolchain"
export ANDROID_NDK_ROOT="$ANDROID_NDK"
test -d "$ANDROID_NDK/toolchains/llvm/prebuilt/linux-x86_64"
# Native GCC search paths must not leak into Android compilation. Compiler
# wrappers carry their own explicit target headers, runtime and sysroot.
unset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH OBJC_INCLUDE_PATH OBJCPLUS_INCLUDE_PATH LIBRARY_PATH
export GUIX_LD_WRAPPER_DISABLE_RPATH=yes
export TAR_OPTIONS="--owner=0 --group=0 --numeric-owner --mtime='@${SOURCE_DATE_EPOCH}' --sort=name"

make -C depends --jobs="$JOBS" HOST="$HOST" \
    NO_QT="$android_no_qt" NO_ZMQ=1 NO_UPNP=1 NO_USDT=1 \
    ${V:+V=1} ${SOURCES_PATH:+SOURCES_PATH="$SOURCES_PATH"} \
    ${BASE_CACHE:+BASE_CACHE="$BASE_CACHE"} \
    x86_64_linux_CC=x86_64-linux-gnu-gcc \
    x86_64_linux_CXX=x86_64-linux-gnu-g++ \
    x86_64_linux_AR=x86_64-linux-gnu-gcc-ar \
    x86_64_linux_RANLIB=x86_64-linux-gnu-gcc-ranlib \
    x86_64_linux_NM=x86_64-linux-gnu-gcc-nm \
    x86_64_linux_STRIP=x86_64-linux-gnu-strip

GIT_ARCHIVE="$DIST_ARCHIVE_BASE/$DISTNAME.tar.gz"
if [[ ! -e "$GIT_ARCHIVE" ]]; then
    mkdir -p "$(dirname "$GIT_ARCHIVE")"
    REFERENCE_DATETIME="@$SOURCE_DATE_EPOCH" \
        contrib/guix/libexec/make_release_tarball.sh "$GIT_ARCHIVE" "$DISTNAME"
fi
(
    cd "$DISTSRC"
    tar --strip-components=1 -xf "$GIT_ARCHIVE"
    python3 contrib/android/test_native_security.py
    # Keep release optimization while retaining DWARF for the separate symbol
    # archive. split-debug.sh removes it from every shipped native library.
    config=(-DCMAKE_BUILD_TYPE=Release -DAPPEND_CFLAGS=-g -DAPPEND_CXXFLAGS=-g
            -DREDUCE_EXPORTS=ON -DWITH_CCACHE=OFF
            -DBUILD_DAEMON=OFF -DBUILD_CLI=OFF -DBUILD_TESTS=OFF -DBUILD_BENCH=OFF
            -DBUILD_GUI_TESTS=OFF -DBUILD_FUZZ_BINARY=OFF -DBUILD_BITCOINCONSENSUS_LIB=OFF
            -DENABLE_EXTERNAL_SIGNER=OFF -DENABLE_TOR_SUBPROCESS=OFF
            -DWITH_ZMQ=OFF -DWITH_MINIUPNPC=OFF -DWITH_USDT=OFF)
    if [[ "$MODE" == module ]]; then
        cmake -S . -B build --toolchain "$BASEPREFIX/$HOST/toolchain.cmake" \
            "${config[@]}" -DBUILD_ANDROID_MODULE=ON -DBUILD_GUI=OFF
        cmake --build build --target bitcoin_android -j "$JOBS" ${V:+--verbose}
        mkdir -p module/jni/arm64-v8a module/headers module/META-INF java-classes debug
        cp build/lib/libknots.so module/jni/arm64-v8a/
        bash build/split-debug.sh module/jni/arm64-v8a/libknots.so \
            module/jni/arm64-v8a/libknots.so debug/libknots.so.dbg
        cp src/android/bitcoin_knots_node.h module/headers/
        cp src/android/README.md module/README.md
        cp COPYING module/META-INF/LICENSE
        mkdir -p module/META-INF/licenses
        cp -R "$GUIX_ENVIRONMENT/share/licenses/android-runtime" module/META-INF/licenses/
        cat > module/AndroidManifest.xml <<'MANIFEST'
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.bitcoinknots.android">
    <uses-sdk android:minSdkVersion="28" />
</manifest>
MANIFEST
        javac --release 8 -encoding UTF-8 -d java-classes \
            src/android/java/org/bitcoinknots/android/Node.java
        python3 contrib/android/zip.py java-classes module/classes.jar
        python3 contrib/android/zip.py module "$OUTDIR/$DISTNAME-$HOST-module.aar"
        python3 contrib/android/verify.py --check-security "$OUTDIR/$DISTNAME-$HOST-module.aar"
    else
        for tool in java javac keytool jarsigner; do
            command -v "$tool" >/dev/null
        done
        export QT_HOST_PATH="$GUIX_ENVIRONMENT/lib/qt6-host"
        # Resolve Qt before it derives its install prefix. The union profile
        # also contains host headers, which must not reach the Android compiler.
        qt_toolchain_file=$(realpath -- "$GUIX_ENVIRONMENT/lib/cmake/Qt6/qt.toolchain.cmake")
        cmake -S . -B build \
            --toolchain "$qt_toolchain_file" \
            "${config[@]}" -DBUILD_ANDROID_MODULE=OFF -DBUILD_GUI=ON -DWITH_QT_VERSION=6 \
            -DCMAKE_PREFIX_PATH="$BASEPREFIX/$HOST" \
            -DCMAKE_FIND_PACKAGE_RESOLVE_SYMLINKS=ON \
            -DQT_ADDITIONAL_PACKAGES_PREFIX_PATH="$BASEPREFIX/$HOST" \
            -DQT_HOST_PATH="$QT_HOST_PATH" \
            -DQt6LinguistTools_DIR="$GUIX_ENVIRONMENT/lib/qt6-host-tools/lib/cmake/Qt6LinguistTools" \
            -DANDROID_SDK_ROOT="$GUIX_ENVIRONMENT" \
            -DQT_ANDROID_SDK_BUILD_TOOLS_REVISION=1.0.0 \
            -DANDROID_STL=c++_shared -DCMAKE_ANDROID_STL_TYPE=c++_shared \
            -DCMAKE_SKIP_BUILD_RPATH=TRUE
        cmake --build build --target bitcoin-qt -j "$JOBS" ${V:+--verbose}
        # androiddeployqt edits this template after copying project resources.
        # Supply a writable application copy: QFile::copy otherwise preserves
        # the read-only permissions of the template in the Guix store.
        install -D -m 644 "$GUIX_ENVIRONMENT/src/android/templates/res/values/libs.xml" \
            build/src/qt/android/res/values/libs.xml
        mkdir -p stage/libs/arm64-v8a debug
        cp build/lib/libbitcoin-qt_arm64-v8a.so stage/libs/arm64-v8a/
        "$QT_HOST_PATH/bin/androiddeployqt" --aux-mode \
            --input build/src/qt/android-bitcoin-qt-deployment-settings.json \
            --output "$PWD/stage" --android-platform android-36
        while IFS= read -r -d '' library; do
            bash build/split-debug.sh "$library" "$library" "debug/$(basename "$library").dbg"
        done < <(find stage/libs/arm64-v8a -type f -name '*.so' -print0 | sort -z)

        python3 contrib/android/test_api_stubs.py
        python3 contrib/android/test_activity_intents.py
        python3 contrib/android/test_version_code.py
        python3 contrib/android/test_release_tools.py
        python3 contrib/android/test_aab.py
        python3 contrib/android/package.py --stage "$PWD/stage" --work "$PWD/package" \
            --output "$OUTDIR/$DISTNAME-$HOST-unsigned.apk" \
            --android-jar "$GUIX_ENVIRONMENT/platforms/android-36/android.jar" \
            --lambda-stubs "$GUIX_ENVIRONMENT/share/android/core-lambda-stubs.jar" \
            --framework-resources "$GUIX_ENVIRONMENT/share/android/platforms/android-36/framework-res.apk" \
            --fileprovider "$GUIX_ENVIRONMENT/share/java/androidx-fileprovider.jar" \
            --qt-java-source "$GUIX_ENVIRONMENT/src/android/java/src" \
            --license-directory "$GUIX_ENVIRONMENT/share/licenses/qt6"
        python3 contrib/android/aab.py --resources package/resources-proto.apk \
            --dex package/dex --native-libraries package/apk/lib/arm64-v8a \
            --assets package/apk/assets --output "$OUTDIR/$DISTNAME-$HOST-unsigned.aab"

        mkdir -p codesigning/unsigned
        # These immutable outputs share a filesystem with the signing kit.
        ln "$OUTDIR/$DISTNAME-$HOST-unsigned.apk" "$OUTDIR/$DISTNAME-$HOST-unsigned.aab" codesigning/unsigned/
        cp --target-directory=codesigning contrib/android/apk-signatures.py contrib/android/zip.py \
            contrib/android/apply-sigs.sh contrib/android/detached-sig-create.sh \
            contrib/android/aab.py contrib/android/aab-signatures.py contrib/android/aab-apply-sigs.sh \
            contrib/android/aab-detached-sig-create.sh
        (
            cd codesigning
            find . -print0 | sort -z \
                | tar --create --no-recursion --mode='u+rw,go+r-w,a+X' --null --files-from=- \
                | gzip -9n > "$OUTDIR/$DISTNAME-$HOST-codesigning.tar.gz"
        )
    fi
    tar -C debug -cf - . | gzip -9n > "$OUTDIR/$DISTNAME-$HOST-$MODE-debug.tar.gz"
)
mv --no-target-directory "$OUTDIR" "$ACTUAL_OUTDIR"
(
    cd /outdir-base
    {
        echo "$GIT_ARCHIVE"
        find "$ACTUAL_OUTDIR" -type f
    } | xargs realpath --relative-base="$PWD" \
      | xargs sha256sum | sort -k2 | sponge "$ACTUAL_OUTDIR/SHA256SUMS.part"
)
