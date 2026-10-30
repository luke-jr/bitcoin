;; Copyright (c) 2026 The Bitcoin Knots developers
;; Distributed under the MIT software license, see the accompanying file COPYING.

(define-module (bitcoin android-fileprovider)
  #:use-module (bitcoin android-host-jdk)
  #:use-module (gnu packages python)
  #:use-module (guix build-system gnu)
  #:use-module (guix download)
  #:use-module (guix gexp)
  #:use-module (guix git-download)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (guix packages))

(define prepare-source
  (local-file "../../../android/prepare-fileprovider.py"))

(define-public (make-android-fileprovider api-jar)
  "Build FileProvider against the source-generated API-JAR file-like object.
This factory keeps the provider independent of the assembled Android SDK and
avoids a dependency cycle with the platform API package. The application must
require API 28 or later."
  (let* ((commit "ee9b3bd4e15861a649335dca51923b358357b151")
         (base (string-append "https://android.googlesource.com/platform/frameworks/support/+/"
                              commit "/"))
         (license-source
          (origin
            (method url-fetch)
            (uri (string-append base "LICENSE.txt?format=TEXT"))
            (file-name "androidx-fileprovider-LICENSE.txt.base64")
            (sha256
             (base32 "0gf2ac5xl6wc232r1wwi7123dn2pqj35ipy5lins0klcq9gv0dhj")))))
    (package
      (name "androidx-fileprovider")
      (version (git-version "0.0" "0" commit))
      (source
       (origin
         (method url-fetch)
         (uri (string-append base
                            "core/core/src/main/java/androidx/core/content/FileProvider.java?format=TEXT"))
         (file-name "androidx-FileProvider.java.base64")
         (sha256
          (base32 "0rq4m608ksmg5gq62ysrl4mlwnrl6h1cmzaf8wzb24baz1qsz591"))))
      (build-system gnu-build-system)
      (arguments
       (list
        ;; Runtime provider tests require Android. The strict source-only
        ;; bootclasspath compilation below validates its Java dependencies.
        #:tests? #f
        #:phases
        #~(modify-phases %standard-phases
            (replace 'unpack
              (lambda* (#:key source inputs #:allow-other-keys)
                (mkdir "source")
                (chdir "source")
                (invoke "python3" #$prepare-source source
                        "src/androidx/core/content/FileProvider.java"
                        "--license" (assoc-ref inputs "license-source")
                        "--license-output" "src/META-INF/LICENSE-androidx-fileprovider.txt")))
            (delete 'configure)
            (replace 'build
              (lambda _
                (mkdir "classes")
                ;; Use only the source-generated Android API as bootclasspath;
                ;; no Android SDK download or precompiled AndroidX dependencies.
                (invoke "javac" "-source" "8" "-target" "8"
                        "-encoding" "UTF-8" "-bootclasspath" #$api-jar
                        "-classpath" "" "-d" "classes"
                        "src/androidx/core/content/FileProvider.java")
                (install-file "src/META-INF/LICENSE-androidx-fileprovider.txt"
                              "classes/META-INF")
                (with-directory-excursion "classes"
                  (apply invoke "jar" "--create"
                         "--file" "../androidx-fileprovider.jar" "--no-compress"
                         "--date=1980-01-01T00:00:02Z"
                         (sort (find-files "." "\\.(class|txt)$") string<?)))
                (with-directory-excursion "src"
                  (apply invoke "jar" "--create"
                         "--file" "../androidx-fileprovider-sources.jar" "--no-compress"
                         "--date=1980-01-01T00:00:02Z"
                         (sort (find-files "." "\\.(java|txt)$") string<?)))))
            (replace 'install
              (lambda* (#:key outputs #:allow-other-keys)
                (let ((directory (string-append (assoc-ref outputs "out")
                                                "/share/java")))
                  (install-file "androidx-fileprovider.jar" directory)
                  (install-file "androidx-fileprovider-sources.jar" directory)))))))
      (native-inputs
       (list (list "openjdk" android-openjdk17 "jdk")
             (list "python" python-minimal)
             (list "license-source" license-source)))
      (home-page "https://developer.android.com/reference/androidx/core/content/FileProvider")
      (synopsis "AndroidX FileProvider compiled from Java source for API 28 and later")
      (description
       "This package builds the AndroidX FileProvider directly from pinned Java
source against the source-generated Android API.  Platform equivalents replace
legacy compatibility calls for devices running API 28 or newer.  Compile-time
annotations are omitted.  URI permissions and canonical path containment remain
upstream, with no dependency on full AndroidX Core, Kotlin or binary Maven jars.
Both the compiled jar and adapted source jar contain the upstream license.")
      (license license:asl2.0))))
