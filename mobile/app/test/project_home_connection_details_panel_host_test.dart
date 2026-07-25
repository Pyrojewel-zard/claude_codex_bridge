import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:ccb_mobile/features/project_home/project_home_connection_details_panel_host.dart';

import 'support/project_home_test_driver.dart';

void main() {
  testWidgets(
    'renders diagnostics without pairing setup and forwards actions',
    (tester) async {
      final lifecycleResult = ValueNotifier<CcbProjectLifecycleResult?>(null);
      final runningLifecycleAction = ValueNotifier<CcbLifecycleAction?>(null);
      var checkRouteCalls = 0;
      final lifecycleActions = <CcbLifecycleAction>[];

      addTearDown(lifecycleResult.dispose);
      addTearDown(runningLifecycleAction.dispose);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ListView(
              children: [
                ProjectHomeConnectionDetailsPanelHost(
                  view: CcbProjectView.fromProjectViewPayload(
                    demoProjectViewFixture,
                  ),
                  mode: AppRuntimeMode.fake,
                  profiles: const [],
                  selectedProfile: null,
                  routeDiagnostics: null,
                  lifecycleResultListenable: lifecycleResult,
                  loadingProfiles: false,
                  checkingRoute: false,
                  runningLifecycleActionListenable: runningLifecycleAction,
                  onModeChanged: (_) {},
                  onProfileSelected: (_) {},
                  onCheckRoute: () {
                    checkRouteCalls += 1;
                  },
                  onLifecycleAction: lifecycleActions.add,
                ),
              ],
            ),
          ),
        ),
      );

      expect(
        find.byKey(const ValueKey('connection-details-panel')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('project-home-update-panel')),
        findsOneWidget,
      );
      expect(
        find.text('Current version: $ccbMobileDefaultVersion'),
        findsOneWidget,
      );
      expect(find.byKey(const ValueKey('gateway-pairing-panel')), findsNothing);
      expect(find.byKey(const ValueKey('gateway-url-field')), findsNothing);
      expect(find.byKey(const ValueKey('runtime-mode-panel')), findsOneWidget);
      expect(
        find.byKey(const ValueKey('project-lifecycle-panel')),
        findsOneWidget,
      );

      await expandTile(tester, const ValueKey('runtime-mode-panel'));
      expect(
        find.byKey(const ValueKey('gateway-route-check-button')),
        findsNothing,
      );
      expect(checkRouteCalls, 0);

      await expandTile(tester, const ValueKey('project-lifecycle-panel'));
      final wakeButton = find.byKey(const ValueKey('lifecycle-wake-button'));
      expect(wakeButton, findsOneWidget);
      tester.widget<OutlinedButton>(wakeButton).onPressed?.call();
      await tester.pumpAndSettle();

      expect(lifecycleActions, [CcbLifecycleAction.wake]);
    },
  );
}
