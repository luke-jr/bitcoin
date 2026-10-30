;; Copyright (c) 2026 The Bitcoin Knots developers
;; Distributed under the MIT software license, see the accompanying file COPYING.

(define-module (bitcoin android-signing)
  #:use-module (gnu packages bash)
  #:use-module (bitcoin android-host-jdk)
  #:use-module (guix build-system gnu)
  #:use-module (guix gexp)
  #:use-module (guix git-download)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (guix packages))

(define-public android-apksigner
  (let ((commit "61f88cbe6f81b4536d1ef124daf3caa4ad014afd"))
    (package
      (name "android-apksigner")
      (version (git-version "0.9" "0" commit))
      (source
       (origin
         (method git-fetch)
         (uri (git-reference
               (url "https://android.googlesource.com/platform/tools/apksig")
               (commit commit)))
         (file-name (git-file-name name version))
         (sha256
          (base32 "1n6rm34l7yx0qany7yc6z5k9fna4cs21lqral4ybni7smpwg1049"))))
      (build-system gnu-build-system)
      (arguments
       (list
        #:phases
        #~(modify-phases %standard-phases
            (delete 'configure)
            (replace 'build
              (lambda _
                ;; Match upstream Android.bp: cloud KMS implementations are
                ;; separate optional libraries, not part of the core apksig jar.
                (for-each delete-file-recursively
                          '("src/main/java/com/android/apksig/kms/aws"
                            "src/main/java/com/android/apksig/kms/gcp"))
                ;; Use OpenJDK's providers instead of a Conscrypt binary jar/JNI
                ;; library. Its PSS implementation has the standard JCA name;
                ;; apksig already supplies the SHA-256/SHA-512 PSS parameters.
                (substitute* "src/apksigner/java/com/android/apksigner/ApkSignerTool.java"
                  (("Security.addProvider\\(new org.conscrypt.OpenSSLProvider\\(\\)\\);")
                   "// Use the OpenJDK security providers."))
                (substitute* "src/main/java/com/android/apksig/internal/apk/SignatureAlgorithm.java"
                  (("SHA256withRSA/PSS|SHA512withRSA/PSS") "RSASSA-PSS"))
                (mkdir-p "classes")
                (apply invoke "javac" "--release" "8" "-encoding" "UTF-8"
                       "-d" "classes"
                       (sort (append (find-files "src/main/java" "\\.java$")
                                     (find-files "src/apksigner/java" "\\.java$"))
                             string<?))
                (for-each
                 (lambda (file)
                   (install-file file "classes/com/android/apksigner"))
                 (find-files "src/apksigner/java" "\\.txt$"))
                (with-directory-excursion "classes"
                  ;; Explicit entry ordering and timestamps make the jar
                  ;; independent of directory enumeration and wall-clock time.
                  (apply invoke "jar" "--create" "--file" "../apksigner.jar"
                         "--main-class" "com.android.apksigner.ApkSignerTool"
                         "--no-compress" "--date=1980-01-01T00:00:02Z"
                         (sort (find-files "." "\\.(class|txt)$") string<?)))))
            (replace 'check
              (lambda* (#:key tests? #:allow-other-keys)
                (when tests?
                  (invoke "java" "-jar" "apksigner.jar" "--version")
                  (invoke "java" "-jar" "apksigner.jar" "sign" "--help")
                  (for-each
                   (lambda (fixture)
                     (invoke "java" "-jar" "apksigner.jar" "verify"
                             "--min-sdk-version" "24"
                             (string-append "src/test/resources/com/android/apksig/"
                                            fixture)))
                   '("golden-aligned-v1v2v3-out.apk"
                     "v2-only-with-rsa-pss-sha256-2048.apk"
                     "v2-only-with-ecdsa-sha256-p256.apk"))
                  (when (zero? (system* "java" "-jar" "apksigner.jar" "verify"
                                       "--min-sdk-version" "24"
                                       "src/test/resources/com/android/apksig/v2-only-signatures-and-digests-block-mismatch.apk"))
                    (error "apksigner accepted a corrupt signature fixture")))))
            (replace 'install
              (lambda* (#:key outputs #:allow-other-keys)
                (let* ((out (assoc-ref outputs "out"))
                       (bin (string-append out "/bin"))
                       (jar (string-append out "/share/java/apksigner.jar")))
                  (install-file "apksigner.jar" (dirname jar))
                  (mkdir-p bin)
                  (call-with-output-file (string-append bin "/apksigner")
                    (lambda (port)
                      (format port "#!~a~%exec ~a -jar ~a \"$@\"~%"
                              #$(file-append bash-minimal "/bin/bash")
                              #$(file-append android-openjdk17 "/bin/java") jar)))
                  (chmod (string-append bin "/apksigner") #o755)))))))
      (native-inputs (list (list android-openjdk17 "jdk")))
      (inputs (list bash-minimal android-openjdk17))
      (home-page "https://android.googlesource.com/platform/tools/apksig/")
      (synopsis "Sign and verify Android APKs with a source-built Java tool")
      (description
       "Apksigner signs Android APKs and verifies their signatures.  This package
builds apksig and its command-line tool directly from Java source with OpenJDK.
It supports local keys and certificates without an Android SDK, Gradle, Maven
artifacts, Conscrypt, or optional cloud KMS providers.")
      (license license:asl2.0))))

(define-public android-aab-verifier
  (package
    (name "android-aab-verifier")
    (version "1")
    (source
     (local-file "../../../android/aab-verify.java"))
    (build-system gnu-build-system)
    (arguments
     (list
      #:modules '((guix build gnu-build-system)
                  (guix build utils)
                  (ice-9 popen)
                  (ice-9 rdelim))
      #:phases
      #~(modify-phases %standard-phases
          (replace 'unpack
            (lambda* (#:key source #:allow-other-keys)
              (copy-file source "aab-verify.java")))
          (delete 'configure)
          (replace 'build
            (lambda _
              (invoke "javac" "--release" "17" "-encoding" "UTF-8"
                      "-d" "classes" "aab-verify.java")
              (invoke "jar" "--create" "--file" "aab-verifier.jar"
                      "--main-class" "AabVerifier" "--no-compress"
                      "--date=1980-01-01T00:00:02Z"
                      "-C" "classes" "AabVerifier.class")))
          (replace 'check
            (lambda* (#:key tests? #:allow-other-keys)
              (when tests?
                (mkdir-p "fixture/base/manifest")
                (for-each
                 (lambda (path)
                   (call-with-output-file (string-append "fixture/" path)
                     (lambda (port) (display "fixture" port))))
                 '("BundleConfig.pb" "base/manifest/AndroidManifest.xml"
                   "base/resources.pb"))
                (invoke "jar" "--create" "--file" "fixture.aab"
                        "--no-manifest" "-C" "fixture" ".")
                (invoke "keytool" "-genkeypair" "-noprompt"
                        "-keystore" "fixture.p12" "-storepass" "fixture-password"
                        "-alias" "fixture" "-keyalg" "RSA" "-keysize" "2048"
                        "-dname" "CN=Build fixture" "-validity" "2")
                (invoke "keytool" "-exportcert" "-keystore" "fixture.p12"
                        "-storepass" "fixture-password" "-alias" "fixture"
                        "-file" "fixture.der")
                (invoke "jarsigner" "-keystore" "fixture.p12"
                        "-storepass" "fixture-password" "-sigfile" "KNOTS"
                        "-signedjar" "signed.aab" "fixture.aab" "fixture")
                (let* ((pipe (open-pipe* OPEN_READ "sha256sum" "fixture.der"))
                       (digest (car (string-split (read-line pipe) #\space))))
                  (unless (zero? (close-pipe pipe))
                    (error "Cannot hash fixture certificate"))
                  (invoke "java" "-jar" "aab-verifier.jar" "signed.aab" digest)
                  (call-with-output-file "fixture/base/resources.pb"
                    (lambda (port) (display "tampered fixture" port)))
                  (invoke "jar" "--update" "--file" "signed.aab"
                          "-C" "fixture" "base/resources.pb")
                  (when (zero? (system* "java" "-jar" "aab-verifier.jar"
                                       "signed.aab" digest))
                    (error "AAB verifier accepted a tampered payload"))))))
          (replace 'install
            (lambda* (#:key outputs #:allow-other-keys)
              (let* ((out (assoc-ref outputs "out"))
                     (bin (string-append out "/bin"))
                     (jar (string-append out "/share/java/aab-verifier.jar")))
                (install-file "aab-verifier.jar" (dirname jar))
                (mkdir-p bin)
                (call-with-output-file (string-append bin "/android-aab-verify")
                  (lambda (port)
                    (format port "#!~a~%exec ~a -jar ~a \"$@\"~%"
                            #$(file-append bash-minimal "/bin/bash")
                            #$(file-append android-openjdk17 "/bin/java") jar)))
                (chmod (string-append bin "/android-aab-verify") #o755)))))))
    (native-inputs (list (list android-openjdk17 "jdk")))
    (inputs (list bash-minimal android-openjdk17))
    (home-page "https://bitcoinknots.org/")
    (synopsis "Verify all App Bundle entries against a pinned signing certificate")
    (description
     "This tool uses OpenJDK's JAR signature verifier, reads every entry to EOF,
rejects duplicate names and unsigned payloads, and requires exactly one signer
whose leaf certificate matches an independently supplied SHA-256 digest.  It
needs no Android SDK or binary bundletool distribution.")
    (license license:expat)))
