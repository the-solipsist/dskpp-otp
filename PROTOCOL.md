# Protocol notes: Nexus Personal DSKPP OTP provisioning

This document describes the interoperability surface used by `dskpp-otp`.
It is based on observing a Nexus Personal SDK-based app performing its normal
provisioning flow. It contains no SDK code, no bank code, no APK and no
credentials. The proprietary `DskppActivation` class is not reimplemented
here; the reference harness delegates to the copy already installed on the
user's device.

The protocol is DSKPP ([RFC 6063](https://datatracker.ietf.org/doc/html/rfc6063))
with a PIN-derived key and a PSKC key package
([RFC 6030](https://datatracker.ietf.org/doc/html/rfc6030)), wrapped in the
Nexus XML messages.

## 1. Activation URL

The bank's activation page produces a URL of the form:

```
https://<bank-host>/?oath_url=<app-scheme>://<bank-host>/dskpp/v1/post?u=<user-id>&ac=<activation-code>
```

Two details matter:

- `u` is the provisioning user identifier and `ac` is the single-use
  activation code.
- The `ac` parameter is frequently outside the `oath_url` value (the outer
  query), because `&` terminates the `oath_url` value. It must be appended to
  the inner URL before the SDK sees it.

The app's JavaScript rewrites the app scheme (`yessecurenext` for YES Bank's
YES Secure Next) to the SDK scheme:

```
<app-scheme>://<bank-host>/dskpp/v1/post?u=...&ac=...
        |
        v
com.nexusgroup.dskpp://<bank-host>/dskpp/v1/post?u=...&ac=...
```

The SDK then replaces the scheme with `https` (the host and path are
preserved) and POSTs the DSKPP messages to:

```
https://<bank-host>/dskpp/v1/post?u=...&ac=...
```

`dskpp_otp.py` accepts either the outer page URL or the inner
`<app-scheme>://...` URL and produces the `com.nexusgroup.dskpp://...` form.

## 2. SDK entry point

The relevant public surface is:

```java
DskppActivation(url, activationPin, cryptoHashes)
    .sdkOTPProvisioningProfile()
```

The returned `SDKOTPProvisioningProfile` carries:

| Field | Meaning |
|---|---|
| `id` | profile identifier |
| `userId` | provisioning user id (the `u` parameter) |
| `displayName` | display name |
| `issuer` | issuer / server name |
| `type` | `TOTP` or `HOTP` |
| `algorithm` | `SHA1`, `SHA256`, `SHA512` |
| `digits` | OTP length |
| `period` | TOTP period in seconds |
| `counter` | HOTP counter (HOTP only) |
| `keyLen` | seed length in bits |
| `seed` | Base32 seed |

`DskppActivation` performs the whole exchange (including the HTTP POSTs) and
returns the decrypted profile. It is proprietary; the harness calls it rather
than copying it.

## 3. Message flow

The exchange is the standard four-pass DSKPP flow:

```
client                                          server
  |  KeyProvClientHello (XML)                       |
  |----------------------------------------------->|
  |  KeyProvServerHello (Status=Continue,           |
  |    SessionID, Nonce)                            |
  |<-----------------------------------------------|
  |  KeyProvClientNonce (MAC over client nonce)     |
  |----------------------------------------------->|
  |  KeyProvServerFinished (PSKC key package + MAC) |
  |<-----------------------------------------------|
```

Status codes observed: `Continue`, `Success`, `AccessDenied`,
`AuthenticationDataInvalid`. A consumed activation code returns an error at
the final step (the client reports `The Url has expired or consumed`,
error code 53).

The XML uses the DSKPP namespace
`urn:ietf:params:xml:ns:keyprov:dskpp`, with PSKC
(`urn:ietf:params:xml:ns:keyprov:pskc`), XML Encryption
(`http://www.w3.org/2001/04/xmlenc#`), XML DSig
(`http://www.w3.org/2000/09/xmldsig#`) and Nexus' own extension namespace.
The ClientHello advertises supported MAC/encryption algorithms, key types,
key packages and the four-pass protocol variant.

## 4. Key schedule

The shared key is derived only from values that the client and server both
know. No device identifier enters the key derivation.

Observed parameters:

- Salt prefix: the literal ASCII string `Key generation`, followed by the
  user id:
  `salt = "Key generation" || userId`.
- `PBKDF2Parameters(pin, salt, activationCode)`:
  - password: the activation PIN (UTF-8),
  - salt: the value above,
  - PBKDF2 "code"/pepper: the activation code,
  - default iterations: 10,000,
  - derived length: 16 bytes.
- The KAC (key authentication code) uses
  `salt = authMacNonce || clientNonce`, 100,000 PBKDF2 iterations and
  HMAC-SHA-256.
- The KProv derivation produces 64 bytes of key data, a 32-byte MAC key and a
  20-byte token (`KProv` splits the PRF output into `KData`, `KMac`, `token`).
- Message MACs cover the user id, the activation URL, the message MAC and the
  MAC key.

The exact XML element ordering and attribute names are those emitted by the
SDK. A from-scratch client must reproduce them; the reference implementation
avoids that by invoking the SDK.

## 5. Why this works at provisioning time

The seed is delivered by the server inside the PSKC key package, encrypted
under the PIN-derived key. Anyone who holds the activation URL (including its
single-use code) and the activation PIN can perform the exchange. That is why
the tool therefore only works at provisioning time.

After the profile exists, the app stores it in a SQLCipher database whose
passphrase is sealed by an AndroidKeyStore key. The seed itself is additionally
encrypted with a PIN-derived key. Reading it from the installed app therefore
requires code execution inside the app's UID (root/Frida) and is explicitly out
of scope. There is no file-copy or ADB-only extraction path.

## 6. Mapping to `otpauth://`

`dskpp_otp.py` maps the profile as follows:

```
otpauth://totp/<issuer>:<account>?secret=<seed>&issuer=<issuer>
    &algorithm=<SHA1|SHA256|SHA512>&digits=<digits>&period=<period>
```

For HOTP, the scheme is `hotp` and the `counter` parameter is included. The
`seed` is the Base32 string returned by the SDK. Authenticators that only
implement SHA-1 (older Google Authenticator versions) cannot use SHA-256/SHA-512
profiles; Aegis, FreeOTP, 2FAS, KeePassXC and recent Google Authenticator can.

## 7. Reference harness

`harness/Harness.java` is small:

1. read the activation URL and PIN from files (never argv, to keep them out of
   `ps`);
2. rewrite the scheme to `com.nexusgroup.dskpp` if needed;
3. construct `DskppActivation` and call `sdkOTPProvisioningProfile()`;
4. write the seed before reading any other profile field;
5. write metadata via reflection (so a changed SDK getter cannot prevent the
   seed from being saved).

It is executed as:

```bash
CLASSPATH=harness.jar:<base.apk>[:<split.apk>...] \
  /system/bin/app_process /system/bin Harness <url-file> <pin-file> <seed-out> <meta-out>
```

`app_process` (not `dalvikvm`) is required so that `android.util.Xml` and the
other framework JNI bindings are initialised. The shell UID can read the
installed APK and reach the network; no root is involved.

## 8. References

- [RFC 6063: DSKPP (Key Provisioning)](https://datatracker.ietf.org/doc/html/rfc6063)
- [RFC 6030: PSKC](https://datatracker.ietf.org/doc/html/rfc6030)
- [RFC 4226: HOTP](https://datatracker.ietf.org/doc/html/rfc4226)
- [RFC 6238: TOTP](https://datatracker.ietf.org/doc/html/rfc6238)
- [RFC 2898: PBKDF2](https://datatracker.ietf.org/doc/html/rfc2898)
  (obsoleted by [RFC 8018](https://datatracker.ietf.org/doc/html/rfc8018))
- [W3C XML Encryption](https://www.w3.org/TR/xmlenc-core1/)
- [W3C XML Signature](https://www.w3.org/TR/xmldsig-core1/)

## 9. Trademarks and scope

"Nexus Personal" is a product of Nexus Group. Bank names and app names are
trademarks of their respective owners. This is independent interoperability
documentation, not affiliated with or endorsed by any of them.
