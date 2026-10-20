#!/usr/bin/env python3
"""Provision a Nexus Personal DSKPP OTP profile into a standard otpauth URI.

This is a provisioning-time interoperability tool.  It does not read an
existing profile out of app-private storage; it performs the DSKPP exchange
with a fresh activation URL and the activation PIN, exactly as the app would,
and returns the seed so that a standard authenticator can be used.

The exchange is executed with the Nexus Personal SDK classes that are already
bundled in the installed app.  The app is *not* modified, copied or
redistributed: a tiny harness is loaded with app_process (shell UID) and
delegates to the app's own SDK.

Example:
    dskpp_otp.py \\
        --package com.yesbank.and.yessecurenext \\
        --link-file /tmp/yes-link.txt \\
        --pin-file /tmp/yes-pin.txt \\
        --out /tmp/yes-otp

The activation URL must be one you obtained yourself from the bank.  The PIN
must be the activation PIN (the one used when the profile was provisioned),
not a later local PIN change.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

DEFAULT_SCHEME = "com.nexusgroup.dskpp"
HARNESS_CLASS = "Harness"
DEFAULT_HARNESS = Path(__file__).resolve().parent / "harness" / "harness.jar"


def run(cmd: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run a command and return its completed process."""
    return subprocess.run(
        cmd,
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def adb_base(adb: str, serial: str | None) -> list[str]:
    """Return the adb command prefix."""
    cmd = [adb]
    if serial:
        cmd += ["-s", serial]
    return cmd


def adb_run(
    adb: str,
    serial: str | None,
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Run an adb command, raising on failure when requested."""
    result = run(adb_base(adb, serial) + args, input_bytes=input_bytes)
    if check and result.returncode != 0:
        raise RuntimeError(
            "adb failed: "
            + " ".join(shlex.quote(x) for x in args)
            + "\n"
            + result.stderr.decode("utf-8", "replace").strip()
        )
    return result


def normalize_link(raw: str, scheme: str = DEFAULT_SCHEME) -> str:
    """Turn a bank activation link into the DSKPP URL the SDK expects.

    Accepted forms:
      * https://host/?oath_url=<app-scheme>://host/dskpp/v1/post?u=...&ac=...
      * <app-scheme>://host/dskpp/v1/post?u=...&ac=...
      * com.nexusgroup.dskpp://host/dskpp/v1/post?u=...&ac=...

    The outer ``ac`` parameter is often outside the ``oath_url`` value; it is
    appended to the inner URL when missing.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("empty activation URL")

    outer = urlparse(raw)
    outer_query = dict(parse_qsl(outer.query, keep_blank_values=True))

    if "oath_url" in outer_query:
        inner = outer_query["oath_url"]
        outer_ac = outer_query.get("ac", "")
        inner_query = dict(parse_qsl(urlparse(inner).query, keep_blank_values=True))
        if "ac" not in inner_query and outer_ac:
            separator = "&" if urlparse(inner).query else "?"
            inner = inner + separator + urlencode({"ac": outer_ac})
        raw = inner

    parsed = urlparse(raw)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if not params.get("u") or not params.get("ac"):
        raise ValueError("activation URL is missing u= and/or ac=")

    query = urlencode([("u", params["u"]), ("ac", params["ac"])])
    return urlunparse((scheme, parsed.netloc, parsed.path, "", query, ""))


def redact_link(url: str) -> str:
    """Return a display-safe form of an activation URL."""
    parsed = urlparse(url)
    names = [name for name, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    query = "&".join(f"{name}=<redacted>" for name in names)
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path}?{query}"


def package_apks(adb: str, serial: str | None, package: str) -> list[str]:
    """Return every APK path belonging to an installed package."""
    result = adb_run(adb, serial, ["shell", f"pm path {shlex.quote(package)}"])
    apks = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("package:"):
            apks.append(line.split(":", 1)[1])
    if not apks:
        raise RuntimeError(
            f"package {package!r} is not installed (or adb cannot see it)"
        )
    return apks


def decode_base32(seed: str) -> bytes:
    """Decode a Base32 TOTP secret, tolerating missing padding."""
    normalized = seed.strip().upper().rstrip("=")
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + padding)


def build_otpauth(meta: dict[str, str], seed: str) -> tuple[str, str]:
    """Build an otpauth URI from the SDK profile metadata."""
    otp_type = (meta.get("getType") or "TOTP").upper()
    issuer = meta.get("getIssuer") or "Nexus Personal"
    account = meta.get("getUserId") or meta.get("getDisplayName") or "otp"

    params: list[tuple[str, str]] = [("secret", seed)]
    params.append(("issuer", issuer))

    if otp_type == "HOTP":
        counter = meta.get("getCounter")
        if counter:
            params.append(("counter", counter))
        scheme = "hotp"
    else:
        scheme = "totp"
        algorithm = meta.get("getAlgorithm")
        digits = meta.get("getDigits")
        period = meta.get("getPeriod")
        if algorithm:
            params.append(("algorithm", algorithm))
        if digits:
            params.append(("digits", digits))
        if period:
            params.append(("period", period))

    label = quote(issuer, safe="") + ":" + quote(account, safe="")
    return f"otpauth://{scheme}/{label}?{urlencode(params)}", otp_type


def make_qr(uri: str, path: Path) -> str | None:
    """Write a QR PNG, returning the tool used or None."""
    qrencode = shutil.which("qrencode")
    if qrencode:
        result = run([qrencode, "-t", "PNG", "-o", str(path)], input_bytes=uri.encode())
        if result.returncode == 0:
            return "qrencode"
    try:
        import qrcode  # type: ignore
    except ImportError:
        return None
    image = qrcode.make(uri, box_size=8, border=4)
    image.save(str(path))
    return "qrcode"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Provision a Nexus Personal DSKPP OTP profile into a standard "
            "otpauth:// URI at activation time."
        ),
        epilog=(
            "Example:\n"
            "  %(prog)s --package com.yesbank.and.yessecurenext \\\n"
            "      --link-file /tmp/yes-link.txt --pin-file /tmp/yes-pin.txt \\\n"
            "      --out /tmp/yes-otp\n\n"
            "The activation link is single-use.  Completing the exchange "
            "rotates the server-side key, so the app's existing profile "
            "becomes stale.  Use only with your own account."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--package",
        required=True,
        help="installed app package that bundles the Nexus Personal SDK "
        "(e.g. com.yesbank.and.yessecurenext)",
    )
    link = parser.add_mutually_exclusive_group(required=True)
    link.add_argument(
        "--link-file",
        type=Path,
        help="file containing the activation URL (recommended; keeps it out of shell history)",
    )
    link.add_argument(
        "--link",
        help="activation URL as a string (visible in ps/history; prefer --link-file)",
    )
    pin = parser.add_mutually_exclusive_group()
    pin.add_argument(
        "--pin-file",
        type=Path,
        help="file containing the activation PIN (recommended)",
    )
    pin.add_argument(
        "--pin",
        help="activation PIN as a string (visible in ps/history; prefer --pin-file)",
    )
    parser.add_argument(
        "--scheme",
        default=DEFAULT_SCHEME,
        help=f"DSKPP scheme expected by the SDK (default: {DEFAULT_SCHEME})",
    )
    parser.add_argument(
        "--out",
        default="dskpp-otp",
        help="output prefix; writes <out>.otpauth.txt and <out>.png (default: dskpp-otp)",
    )
    parser.add_argument(
        "--harness",
        type=Path,
        default=DEFAULT_HARNESS,
        help=f"harness jar (default: {DEFAULT_HARNESS})",
    )
    parser.add_argument("--adb", default="adb", help="adb executable (default: adb)")
    parser.add_argument("--serial", help="adb device serial (for multiple devices)")
    parser.add_argument(
        "--qr",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="generate a QR PNG (default: enabled)",
    )
    parser.add_argument(
        "--print-uri",
        action="store_true",
        help="print the otpauth URI (contains the secret)",
    )
    parser.add_argument(
        "--store-pass",
        metavar="NAME",
        help="insert the URI into pass under NAME (runs: pass otp insert -f NAME)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="normalize the link and show the plan without contacting the device or bank",
    )
    parser.add_argument("--debug", action="store_true", help="print adb commands")
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="keep the device temp directory (contains secrets; debugging only)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the provisioning flow."""
    args = parse_args(argv)

    try:
        raw_link = (
            args.link_file.read_text(encoding="utf-8").strip()
            if args.link_file
            else args.link
        )
        url = normalize_link(raw_link, args.scheme)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"activation URL: {redact_link(url)}")
    print(f"package: {args.package}")
    print(f"output prefix: {args.out}")

    if args.dry_run:
        print("dry run: not contacting adb or the bank")
        print(f"harness: {args.harness}")
        return 0

    if not args.harness.is_file():
        print(f"error: harness not found: {args.harness}", file=sys.stderr)
        return 1

    if shutil.which(args.adb) is None:
        print(f"error: adb not found: {args.adb}", file=sys.stderr)
        return 1

    if args.pin_file:
        try:
            pin = args.pin_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    elif args.pin:
        pin = args.pin.strip()
    else:
        pin = getpass.getpass("Activation PIN: ").strip()

    if not pin:
        print("error: empty PIN", file=sys.stderr)
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="dskpp-otp-"))
    os.chmod(workdir, 0o700)
    device_dir = f"/data/local/tmp/dskpp-otp-{os.urandom(6).hex()}"
    remote = {
        "url": f"{device_dir}/url",
        "pin": f"{device_dir}/pin",
        "harness": f"{device_dir}/harness.jar",
        "seed": f"{device_dir}/seed",
        "meta": f"{device_dir}/meta",
    }

    try:
        url_file = workdir / "url"
        url_file.write_text(url + "\n", encoding="utf-8")
        os.chmod(url_file, 0o600)
        pin_file = workdir / "pin"
        pin_file.write_text(pin + "\n", encoding="utf-8")
        os.chmod(pin_file, 0o600)

        if args.debug:
            print(f"adb: {args.adb} serial={args.serial or '<default>'}")

        apks = package_apks(args.adb, args.serial, args.package)
        adb_run(args.adb, args.serial, ["shell", f"mkdir -p {shlex.quote(device_dir)}"])
        adb_run(args.adb, args.serial, ["shell", f"chmod 700 {shlex.quote(device_dir)}"])
        for local, remote_path in (
            (url_file, remote["url"]),
            (pin_file, remote["pin"]),
            (args.harness, remote["harness"]),
        ):
            adb_run(args.adb, args.serial, ["push", str(local), remote_path])
        adb_run(
            args.adb,
            args.serial,
            [
                "shell",
                f"chmod 600 {shlex.quote(remote['url'])} {shlex.quote(remote['pin'])}",
            ],
        )

        classpath = ":".join([remote["harness"]] + apks)
        shell_cmd = (
            f"CLASSPATH={shlex.quote(classpath)} /system/bin/app_process /system/bin "
            f"{HARNESS_CLASS} {shlex.quote(remote['url'])} {shlex.quote(remote['pin'])} "
            f"{shlex.quote(remote['seed'])} {shlex.quote(remote['meta'])}"
        )
        if args.debug:
            print(f"adb shell {shell_cmd}")

        result = adb_run(args.adb, args.serial, ["shell", shell_cmd], check=False)
        stderr = result.stderr.decode("utf-8", "replace").strip()
        if result.returncode != 0:
            print(stderr or "harness failed", file=sys.stderr)
            lowered = stderr.lower()
            if "expired or consumed" in lowered:
                print(
                    "hint: the activation code is single-use; generate a new "
                    "activation link.",
                    file=sys.stderr,
                )
            elif "classnotfound" in lowered or "noclassdeffound" in lowered:
                print(
                    "hint: the package does not bundle the expected Nexus Personal "
                    "classes; check --package.",
                    file=sys.stderr,
                )
            elif "nosuchmethod" in lowered:
                print(
                    "hint: the app's SDK version differs from the harness stubs; "
                    "the harness needs updating.",
                    file=sys.stderr,
                )
            elif "no jce provider" in lowered:
                print(
                    "hint: the app does not bundle BouncyCastle; a JCE provider "
                    "is required.",
                    file=sys.stderr,
                )
            return 1

        local_seed = workdir / "seed"
        local_meta = workdir / "meta"
        adb_run(args.adb, args.serial, ["pull", remote["seed"], str(local_seed)])
        adb_run(args.adb, args.serial, ["pull", remote["meta"], str(local_meta)])

        seed_line = local_seed.read_text(encoding="utf-8").strip()
        if not seed_line.startswith("seed=") or not seed_line.split("=", 1)[1]:
            print("error: no seed returned by the harness", file=sys.stderr)
            return 1
        seed = seed_line.split("=", 1)[1].strip()

        meta: dict[str, str] = {}
        for line in local_meta.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if not value.startswith("ERR:"):
                    meta[key] = value

        try:
            key_bytes = decode_base32(seed)
        except Exception as exc:  # noqa: BLE001
            print(f"error: seed is not valid Base32: {exc}", file=sys.stderr)
            return 1

        uri, otp_type = build_otpauth(meta, seed)
        out_prefix = Path(args.out)
        uri_path = Path(f"{out_prefix}.otpauth.txt")
        qr_path = Path(f"{out_prefix}.png")
        uri_path.write_text(uri + "\n", encoding="utf-8")
        os.chmod(uri_path, 0o600)

        qr_tool = None
        if args.qr:
            qr_tool = make_qr(uri, qr_path)
            if qr_tool:
                os.chmod(qr_path, 0o600)

        print()
        print(f"issuer:    {meta.get('getIssuer', '-')}")
        print(f"account:   {meta.get('getUserId', meta.get('getDisplayName', '-'))}")
        print(f"type:      {otp_type}")
        print(f"algorithm: {meta.get('getAlgorithm', '-')}")
        print(f"digits:    {meta.get('getDigits', '-')}")
        print(f"period:    {meta.get('getPeriod', '-')}s")
        print(f"seed:      {len(seed)} Base32 chars ({len(key_bytes) * 8}-bit)")
        print(f"uri file:  {uri_path} (0600)")
        if qr_tool:
            print(f"qr file:   {qr_path} (0600, {qr_tool})")
        elif args.qr:
            print("qr:        not generated (install qrencode or the qrcode module)")

        if args.print_uri:
            print()
            print(uri)

        if args.store_pass:
            pass_bin = shutil.which("pass")
            if not pass_bin:
                print("error: pass not found; cannot --store-pass", file=sys.stderr)
                return 1
            result = run([pass_bin, "otp", "insert", "-f", args.store_pass], input_bytes=uri.encode())
            if result.returncode != 0:
                print(result.stderr.decode("utf-8", "replace").strip(), file=sys.stderr)
                return 1
            print(f"stored in pass: {args.store_pass}")
            print(f"show QR: pass otp uri -q {args.store_pass}")

        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.keep_temp:
            try:
                adb_run(args.adb, args.serial, ["shell", f"rm -rf {shlex.quote(device_dir)}"], check=False)
            except RuntimeError as exc:
                if args.debug:
                    print(f"cleanup: {exc}", file=sys.stderr)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
