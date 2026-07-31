import '../../models/ccb_agent.dart';

const _claudeLocalCommandsWithoutAssistantReply = <String>{
  '/clear',
  '/config',
  '/cost',
  '/doctor',
  '/exit',
  '/help',
  '/logout',
  '/memory',
  '/model',
  '/permissions',
  '/status',
  '/terminal-setup',
  '/vim',
};

const _codexLocalCommandsWithoutAssistantReply = <String>{
  '/clear',
  '/exit',
  '/help',
  '/model',
  '/permissions',
  '/quit',
  '/status',
};

bool agentSubmissionExpectsAssistantReply({
  required CcbAgent agent,
  required String body,
  required bool hasAttachments,
}) {
  if (hasAttachments) {
    return true;
  }
  final command = _exactSlashCommand(body);
  if (command == null) {
    return true;
  }
  return switch (agent.provider.trim().toLowerCase()) {
    'claude' => !_claudeLocalCommandsWithoutAssistantReply.contains(command),
    'codex' => !_codexLocalCommandsWithoutAssistantReply.contains(command),
    _ => true,
  };
}

String? _exactSlashCommand(String body) {
  final text = body.trim().toLowerCase();
  if (text.isEmpty || text.contains(RegExp(r'\s'))) {
    return null;
  }
  return text.startsWith('/') ? text : null;
}
