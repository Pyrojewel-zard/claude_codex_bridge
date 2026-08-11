import 'package:ccb_mobile/models/ccb_content_item.dart';
import 'package:ccb_mobile/models/ccb_conversation_item.dart';
import 'package:test/test.dart';

void main() {
  group('CcbConversationItem timing metadata', () {
    test('parses and serializes nullable timing fields as UTC ISO strings', () {
      final item = CcbConversationItem.fromJson({
        'id': 'reply-1',
        'agent': 'lead',
        'kind': 'agent_reply',
        'title': 'Agent reply',
        'body': 'done',
        'sent_at': '2026-07-01T11:42:00+08:00',
        'started_at': '2026-07-01T11:40:48+08:00',
        'completed_at': '2026-07-01T11:42:00+08:00',
        'duration_ms': '72000',
        'session_id': 'provider-session-1',
      });

      expect(item.sentAt, DateTime.utc(2026, 7, 1, 3, 42));
      expect(item.startedAt, DateTime.utc(2026, 7, 1, 3, 40, 48));
      expect(item.completedAt, DateTime.utc(2026, 7, 1, 3, 42));
      expect(item.durationMs, 72000);
      expect(item.sessionId, 'provider-session-1');

      final json = item.toJson();
      expect(json['sent_at'], '2026-07-01T03:42:00.000Z');
      expect(json['started_at'], '2026-07-01T03:40:48.000Z');
      expect(json['completed_at'], '2026-07-01T03:42:00.000Z');
      expect(json['duration_ms'], 72000);
      expect(json['session_id'], 'provider-session-1');
    });

    test('keeps old or malformed JSON timing fields nullable', () {
      final item = CcbConversationItem.fromJson({
        'id': 'user-1',
        'agent': 'lead',
        'kind': 'user_message',
        'title': 'You',
        'body': 'hello',
        'sent_at': 'not-a-date',
      });

      expect(item.sentAt, isNull);
      expect(item.startedAt, isNull);
      expect(item.completedAt, isNull);
      expect(item.durationMs, isNull);
    });

    test('copyWith preserves timing fields through state updates', () {
      final sentAt = DateTime.utc(2026, 7, 1, 3, 42);
      final item = CcbConversationItem.userMessage(
        id: 'local-lead-0',
        agentName: 'lead',
        body: 'hello',
        sentAt: sentAt,
      );

      final sent = item.copyWith(state: CcbConversationDeliveryState.sent);

      expect(sent.sentAt, sentAt);
      expect(sent.state, CcbConversationDeliveryState.sent);
    });

    test('copyWith preserves provider session identity', () {
      const item = CcbConversationItem(
        id: 'reply-session',
        agentName: 'lead',
        kind: CcbConversationItemKind.agentReply,
        title: 'Agent reply',
        body: 'hello',
        source: 'provider_native/codex',
        sessionId: 'provider-session-2',
      );

      expect(item.copyWith(body: 'updated').sessionId, 'provider-session-2');
    });

    test('agent replies carry timing metadata from content items', () {
      final reply = CcbConversationItem.agentReplyFromContent(
        agentName: 'lead',
        content: CcbContentItem(
          id: 'content-1',
          kind: 'reply',
          format: 'markdown',
          text: 'done',
          completedAt: DateTime.utc(2026, 7, 1, 3, 42),
          durationMs: 72000,
        ),
      );

      expect(reply.sentAt, DateTime.utc(2026, 7, 1, 3, 42));
      expect(reply.completedAt, DateTime.utc(2026, 7, 1, 3, 42));
      expect(reply.durationMs, 72000);
    });
  });
}
