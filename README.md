# dskpp-otp

Provision **Nexus Personal (DSKPP) OTP profiles** into standard
`otpauth://` URIs, so you can use a **free software authenticator** instead
of a proprietary banking app.

This is a provisioning-time interoperability tool. It performs the same DSKPP
exchange the banking app performs — using an activation link and PIN **you**
obtained yourself — and emits a standard TOTP/HOTP URI and QR code. The result
can be imported into Aegis, FreeOTP, 2FAS, KeePassXC, `pass-otp`, and any other
authenticator that understands `otpauth://`.

> **Status:** experimental. The exchange is single-use and rotates the
> server-side key. Read [Security and limitations](#security-and-limitations)
> before using it.

---

## Why

A number of banks ship a mandatory "soft token" app built on the **Nexus
Personal** SDK. These apps typically:

- generate standard TOTP/HOTP codes internally,
- store the seed in app-private, SQLCipher-encrypted storage whose key is
  wrapped by the Android Keystore,
- offer **no export** and no way to use another authenticator.

The practical effect is lock-in: you must install and keep a proprietary app to
log in, even though the underlying OTP is a standard algorithm. This tool
removes that lock-in at the only point where the seed is legitimately available
to you: **activation**.

YES Bank's **YES Secure Next** (`com.yesbank.and.yessecurenext`) is one
example. It uses the Nexus Personal SDK and provisions a TOTP profile with
SHA-512, 6 digits and a 30-second period. The tool is written generically; the
bank, package, scheme and profile parameters are configuration.

## Software freedom

The point is not merely convenience. Your second factor is a credential you
control, and it should be usable in software you can inspect, modify, run and
share. A mandatory proprietary soft-token app makes that impossible: you cannot
audit it, replace it, or move your own seed to another device. This tool
performs the standard DSKPP provisioning exchange at activation time and hands
you a standard `otpauth://` URI, so the second factor can live in **free
software** such as Aegis, FreeOTP, 2FAS, KeePassXC or `pass-otp` (free as in
freedom; several of these are also gratis).

## What it is, and what it is not

**It is:**

- a provisioning-time DSKPP client;
- a way to turn a fresh activation link + activation PIN into an
  `otpauth://` URI;
- compatible with free software authenticators;
- root-free and app-modification-free.

**It is not:**

- an extractor for an already-provisioned app. There is no supported way to
  read the seed out of `SQLCipher` + AndroidKeyStore storage without root or
  runtime instrumentation; this tool does not attempt it;
- a PIN bypass. It uses the activation PIN, exactly as the app does;
- a way to obtain activation links or PINs. Those are manual, bank-issued
  credentials;
- a modification, repackaging or redistribution of the app or the SDK.

## How it works

1. The bank's activation page hands you a link like
   `https://<bank-host>/?oath_url=<app-scheme>://<bank-host>/dskpp/v1/post?u=<user>&ac=<code>`.
2. The app rewrites the scheme to the SDK's `com.nexusgroup.dskpp` and performs a
   DSKPP (RFC 6063) exchange with the bank. The shared key is derived from the
   **PIN + user ID + activation code + a fixed salt** — not from the device.
3. This tool performs the same exchange. It runs a tiny harness with
   `app_process` (shell UID) that loads the Nexus Personal classes **from your
   installed app** and delegates to them. No root, no app changes, no SDK code
   in this repository.
4. The returned profile (seed, algorithm, digits, period, issuer) is written as
   a standard `otpauth://` URI and a QR PNG.

The exchange is single-use: completing it consumes the activation code and
rotates the server-side key. The banking app's existing local profile will stop
matching. That is the point — you are moving the profile to the authenticator
you choose.

See [PROTOCOL.md](PROTOCOL.md) for the full protocol notes.

## Requirements

- Linux/macOS with Python 3.9+;
- `adb` with the phone authorised (USB or wireless debugging);
- the banking app **installed** on the phone (its SDK classes are used at
  runtime; the app does not need to be running or unlocked);
- **no root**;
- optional: `qrencode` (or the Python `qrcode` package) for the QR PNG;
- optional: `pass` + `pass-otp` if you want to store the URI in `pass`.

The harness (`harness/harness.jar`) is built for Android 9+ (API 28+). It is
prebuilt in the repository; `harness/build.sh` rebuilds it from source.

## Quick start (YES Bank example)

Obtain an activation link from YES Bank's Secure Next page yourself. Save it to
a file, and save the activation PIN to another file:

```bash
# link.txt contains the bank's activation URL
# pin.txt contains the activation PIN (6 digits for YES Secure Next)
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

Import the QR/URI into your chosen authenticator. For a free software setup:

- **Aegis Authenticator** — scan the QR or import the URI;
- **FreeOTP** — scan the QR;
- **2FAS** — scan the QR;
- **KeePassXC** — add a TOTP entry and paste the URI/secret;
- **pass-otp** — see below.

Do not open the activation link in the banking app first; that consumes it.

## `pass-otp`

`pass-otp` stores the full URI, so it preserves the algorithm (SHA-1/SHA-256/
SHA-512) and period:

```bash
python3 dskpp_otp.py \
    --package com.yesbank.and.yessecurenext \
    --link-file link.txt --pin-file pin.txt \
    --out /tmp/yes-otp --store-pass bank/yes_secure_next

pass otp uri -q bank/yes_secure_next   # show the QR
pass otp bank/yes_secure_next          # generate a code
```

`pass otp insert --secret` assumes SHA-1 and 6/30 defaults; use the full URI
(as this tool does) for SHA-256/SHA-512 profiles.

## Options

| Option | Meaning |
|---|---|
| `--package` | Installed package that bundles the Nexus Personal SDK |
| `--link-file` | File containing the activation URL (recommended) |
| `--link` | Activation URL as a string (visible in `ps`/history) |
| `--pin-file` | File containing the activation PIN (recommended) |
| `--pin` | PIN as a string (visible in `ps`/history) |
| `--scheme` | DSKPP scheme expected by the SDK (default `com.nexusgroup.dskpp`) |
| `--out` | Output prefix (default `dskpp-otp`) |
| `--qr` / `--no-qr` | Generate a QR PNG (default: yes) |
| `--print-uri` | Print the URI (contains the secret) |
| `--store-pass NAME` | Insert into `pass` under `NAME` |
| `--dry-run` | Normalize the link and show the plan without contacting anything |
| `--serial` | ADB serial for multiple devices |
| `--debug` | Show adb commands |
| `--keep-temp` | Keep the on-device temp dir (contains secrets; debugging only) |

## Security and limitations

- **Use only your own account and your own credentials.** The activation link
  and PIN are sensitive; treat them like passwords.
- **The link is single-use.** If you see `The Url has expired or consumed`,
  generate a new link. Opening the link in the app first also consumes it.
- **The exchange rotates the key.** The banking app's existing profile will
  stop producing valid codes. Do not run this unless you intend to move the
  profile to another authenticator.
- **The PIN must be the activation PIN**, not a PIN changed later in the app.
  A local PIN change re-encrypts the existing seed; the DSKPP exchange still
  expects the original activation PIN.
- **Algorithm support varies.** SHA-1 profiles work almost everywhere;
  SHA-256/SHA-512 profiles need an authenticator that supports them (Aegis,
  2FAS, FreeOTP, KeePassXC, recent Google Authenticator). YES Bank currently
  provisions SHA-512, so check your authenticator before starting.
- **Secrets on disk.** The URI and QR files are written `0600`; the PIN is read
  from a file or prompt. Delete/shred the PIN file and temporary outputs after
  importing. Avoid `--print-uri` unless you need it.
- **No root, no app modification.** The harness only executes the SDK that is
  already installed, in the shell UID. It cannot read the app's private data.
- **Not affiliated** with Nexus Group, YES Bank, or any bank. No warranty.
  Comply with your bank's terms and local law.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `The Url has expired or consumed` | Single-use link already used; generate a new one |
| `ClassNotFoundException` / `NoClassDefFoundError` | Wrong `--package`, app not installed, or SDK in an unexpected split |
| `NoSuchMethodError` | App/SDK version changed; update the harness stubs and rebuild |
| `No JCE provider found` | The app does not bundle BouncyCastle; the SDK needs a JCE provider |
| `No implementation found for SystemProperties` | You are running the harness with `dalvikvm`; use `app_process` (the script does) |
| Process prints `Killed` | Older harness/uncaught exception; rebuild `harness.jar` |
| Authenticator rejects the code | Algorithm mismatch (SHA-1 vs SHA-256/512) or wrong PIN/link |
| `pass otp` says unsupported | Use the full URI, not `--secret`; check `oathtool` support for SHA-512 |

## Protocol notes

Standards: [RFC 6063 (DSKPP)](https://datatracker.ietf.org/doc/html/rfc6063),
[RFC 6030 (PSKC)](https://datatracker.ietf.org/doc/html/rfc6030),
[RFC 4226 (HOTP)](https://datatracker.ietf.org/doc/html/rfc4226),
[RFC 6238 (TOTP)](https://datatracker.ietf.org/doc/html/rfc6238),
[RFC 8018 (PBKDF2)](https://datatracker.ietf.org/doc/html/rfc8018).

See [PROTOCOL.md](PROTOCOL.md) for:

- the activation URL shapes and the `u`/`ac` handling;
- the DSKPP message flow (ClientHello → ServerHello → ClientNonce →
  ServerFinished);
- the PIN-derived key schedule;
- profile fields and the `otpauth://` mapping;
- why the key is device-independent;
- why extracting an installed profile is out of scope.

## Repository layout

```
dskpp_otp.py              # orchestrator (Python, stdlib only)
harness/
  harness.jar             # prebuilt dex (our Harness class only)
  build.sh                # rebuild with javac + d8/r8
  src/Harness.java        # calls the installed SDK's DskppActivation
  stubs/                  # compile-time API stubs (no implementation)
PROTOCOL.md
LICENSE
```

The harness jar contains **only** the `Harness` class. It references the SDK's
`DskppActivation` by name and resolves it from the installed APK at runtime.

## License

MIT for this repository's code and documentation. No SDK, APK, bank code, or
user data is included or redistributed. See [NOTICE](NOTICE).
