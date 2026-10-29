;;; Copyright (c) 2026 The Bitcoin Knots developers
;;; Distributed under the MIT software license, see the accompanying file COPYING.

(define-module (bitcoin android-sdk)
  #:use-module (gnu packages java)
  #:use-module (gnu packages python)
  #:use-module (guix build-system gnu)
  #:use-module (guix download)
  #:use-module (guix gexp)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (guix packages))

(define %api-compiler (local-file "../../libexec/build-android-api.py"))
(define %api-tests (local-file "../../../android/test_api_stubs.py"))
(define %canonical-zip (local-file "../../../android/zip.py"))

;; Gitiles TEXT responses contain base64-encoded source, not SDK binaries.
(define lambda-stub-source
  (origin
    (method url-fetch)
    (uri (string-append
          "https://android.googlesource.com/platform/libcore/+/"
          "fff4fcc0cf7f080cf2511cbb57561482b13b218f/"
          "ojluni/src/lambda/java/java/lang/invoke/LambdaMetafactory.java?format=TEXT"))
    (file-name "LambdaMetafactory.java.base64")
    (sha256 (base32 "1nznr14k4x7xjz1vsr4q74fgm25xvpqdkw1pghwniv8gnq18lsch"))))

(define-public android-api-36
  (package
    (name "android-api")
    (version "36")
    (source
     (origin
       (method url-fetch)
       (uri (string-append
             "https://android.googlesource.com/platform/prebuilts/sdk/+/"
             "3b7daadc4e54d51439e5ae9b4dbd96cda8b6104e/"
             "36/public/api/android.txt?format=TEXT"))
       (file-name "android-36-api.txt.base64")
       (sha256 (base32 "0460wkzs0xiv832pcbzdhnv7pmn67nkq30gymc38cdjywb855f8c"))))
    (build-system gnu-build-system)
    (arguments
     (list
      #:phases
      #~(modify-phases %standard-phases
          (replace 'unpack
            (lambda* (#:key source inputs #:allow-other-keys)
              (copy-file source "android-api.base64")
              (invoke "python3" "-c"
                      (string-append
                       "import base64,pathlib,sys; pathlib.Path('LambdaMetafactory.java').write_bytes("
                       "base64.b64decode(pathlib.Path(sys.argv[1]).read_bytes(),validate=True))")
                      (assoc-ref inputs "lambda-stub-source"))))
          (delete 'configure)
          (replace 'build
            (lambda _
              (invoke "python3" #$%api-compiler "android-api.base64" "classes" "--base64")
              (invoke "python3" #$%canonical-zip "classes" "android.jar" "--epoch" "315532800")
              (invoke "javac" "-source" "8" "-target" "8"
                      "-bootclasspath" "android.jar" "-encoding" "UTF-8"
                      "-d" "lambda-classes" "LambdaMetafactory.java")
              (invoke "python3" #$%canonical-zip "lambda-classes" "core-lambda-stubs.jar"
                      "--epoch" "315532800")))
          (replace 'check
            (lambda* (#:key tests? #:allow-other-keys)
              (when tests?
                (setenv "ANDROID_API_COMPILER" #$%api-compiler)
                (invoke "python3" #$%api-tests)
                ;; Check the complete source-to-archive path independently of
                ;; filesystem enumeration order and class-file pool reuse.
                (invoke "python3" #$%api-compiler "android-api.base64" "classes-again" "--base64")
                (invoke "python3" #$%canonical-zip "classes-again" "android-again.jar"
                        "--epoch" "315532800")
                (invoke "cmp" "android.jar" "android-again.jar")
                ;; Exercise javac's Android API resolution, generics, lambda
                ;; bootstrap metadata, constants, enums and annotation defaults.
                (call-with-output-file "ApiProbe.java"
                  (lambda (port)
                    (display
                     (string-append
                      "@android.annotation.TargetApi(36)\n"
                      "@android.annotation.SuppressLint({\"NewApi\"})\n"
                      "public class ApiProbe {\n"
                      " @Deprecated(since=\"1\",forRemoval=false)\n"
                      " public static <T extends java.io.Serializable & Comparable<T>> T id(T v) {return v;}\n"
                      " java.util.Map.Entry<String,Integer> entry;\n"
                      " java.util.function.ToIntFunction<String> length = String::length;\n"
                      " java.util.concurrent.Callable<String> lambda = () -> \"android\";\n"
                      " android.graphics.Bitmap.Config config = android.graphics.Bitmap.Config.ARGB_8888;\n"
                      " android.os.Bundle bundle = new android.os.Bundle();\n"
                      " int version = android.os.Build.VERSION_CODES.BAKLAVA;\n"
                      " public String stream() { return java.util.stream.Stream.of(\"a\",\"b\")"
                      ".map(String::toUpperCase).findFirst().orElse(\"\"); }\n}\n") port)))
                (invoke "javac" "-source" "8" "-target" "8"
                        "-bootclasspath" "android.jar:core-lambda-stubs.jar"
                        "-d" "probe-classes" "ApiProbe.java"))))
          (replace 'install
            (lambda* (#:key outputs #:allow-other-keys)
              (let* ((out (assoc-ref outputs "out"))
                     (platform (string-append out "/platforms/android-36")))
                (install-file "android.jar" platform)
                (install-file "core-lambda-stubs.jar" (string-append out "/share/android"))
                (call-with-output-file (string-append platform "/source.properties")
                  (lambda (port)
                    (display "Pkg.Desc=Bitcoin Knots source-generated Android API 36\nAndroidVersion.ApiLevel=36\nPkg.Revision=1\n" port)))))))))
    (native-inputs
     (list (list "python" python-minimal)
           (list "openjdk" openjdk17 "jdk")
           (list "lambda-stub-source" lambda-stub-source)))
    (home-page "https://android.googlesource.com/platform/prebuilts/sdk/")
    (synopsis "Android 36 compile-time API generated from signature source")
    (description "This package compiles Android's public API signature source
into JVM class-file stubs.  The companion lambda bootstrap stub is built from
libcore Java source.  No prebuilt android.jar, Metalava binary, Kotlin compiler,
Gradle distribution or Maven artifact is an input.  These jars are compiler
libraries, not Android runtime code, and must never be packaged in an APK.
Framework resources are provided separately by the source-built resource SDK.")
    (license (list license:asl2.0 license:gpl2+))))
