;; Copyright (c) 2026 The Bitcoin Knots developers
;; Distributed under the MIT software license, see the accompanying file COPYING.

(define-module (bitcoin android-framework-res)
  #:use-module (bitcoin android-aapt2)
  #:use-module (gnu packages python)
  #:use-module (guix build-system gnu)
  #:use-module (guix download)
  #:use-module (guix gexp)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (guix packages))

(define (framework-xml name hash)
  (origin
    (method url-fetch)
    (uri (string-append
          "https://android.googlesource.com/platform/frameworks/base/+/"
          "99b01a65cc4c104933788b3143285ab6bae65827/core/res/res/values/"
          name "?format=TEXT"))
    (file-name (string-append "android-36-" name ".base64"))
    (sha256 (base32 hash))))

(define build-helper
  (local-file "../../../android/build-framework-res.py"))

(define zip-helper
  (local-file "../../../android/zip.py"))

(define-public android-framework-res-36
  (package
    (name "android-framework-res")
    (version "36")
    (source
     (framework-xml "public-final.xml"
                    "1linnl4ydi34fnqn3lwdwh3i4pbc87pxzn1m00bc5vmfl8pwbc22"))
    (build-system gnu-build-system)
    (arguments
     (list
      #:phases
      #~(modify-phases %standard-phases
          (replace 'unpack
            (lambda* (#:key source inputs #:allow-other-keys)
              (define (decode input output)
                (invoke "python3" "-c"
                        "import base64,pathlib,sys; pathlib.Path(sys.argv[2]).write_bytes(base64.b64decode(pathlib.Path(sys.argv[1]).read_bytes()))"
                        input output))
              (mkdir "source")
              (chdir "source")
              (decode source "public-final.xml")
              (decode (assoc-ref inputs "attrs-source") "attrs.xml")
              (decode (assoc-ref inputs "manifest-attrs-source") "attrs_manifest.xml")
              ;; Keep the canonical ZIP helper adjacent to its importing script.
              (copy-file #$build-helper "build-framework-res.py")
              (copy-file #$zip-helper "zip.py")))
          (delete 'configure)
          (replace 'build
            (lambda _
              (invoke "python3" "build-framework-res.py"
                      "--public" "public-final.xml"
                      "--attrs" "attrs.xml" "--attrs" "attrs_manifest.xml"
                      "--output" "framework-res.apk"
                      "--ids-output" "public-ids.json")))
          (replace 'check
            (lambda* (#:key tests? #:allow-other-keys)
              (when tests?
                ;; Each generation also compares every compiled public ID with
                ;; public-final.xml. Independent work directories must agree.
                (invoke "python3" "build-framework-res.py"
                        "--public" "public-final.xml"
                        "--attrs" "attrs.xml" "--attrs" "attrs_manifest.xml"
                        "--output" "framework-res-second.apk")
                (invoke "cmp" "framework-res.apk" "framework-res-second.apk")
                (mkdir-p "smoke/res/values")
                (call-with-output-file "smoke/AndroidManifest.xml"
                  (lambda (port)
                    (display "<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\" package=\"org.bitcoinknots.frameworkfixture\"><application android:theme=\"@style/AppTheme\"><service android:name=\".Service\" android:foregroundServiceType=\"dataSync|specialUse\"/></application></manifest>\n" port)))
                (call-with-output-file "smoke/res/values/styles.xml"
                  (lambda (port)
                    (display "<resources><style name=\"AppTheme\" parent=\"@android:style/Theme.Material.Light.NoActionBar\"><item name=\"android:colorAccent\">@android:color/holo_blue_light</item></style></resources>\n" port)))
                (invoke "aapt2" "compile" "--dir" "smoke/res"
                        "-o" "smoke/compiled.zip")
                (invoke "aapt2" "link" "-I" "framework-res.apk"
                        "--manifest" "smoke/AndroidManifest.xml"
                        "--min-sdk-version" "28" "--target-sdk-version" "36"
                        "-o" "smoke/app.apk" "smoke/compiled.zip")
                (invoke "aapt2" "link" "--proto-format" "-I" "framework-res.apk"
                        "--manifest" "smoke/AndroidManifest.xml"
                        "--min-sdk-version" "28" "--target-sdk-version" "36"
                        "-o" "smoke/proto.apk" "smoke/compiled.zip")
                ;; Framework values must remain references to the device's real
                ;; resources, rather than inheriting compile-time placeholders.
                (invoke "python3" "-c"
                        "import subprocess; r=subprocess.check_output(['aapt2','dump','resources','smoke/app.apk'],text=True); x=subprocess.check_output(['aapt2','dump','xmltree','smoke/app.apk','--file','AndroidManifest.xml'],text=True); assert '@0x01060012' in r; assert 'foregroundServiceType(0x01010599)=0x40000001' in x")
                (call-with-output-file "smoke/res/values/styles.xml"
                  (lambda (port)
                    (display "<resources><style name=\"AppTheme\"><item name=\"android:layout_rowSpan\">0</item></style></resources>\n" port)))
                (invoke "aapt2" "compile" "--dir" "smoke/res"
                        "-o" "smoke/invalid.zip")
                (invoke "python3" "-c"
                        "import subprocess; r=subprocess.run(['aapt2','link','-I','framework-res.apk','--manifest','smoke/AndroidManifest.xml','-o','smoke/invalid.apk','smoke/invalid.zip'],capture_output=True,text=True); assert r.returncode != 0; assert 'less than minimum integer 1' in r.stderr"))))
          (replace 'install
            (lambda* (#:key outputs #:allow-other-keys)
              (let ((directory
                     (string-append (assoc-ref outputs "out")
                                    "/share/android/platforms/android-36")))
                (install-file "framework-res.apk" directory)
                (install-file "public-ids.json" directory)))))))
    (native-inputs
     (list (list "python" python-minimal)
           (list "aapt2" android-aapt2)
           (list "attrs-source"
                 (framework-xml "attrs.xml"
                                "03sdbjah98nvkj75s4qz9j15b4h210pfz2hf8dsd31m73qkmbfx0"))
           (list "manifest-attrs-source"
                 (framework-xml "attrs_manifest.xml"
                                "15yg4v4bxrfyzx3iqs37518n409bqnpcfdsaxxyxfkragy8lrasy"))))
    (home-page "https://android.googlesource.com/platform/frameworks/base/")
    (synopsis "Source-generated Android 36 compile-time framework resource table")
    (description
     "This package builds an Android 36 framework resource include using the
source public ID declarations and attribute formats, enum values, flags and range
constraints. Other resources contain compile-time placeholders. The table is for
AAPT2 -I or merging into a source-built android.jar; it must never be installed on
a device or included as application resource content. Public IDs are checked
against source, including a modern manifest flag and external-reference test.")
    (license license:asl2.0)))
