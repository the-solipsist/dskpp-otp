// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Pranesh Prakash

import com.nexusgroup.personal.sdk.java.crypto.CryptoHashes;
import com.nexusgroup.personal.sdk.java.otp.SDKOTPProvisioningProfile;
import com.nexusgroup.personal.sdk.java.otp.dskpp.DskppActivation;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.Provider;
import java.security.Security;

/**
 * Runs the Nexus Personal DSKPP client that is bundled in an installed app.
 *
 * This class is deliberately tiny and contains no Nexus code: it is compiled
 * against the minimal stubs in harness/stubs and executed with app_process so
 * that the real classes are loaded from the installed APK at runtime.
 */
public final class Harness {
    private static final String SDK_SCHEME = "com.nexusgroup.dskpp";

    private Harness() {
    }

    public static void main(String[] args) {
        try {
            run(args);
        } catch (Throwable t) {
            System.err.println("ERROR " + t.getClass().getName() + ": " + t.getMessage());
            System.exit(1);
        }
    }

    private static void run(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("usage: Harness <activation-url-file> <pin-file> <seed-out> [meta-out]");
            System.exit(2);
        }

        String raw = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8).trim();
        String pin = new String(Files.readAllBytes(Paths.get(args[1])), StandardCharsets.UTF_8).trim();

        java.net.URI uri = java.net.URI.create(raw);
        String url = raw;
        if (!SDK_SCHEME.equals(uri.getScheme())) {
            url = SDK_SCHEME + raw.substring(raw.indexOf(':'));
        }

        Provider provider = null;
        try {
            provider = (Provider) Class.forName("org.bouncycastle.jce.provider.BouncyCastleProvider")
                    .getDeclaredConstructor().newInstance();
        } catch (Throwable ignored) {
            provider = Security.getProvider("BC");
            if (provider == null) {
                provider = Security.getProvider("SUN");
            }
        }
        if (provider == null) {
            throw new IllegalStateException("No JCE provider found (BouncyCastle/SUN)");
        }
        Security.addProvider(provider);

        DskppActivation activation = new DskppActivation(url, pin, new CryptoHashes(provider));
        SDKOTPProvisioningProfile profile = activation.sdkOTPProvisioningProfile();

        // Save the seed before touching any metadata: a getter mismatch must
        // never cost a single-use activation code.
        String seed = profile.getSeed();
        Files.write(Paths.get(args[2]), ("seed=" + seed + "\n").getBytes(StandardCharsets.UTF_8));
        System.err.println("SEED_SAVED len=" + (seed == null ? -1 : seed.length()));

        if (args.length > 3) {
            StringBuilder sb = new StringBuilder();
            String[] names = {"getId", "getUserId", "getDisplayName", "getIssuer",
                              "getDigits", "getPeriod", "getAlgorithm", "getType",
                              "getCounter", "getKeyLen"};
            for (String name : names) {
                try {
                    Method method = profile.getClass().getMethod(name);
                    sb.append(name).append('=').append(String.valueOf(method.invoke(profile))).append('\n');
                } catch (Throwable t) {
                    sb.append(name).append("=ERR:").append(t.getClass().getSimpleName()).append('\n');
                }
            }
            Files.write(Paths.get(args[3]), sb.toString().getBytes(StandardCharsets.UTF_8));
        }
    }
}
