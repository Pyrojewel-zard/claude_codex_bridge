import 'package:flutter/material.dart';

import '../../l10n/ccb_mobile_localizations.dart';
import '../../models/ccb_project_view.dart';

class ProjectChatHeader extends StatelessWidget {
  const ProjectChatHeader({
    required this.view,
    required this.onBack,
    required this.onOpenTerminal,
    required this.onOpenConnectionDetails,
    this.onRefreshConversation,
    this.onShowChat,
    this.terminalMode = false,
    super.key,
  });

  final CcbProjectView view;
  final VoidCallback? onBack;
  final VoidCallback? onRefreshConversation;
  final VoidCallback? onOpenTerminal;
  final VoidCallback? onShowChat;
  final VoidCallback onOpenConnectionDetails;
  final bool terminalMode;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final strings = CcbMobileLocalizations.of(context);
    return SizedBox(
      key: const ValueKey('project-chat-header'),
      height: 56,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8),
        child: Row(
          children: [
            if (onBack != null)
              IconButton(
                key: const ValueKey('project-back-button'),
                tooltip: strings.projects,
                onPressed: onBack,
                icon: const Icon(Icons.arrow_back),
              ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Text(
                  view.project.displayName,
                  key: const ValueKey('project-chat-title'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: textTheme.titleLarge,
                ),
              ),
            ),
            if (onRefreshConversation != null)
              IconButton(
                key: const ValueKey('agent-conversation-refresh-action'),
                tooltip: strings.refreshConversation,
                onPressed: onRefreshConversation,
                icon: const Icon(Icons.refresh),
              ),
            IconButton(
              key: ValueKey(
                terminalMode
                    ? 'return-to-agent-chat-button'
                    : 'open-agent-terminal-button',
              ),
              tooltip:
                  terminalMode ? strings.returnToChat : strings.openTerminal,
              onPressed: terminalMode ? onShowChat : onOpenTerminal,
              icon: Icon(
                terminalMode ? Icons.chat_bubble_outline : Icons.terminal,
              ),
            ),
            IconButton(
              key: const ValueKey('connection-details-action'),
              tooltip: strings.diagnostics,
              onPressed: onOpenConnectionDetails,
              icon: const Icon(Icons.more_vert),
            ),
          ],
        ),
      ),
    );
  }
}
