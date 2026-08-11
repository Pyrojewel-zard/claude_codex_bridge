#!/usr/bin/env sh
# Source this file before running local Flutter or Android SDK commands.

export FLUTTER_ROOT="${FLUTTER_ROOT:-/home/bfly/.local/share/flutter-sdks/3.44.2/flutter}"
export JAVA_HOME="${JAVA_HOME:-/home/bfly/.local/share/jdks/temurin-17.0.19+10}"
export ANDROID_HOME="${ANDROID_HOME:-/home/bfly/.local/share/android-sdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"

if [ -z "${CCB_MOBILE_CMAKE_BIN:-}" ]; then
  if [ -d "$ANDROID_HOME/cmake" ]; then
    ccb_mobile_cmake="$(find "$ANDROID_HOME/cmake" -path '*/bin/cmake' -type f 2>/dev/null | sort | tail -n 1)"
    if [ -x "$ccb_mobile_cmake" ]; then
      export CCB_MOBILE_CMAKE_BIN="$ccb_mobile_cmake"
    fi
  fi
fi

if [ -z "${CCB_MOBILE_CMAKE_BIN:-}" ]; then
  for ccb_mobile_cmake in /usr/bin/cmake /bin/cmake; do
    if [ -x "$ccb_mobile_cmake" ]; then
      export CCB_MOBILE_CMAKE_BIN="$ccb_mobile_cmake"
      break
    fi
  done
fi

if [ -n "${CCB_MOBILE_CMAKE_BIN:-}" ]; then
  CCB_MOBILE_CMAKE_DIR="$(dirname "$CCB_MOBILE_CMAKE_BIN")"
  export PATH="$CCB_MOBILE_CMAKE_DIR:$FLUTTER_ROOT/bin:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
  unset CCB_MOBILE_CMAKE_DIR
else
  export PATH="$FLUTTER_ROOT/bin:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
fi

unset ccb_mobile_cmake
