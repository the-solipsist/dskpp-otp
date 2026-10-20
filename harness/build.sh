#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pranesh Prakash
# Build harness.jar, the tiny dex that runs the installed app's DSKPP client.
#
# Requirements:
#   - javac (JDK 11+)
#   - d8: either a `d8` executable on PATH, or D8_JAR=/path/to/r8.jar
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
build="$here/build"

rm -rf "$build"
mkdir -p "$build/stubs" "$build/classes"

mapfile -t stub_sources < <(find "$here/stubs" -name '*.java')
javac --release 11 -d "$build/stubs" "${stub_sources[@]}"
javac --release 11 -cp "$build/stubs" -d "$build/classes" "$here/src/Harness.java"

if [[ -n "${D8_JAR:-}" ]]; then
    java -cp "$D8_JAR" com.android.tools.r8.D8 \
        --min-api 28 --classpath "$build/stubs" \
        --output "$here/harness.jar" "$build/classes/Harness.class"
elif command -v d8 >/dev/null 2>&1; then
    d8 --min-api 28 --classpath "$build/stubs" \
        --output "$here/harness.jar" "$build/classes/Harness.class"
else
    echo "error: d8 not found; set D8_JAR=/path/to/r8.jar or install d8" >&2
    exit 1
fi

rm -rf "$build"
echo "wrote $here/harness.jar"
