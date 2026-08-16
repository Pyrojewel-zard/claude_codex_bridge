# CCB Mobile App

This is the Flutter application for the CCB Mobile controller.

Current status:

- server-wide real-project gateway, chat, Terminal, file, notification, and
  Relay paths behind route-agnostic repository/transport boundaries;
- Provider identity, model/thinking selection, session usage, and account
  quota semantics aligned with open-source Paseo at pinned commit `b599d38`;
- CCB remains authoritative for project/window/agent/session lifecycle,
  configuration, permissions, and tmux panes;
- third-party provenance is recorded in
  [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

The Android and iOS platform folders were generated with `flutter create` after
the local Flutter/Android toolchain became available.

Useful development commands:

```bash
cd app
flutter create .
flutter test
flutter run -d <android-emulator-id>
```

Current workspace toolchain snapshot:

- Flutter 3.44.2 / Dart 3.12.2:
  `/home/bfly/.local/share/flutter-sdks/3.44.2/flutter/bin/flutter`
- JDK 17: `/home/bfly/.local/share/jdks/temurin-17.0.19+10`
- Android SDK: `/home/bfly/.local/share/android-sdk`

The generated Android/iOS platform folders are now present. The current
validated commands are:

```bash
cd app
/home/bfly/.local/share/flutter-sdks/3.44.2/flutter/bin/flutter analyze
/home/bfly/.local/share/flutter-sdks/3.44.2/flutter/bin/flutter test
/home/bfly/.local/share/flutter-sdks/3.44.2/flutter/bin/flutter build apk --debug
```
