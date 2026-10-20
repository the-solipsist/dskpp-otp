# dskpp-otp

`dskpp-otp` takes a fresh activation link and activation PIN from a bank that
uses the Nexus Personal SDK, runs the DSKPP provisioning exchange, and writes
the result as a standard `otpauth://` URI and QR code. You can import that into
a free software authenticator and stop using the bank's app.

This is an experimental provisioning-time tool. The activation link is
single-use and completing the exchange rotates the server-side key. Read
[Security and limitations](#security-and-limitations) before you start.

## Why

Some banks require a soft-token app built on the Nexus Personal SDK. The app
generates standard TOTP or HOTP codes, but the seed lives in a SQLCipher
database whose key is wrapped by the Android Keystore. The app has no export.
If you want to log in, you have to keep that app installed.

The seed is available at activation, before the app stores it. The bank gives
you a link and a PIN; the app exchanges them for a profile. This tool performs
the same exchange and writes the profile as an `otpauth://` URI. After that,
any authenticator that understands the URI can generate the codes.

YES Bank's YES Secure Next (`com.yesbank.and.yessecurenext`) is one example. At
the time of writing it provisions a TOTP profile with SHA-512, six digits and a
30-second period. The tool is not tied to YES Bank: the package, scheme and
profile parameters are configuration.

## Free software

Your second factor is a credential you own. It should work in software you can
read, change, and run where you like. A proprietary token app keeps the seed in
private storage, cannot be audited, and offers no export. This tool exists so
the credential can live in free software such as
[Aegis](https://github.com/beemdevelopment/Aegis),
[FreeOTP](https://github.com/freeotp/freeotp-android),
[2FAS](https://github.com/twofas/2fas-android),
[KeePassXC](https://keepassxc.org/), or
[pass-otp](https://github.com/tadfisher/pass-otp).

## Scope

The tool:

- runs the DSKPP exchange at activation time;
- turns an activation link and PIN into an `otpauth://` URI and QR code;
- works with free software authenticators;
- runs as the shell user, without root and without modifying the app.

It does not:

- extract a seed from an app that is already provisioned. That requires root
  or runtime instrumentation because of SQLCipher and the Keystore;
- bypass the PIN;
- obtain activation links or PINs;
- modify, repackage, or redistribute the app or the SDK.

## How it works

1. The bank's activation page gives you a link like
   `https://<bank-host>/?oath_url=<app-scheme>://<bank-host>/dskpp/v1/post?u=<user>&ac=<code>`.
2. The app rewrites the scheme to `com.nexusgroup.dskpp` and performs a DSKPP
   exchange ([RFC 6063](https://datatracker.ietf.org/doc/html/rfc6063)) with
   the bank. The shared key comes from the PIN, user ID, activation code and a
   fixed salt. It does not depend on the device.
3. This tool runs the same exchange. A small harness runs under
   `app_process` as the shell user and loads the Nexus Personal classes from
   the installed app. The app is not modified, and no SDK code is included in
   this repository.
4. The profile (seed, algorithm, digits, period, issuer) is written as an
   `otpauth://` URI and a QR PNG.

The exchange is single-use. Completing it consumes the activation code and
rotates the server-side key, so the app's existing profile stops matching. That
is expected when you move the profile to another authenticator.

See [PROTOCOL.md](PROTOCOL.md) for the protocol details.

## Requirements

- Linux or macOS with Python 3.9 or newer;
- [`adb`](https://developer.android.com/tools/adb) with the phone authorised
  (USB or wireless debugging);
- the banking app installed on the phone. Its SDK classes are loaded at
  runtime; the app does not need to be running or unlocked;
- no root;
- optional: [`qrencode`](https://fukuchi.org/works/qrencode/) or the Python
  [`qrcode`](https://github.com/lincolnloop/python-qrcode) package for the QR
  PNG;
- optional: [`pass`](https://www.passwordstore.org/) and
  [`pass-otp`](https://github.com/tadfisher/pass-otp) if you want to store the
  URI in `pass`.

The harness (`harness/harness.jar`) is built for Android 9 (API 28) and newer.
It is prebuilt in the repository; `harness/build.sh` rebuilds it from source.

## Quick start (YES Bank example)

Get an activation link from YES Bank's Secure Next page. Save it to a file, and
save the activation PIN to another file:

```bash
# link.txt contains the bank's activation URL
# pin.txt contains the activation PIN (six digits for YES Secure Next)
chmod 600 link.txt pin.txt

python3 dskpp_otp.py \
    --package com.yesbank.and.yessecurenext \
    --link-file link.txt \
    --pin-file pin.txt \
    --out yes-secure-next
```

Output:

```
yes-secure-next.otpauth.txt   # 0600, standard otpauth:// URI
yes-secure-next.png           # 0600, QR code
```

Import the QR or URI into your chosen authenticator. For a free software setup:

- [Aegis Authenticator](https://github.com/beemdevelopment/Aegis): scan the QR
  or import the URI;
- [FreeOTP](https://github.com/freeotp/freeotp-android): scan the QR;
- [2FAS](https://github.com/twofas/2fas-android): scan the QR;
- [KeePassXC](https://keepassxc.org/): add a TOTP entry and paste the URI or
  secret;
- [pass-otp](https://github.com/tadfisher/pass-otp): see below.

Do not open the activation link in the banking app first. That consumes it.

## `pass-otp`

[`pass-otp`](https://github.com/tadfisher/pass-otp) (with
[`pass`](https://www.passwordstore.org/)) stores the full URI, so it keeps the
algorithm (SHA-1, SHA-256 or SHA-512) and the period:

```bash
python3 dskpp_otp.py \
    --package com.yesbank.and.yessecurenext \
    --link-file link.txt --pin-file pin.txt \
    --out /tmp/yes-otp --store-pass bank/yes_secure_next

pass otp uri -q bank/yes_secure_next   # show the QR
pass otp bank/yes_secure_next          # generate a code
```

`pass otp insert --secret` assumes SHA-1 and the 6/30 defaults. Use the full
URI, as this tool does, for SHA-256 or SHA-512 profiles.

## Options

| Option | Meaning |
|---|---|
| `--package` | Installed package that bundles the Nexus Personal SDK |
| `--link-file` | File containing the activation URL (recommended) |
| `--link` | Activation URL as a string (visible in `ps` and shell history) |
| `--pin-file` | File containing the activation PIN (recommended) |
| `--pin` | PIN as a string (visible in `ps` and shell history) |
| `--scheme` | DSKPP scheme expected by the SDK (default `com.nexusgroup.dskpp`) |
| `--out` | Output prefix (default `dskpp-otp`) |
| `--qr` / `--no-qr` | Generate a QR PNG (default: yes) |
| `--print-uri` | Print the URI (contains the secret) |
| `--store-pass NAME` | Insert into `pass` under `NAME` |
| `--dry-run` | Normalize the link and show the plan without contacting anything |
| `--serial` | ADB serial for multiple devices |
| `--debug` | Show adb commands |
| `--keep-temp` | Keep the on-device temp directory (contains secrets; debugging only) |

## Security and limitations

- Use your own account and credentials. The activation link and PIN are
  sensitive; treat them like passwords.
- The link is single-use. If you see `The Url has expired or consumed`,
  generate a new link. Opening the link in the app first also consumes it.
- The exchange rotates the key. The bank app's existing profile will stop
  producing valid codes. Do not run this unless you intend to move the profile
  to another authenticator.
- The PIN must be the activation PIN, not one you changed later in the app. A
  local PIN change re-encrypts the existing seed; the DSKPP exchange still
  expects the original activation PIN.
- Algorithm support varies. SHA-1 profiles work almost everywhere. SHA-256 and
  SHA-512 profiles need an authenticator that supports them (Aegis, 2FAS,
  FreeOTP, KeePassXC, recent Google Authenticator). At the time of writing, YES
  Bank provisions SHA-512, so check your authenticator before you start.
- Secrets on disk. The URI and QR are written with mode 0600. The PIN is read
  from a file or a prompt. Delete or shred the PIN file and the temporary
  outputs after importing. Avoid `--print-uri` unless you need it.
- No root and no app modification. The harness runs the SDK that is already
  installed, as the shell user. It cannot read the app's private data.
- Not affiliated with Nexus Group, YES Bank, or any bank. No warranty. Comply
  with your bank's terms and local law.

## Troubleshooting

| Symptom | Cause or fix |
|---|---|
| `The Url has expired or consumed` | The single-use link was already used; generate a new one |
| `ClassNotFoundException` or `NoClassDefFoundError` | Wrong `--package`, app not installed, or the SDK is in an unexpected split |
| `NoSuchMethodError` | The app or SDK version changed; update the harness stubs and rebuild |
| `No JCE provider found` | The app does not bundle BouncyCastle; the SDK needs a JCE provider |
| `No implementation found for SystemProperties` | The harness is running under `dalvikvm`; use `app_process` (the script does) |
| The process prints `Killed` | The harness hit an uncaught exception; rebuild `harness.jar` |
| The authenticator rejects the code | Algorithm mismatch (SHA-1 vs SHA-256/512) or a wrong PIN or link |
| `pass otp` says the algorithm is unsupported | Use the full URI, not `--secret`, and check [`oathtool`](https://www.nongnu.org/oath-toolkit/) support for SHA-512 |

## Protocol notes

Standards: [RFC 6063 (DSKPP)](https://datatracker.ietf.org/doc/html/rfc6063),
[RFC 6030 (PSKC)](https://datatracker.ietf.org/doc/html/rfc6030),
[RFC 4226 (HOTP)](https://datatracker.ietf.org/doc/html/rfc4226),
[RFC 6238 (TOTP)](https://datatracker.ietf.org/doc/html/rfc6238),
[RFC 8018 (PBKDF2)](https://datatracker.ietf.org/doc/html/rfc8018).

See [PROTOCOL.md](PROTOCOL.md) for:

- the activation URL shapes and how `u` and `ac` are handled;
- the DSKPP message flow (ClientHello, ServerHello, ClientNonce,
  ServerFinished);
- the PIN-derived key schedule;
- profile fields and the `otpauth://` mapping;
- why the key is device-independent;
- why extracting an installed profile is out of scope.

## Related projects and tools

Free software authenticators:
[Aegis](https://github.com/beemdevelopment/Aegis),
[FreeOTP](https://github.com/freeotp/freeotp-android),
[2FAS](https://github.com/twofas/2fas-android),
[KeePassXC](https://keepassxc.org/).

Password-store integration: [pass](https://www.passwordstore.org/),
[pass-otp](https://github.com/tadfisher/pass-otp).

Android and OTP tooling: [adb](https://developer.android.com/tools/adb),
[qrencode](https://fukuchi.org/works/qrencode/),
[oathtool](https://www.nongnu.org/oath-toolkit/),
[python-qrcode](https://github.com/lincolnloop/python-qrcode).

## Repository layout

```
dskpp_otp.py              # orchestrator (Python, standard library only)
harness/
  harness.jar             # prebuilt dex (our Harness class only)
  build.sh                # rebuild with javac and d8 or r8
  src/Harness.java        # calls the installed SDK's DskppActivation
  stubs/                  # compile-time API stubs (no implementation)
PROTOCOL.md
LICENSE
```

The harness jar contains only the `Harness` class. It refers to the SDK's
`DskppActivation` by name and resolves it from the installed APK at runtime.

## License

MIT for this repository's code and documentation. No SDK, APK, bank code, or
user data is included or redistributed. See [NOTICE](NOTICE).
