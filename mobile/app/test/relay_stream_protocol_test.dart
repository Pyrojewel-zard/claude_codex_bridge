import 'dart:convert';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test('relay inner request and stream frames use the frozen v1 schema', () {
    final request = RelayInnerMessage.request(
      requestId: 'request-demo-0001',
      operation: 'agent_conversation',
      payload: const {
        'project_id': 'project-demo',
        'agent': 'worker1',
        'namespace_epoch': 7,
      },
    );
    final opened = RelayInnerMessage.streamOpen(
      streamId: 'stream-demo-0001',
      operation: 'terminal',
      payload: const {'terminal_id': 'terminal-demo'},
    );

    expect(
      RelayInnerMessage.decode(request.encode()).toJson(),
      request.toJson(),
    );
    expect(RelayInnerMessage.decode(opened.encode()).toJson(), opened.toJson());
    expect(relayInnerPayloadSize(const {'data': 'abc'}), 14);
  });

  test(
    'relay inner protocol rejects downgrade and arbitrary proxy operation',
    () {
      expect(
        () => RelayInnerMessage.fromJson(const {
          'schema_version': 0,
          'kind': 'request',
          'request_id': 'request-demo-0001',
          'operation': 'health',
          'payload': <String, Object?>{},
        }),
        throwsFormatException,
      );
      expect(
        () => RelayInnerMessage.request(
          requestId: 'request-demo-0001',
          operation: 'arbitrary_proxy',
          payload: const {},
        ),
        throwsFormatException,
      );
      expect(
        () => RelayInnerMessage.request(
          requestId: 'request-demo-0001',
          operation: 'upload_file',
          payload: const {},
        ),
        throwsFormatException,
      );
    },
  );

  test('relay inner stream identity and receive credit are bounded', () {
    expect(
      () => RelayInnerMessage(
        kind: RelayInnerKind.error,
        requestId: 'request-demo-0001',
        streamId: 'stream-demo-0001',
        payload: const {'code': 'bad_request'},
      ),
      throwsFormatException,
    );
    expect(
      () => RelayInnerMessage.streamOpen(
        streamId: 'stream-demo-0001',
        operation: 'notifications',
        payload: const {},
        creditBytes: relayStreamMaxWindowBytes + 1,
      ),
      throwsFormatException,
    );
    expect(
      () => RelayInnerMessage(
        kind: RelayInnerKind.streamData,
        streamId: 'stream-demo-0001',
        creditBytes: 1,
        payload: const {},
      ),
      throwsFormatException,
    );
  });

  test('relay inner decoder rejects non-object and oversized messages', () {
    expect(
      () =>
          RelayInnerMessage.decode(utf8.encode(jsonEncode(['not', 'object']))),
      throwsFormatException,
    );
    expect(
      () => RelayInnerMessage.decode(
        List<int>.filled(relayStreamMaxMessageBytes + 1, 0x20),
      ),
      throwsFormatException,
    );
  });
}
