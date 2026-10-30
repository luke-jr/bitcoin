;;; Copyright (c) 2026 The Bitcoin Knots developers
;;; Distributed under the MIT software license, see the accompanying
;;; file COPYING or https://opensource.org/license/mit/.

(define-module (bitcoin android-qt)
  #:use-module (guix packages)
  #:use-module (guix download)
  #:use-module (guix gexp)
  #:use-module (guix search-paths)
  #:use-module (guix build-system cmake)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (gnu packages)
  #:use-module (gnu packages perl)
  #:use-module (gnu packages python)
  #:use-module (bitcoin android-host-jdk)
  #:use-module (bitcoin android)
  #:use-module (bitcoin android-sdk))

(define %normalize-jars
  (local-file "../../libexec/normalize-android-jars.py"))

(define (qt-source component hash)
  (origin
    (method url-fetch)
    (uri (string-append "https://download.qt.io/archive/qt/6.9/6.9.3/submodules/"
                        component "-everywhere-src-6.9.3.tar.xz"))
    (sha256 (base32 hash))
    ;; Apply the same moc compatibility patch as the pinned Guix Qt packages.
    ;; Guix exposes GCC's C++ headers through CPLUS_INCLUDE_PATH, which moc
    ;; scans without the compiler predefines needed by _GLIBCXX_VISIBILITY.
    (patches (if (string=? component "qtbase")
                 (search-patches "qtbase-moc-ignore-gcc-macro.patch")
                 '()))
    (modules '((guix build utils)))
    (snippet
     (and (string=? component "qtbase")
          '(begin
             ;; Gradle is not part of the release pipeline. Remove the bundled
             ;; binary wrapper before building or installing anything.
             (delete-file "src/3rdparty/gradle/gradle/wrapper/gradle-wrapper.jar")
             (substitute* "src/3rdparty/gradle/CMakeLists.txt"
               ((".*gradle-wrapper.jar.*\n") ""))
             ;; Auxiliary staging must include project manifest/resources as
             ;; normal deployment does, while never copying Gradle tooling.
             (substitute* "src/tools/androiddeployqt/main.cpp"
               (("    if \\(!copyGradleTemplate\\(options\\)\\)")
                "    if (!options.auxMode && !copyGradleTemplate(options))")
               (("    if \\(options.auxMode\\) \\{\n")
                "    if (options.auxMode) {\n        if (!copyAndroidSources(options))\n            return CannotCopyAndroidSources;\n"))
             ;; Compile solely against the source-built Android API and its
             ;; compiler-only lambda stub, never the host JDK API classes.
             (substitute* "cmake/QtJavaHelpers.cmake"
               (("-classpath \"\\$\\{QT_ANDROID_JAR\\}\"")
                "-bootclasspath \"${QT_ANDROID_JAR}:${ANDROID_SDK_ROOT}/share/android/core-lambda-stubs.jar\"")))))))

(define-public qtbase-android-host
  (package
    (name "qtbase-android-host")
    (version "6.9.3")
    (source (qt-source "qtbase" "0vnwp12wvsab1vsn8zhi4mcvrpg5iacq59xzzs0w0vimc3va58f5"))
    (build-system cmake-build-system)
    (arguments
     (list
      #:tests? #f
      #:build-type "Release"
      #:configure-flags
      #~(list "-DBUILD_SHARED_LIBS=OFF" "-DQT_BUILD_TESTS=OFF" "-DQT_BUILD_EXAMPLES=OFF"
              "-DFEATURE_gui=OFF" "-DFEATURE_widgets=OFF" "-DFEATURE_network=OFF"
              "-DFEATURE_sql=OFF" "-DFEATURE_dbus=OFF" "-DFEATURE_openssl=OFF"
              "-DFEATURE_testlib=OFF" "-DFEATURE_concurrent=OFF" "-DFEATURE_glib=OFF"
              "-DFEATURE_icu=OFF" "-DFEATURE_system_zlib=OFF" "-DFEATURE_system_pcre2=OFF"
              "-DFEATURE_system_doubleconversion=OFF" "-DFEATURE_androiddeployqt=ON"
              "-DBUILD_WITH_PCH=OFF")))
    (native-inputs (list perl python-minimal))
    (home-page "https://www.qt.io/")
    (synopsis "Qt 6 host tools for the Android GUI source build")
    (description "This package builds the Qt 6 host tools, including moc, rcc,
uic and androiddeployqt, from the Qt source archive.  Bundled dependencies are
compiled from their sources in the same archive.  It is independent of the
desktop Qt 5 depends build.")
    (license (list license:lgpl3 license:gpl3 license:bsd-3))))

(define-public qttools-android-host
  (package
    (name "qttools-android-host")
    (version "6.9.3")
    (source (qt-source "qttools" "1sdla2blvk9r4g7v67dhwqjxx7kflyh7cm9pw5f7ziazjw7apxqc"))
    (build-system cmake-build-system)
    (arguments
     (list
      #:tests? #f
      #:build-type "Release"
      #:configure-flags
      #~(list (string-append "-DCMAKE_PREFIX_PATH=" #$qtbase-android-host)
              "-DQT_BUILD_TESTS=OFF" "-DQT_BUILD_EXAMPLES=OFF"
              "-DFEATURE_assistant=OFF" "-DFEATURE_designer=OFF"
              "-DFEATURE_distancefieldgenerator=OFF" "-DFEATURE_kmap2qmap=OFF"
              "-DFEATURE_pixeltool=OFF" "-DFEATURE_qdbus=OFF" "-DFEATURE_qev=OFF"
              "-DFEATURE_qtattributionsscanner=OFF" "-DFEATURE_qtdiag=OFF"
              "-DFEATURE_qtplugininfo=OFF" "-DFEATURE_qdoc=OFF")))
    (native-inputs (list perl python-minimal))
    (inputs (list qtbase-android-host))
    (home-page "https://www.qt.io/")
    (synopsis "Qt 6 host translation tools built from source")
    (description "This package builds the Qt Linguist command-line tools,
including lrelease, for compiling the Android GUI's translation catalogs.")
    (license (list license:lgpl3 license:gpl3))))

(define-public qtbase-android
  (package
    (inherit qtbase-android-host)
    (name "qtbase-android")
    (arguments
     (list
      #:tests? #f
      #:build-type "Release"
      #:validate-runpath? #f ; Android dependencies are resolved on the device.
      #:configure-flags
      #~(list
         (string-append "-DCMAKE_TOOLCHAIN_FILE=" #$android-aarch64-gui-toolchain
                        "/lib/android-toolchain/build/cmake/android.toolchain.cmake")
         (string-append "-DANDROID_NDK_ROOT=" #$android-aarch64-gui-toolchain "/lib/android-toolchain")
         (string-append "-DANDROID_SDK_ROOT=" #$android-api-36)
         (string-append "-DQT_HOST_PATH=" #$qtbase-android-host)
         "-DANDROID_ABI=arm64-v8a" "-DANDROID_NATIVE_API_LEVEL=28"
         "-DANDROID_STL=c++_shared" "-DQT_ANDROID_API_USED_FOR_JAVA=android-36"
         "-DQT_ANDROID_JAVAC_SOURCE=8" "-DQT_ANDROID_JAVAC_TARGET=8"
         "-DQT_BUILD_TESTS=OFF" "-DQT_BUILD_EXAMPLES=OFF"
         "-DFEATURE_dbus=OFF" "-DFEATURE_openssl=OFF" "-DFEATURE_vulkan=OFF"
         "-DINPUT_opengl=es2" "-DFEATURE_system_zlib=OFF"
         "-DFEATURE_system_pcre2=OFF" "-DFEATURE_system_doubleconversion=OFF"
         "-DFEATURE_system_freetype=OFF" "-DFEATURE_system_harfbuzz=OFF"
         "-DFEATURE_system_libpng=OFF" "-DFEATURE_system_jpeg=OFF"
         "-DFEATURE_system_sqlite=OFF" "-DBUILD_WITH_PCH=OFF" "-DCMAKE_SKIP_RPATH=ON")
      #:phases
      #~(modify-phases %standard-phases
          (add-after 'unpack 'preserve-qt-licenses
            (lambda _
              (let ((licenses (string-append #$output "/share/licenses/qt6")))
                (mkdir-p licenses)
                (copy-recursively "LICENSES" licenses)
                (copy-recursively
                 #$(file-append android-aarch64-gui-cxx-runtime "/share/licenses/android-runtime")
                 (string-append licenses "/android-runtime")))))
          (add-after 'set-paths 'target-environment
            (lambda _
              (setenv "JAVA_HOME" #$android-openjdk17:jdk)
              (for-each unsetenv '("C_INCLUDE_PATH" "CPLUS_INCLUDE_PATH" "CPATH" "LIBRARY_PATH"))))
          (add-after 'install 'expose-host-tools-and-normalize-jars
            (lambda _
              (symlink #$qtbase-android-host (string-append #$output "/lib/qt6-host"))
              (symlink #$qttools-android-host (string-append #$output "/lib/qt6-host-tools"))
              (invoke "python3" #$%normalize-jars #$output)))
          (delete 'strip))))
    (native-inputs (list perl python-minimal (list android-openjdk17 "jdk")
                         qtbase-android-host qttools-android-host))
    (inputs (list android-api-36 android-aarch64-gui-toolchain))
    (native-search-paths
     (list (search-path-specification
            (variable "QT_HOST_PATH")
            (files '("lib/qt6-host"))
            (separator #f))))
    (synopsis "Qt 6 Android GUI libraries and Java bindings built from source")
    (description "This package compiles Qt Core, GUI, Widgets, Network and their
Android plugins, plus the Java 8 bindings, using the source-built native
toolchain and generated Android API.  Its source removes the Gradle binary
wrapper; release APK assembly is performed separately without Gradle.")))
