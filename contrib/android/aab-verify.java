// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying file COPYING.

import java.io.InputStream;
import java.nio.file.Path;
import java.security.CodeSigner;
import java.security.MessageDigest;
import java.security.cert.Certificate;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;

/** Verify every JAR payload entry against an independently pinned leaf certificate. */
class AabVerifier {
    private static boolean signatureEntry(String name) {
        return name.equals("META-INF/MANIFEST.MF") || name.equals("META-INF/KNOTS.SF")
            || name.equals("META-INF/KNOTS.RSA") || name.equals("META-INF/KNOTS.EC")
            || name.equals("META-INF/KNOTS.DSA");
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--help")) {
            System.out.println("Usage: android-aab-verify <signed.aab> <certificate-sha256>");
            return;
        }
        require(args.length == 2, "Expected signed AAB and independent certificate SHA-256");
        String expected = args[1].replace(":", "").toLowerCase(Locale.ROOT);
        require(expected.matches("[0-9a-f]{64}"), "Invalid certificate SHA-256");
        byte[] certificateDigest = java.util.HexFormat.of().parseHex(expected);
        Set<String> names = new HashSet<>();
        int payloads = 0;
        int blocks = 0;
        try (JarFile jar = new JarFile(Path.of(args[0]).toFile(), true)) {
            Enumeration<JarEntry> entries = jar.entries();
            while (entries.hasMoreElements()) {
                JarEntry entry = entries.nextElement();
                String name = entry.getName();
                require(names.add(name), "Duplicate ZIP entry: " + name);
                require(!name.isEmpty() && !name.startsWith("/") && !name.contains("\\")
                    && !name.contains("\u0000"), "Invalid ZIP entry name");
                for (String part : name.split("/")) {
                    require(!part.isEmpty() && !part.equals(".") && !part.equals(".."), "Invalid ZIP path");
                }
                if (entry.isDirectory()) continue;
                // Reading to EOF is essential: JarFile verifies entry digests lazily.
                try (InputStream input = jar.getInputStream(entry)) {
                    byte[] buffer = new byte[65536];
                    while (input.read(buffer) != -1) { }
                }
                if (signatureEntry(name)) {
                    if (name.matches("META-INF/KNOTS\\.(RSA|EC|DSA)")) blocks++;
                    continue;
                }
                CodeSigner[] signers = entry.getCodeSigners();
                require(signers != null && signers.length == 1,
                        "Unsigned entry or unexpected signer count: " + name);
                Certificate certificate = signers[0].getSignerCertPath().getCertificates().get(0);
                byte[] actual = MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded());
                require(MessageDigest.isEqual(actual, certificateDigest),
                        "Unexpected signing certificate: " + name);
                payloads++;
            }
        }
        require(payloads > 0 && blocks == 1 && names.contains("META-INF/MANIFEST.MF")
            && names.contains("META-INF/KNOTS.SF"), "Missing or ambiguous JAR signing metadata");
        require(names.contains("BundleConfig.pb") && names.contains("base/manifest/AndroidManifest.xml")
            && names.contains("base/resources.pb"), "Missing base App Bundle structure");
        System.out.println("AAB signature verified; " + payloads + " entries; certificate SHA-256 " + expected);
    }
}
