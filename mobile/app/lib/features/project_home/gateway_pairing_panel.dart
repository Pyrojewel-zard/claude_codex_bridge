import 'package:flutter/material.dart';

import '../../l10n/ccb_mobile_localizations.dart';

class GatewayPairingPanel extends StatelessWidget {
  const GatewayPairingPanel({
    required this.connectionCodeController,
    required this.claiming,
    required this.onClaim,
    super.key,
  });

  final TextEditingController connectionCodeController;
  final bool claiming;
  final VoidCallback onClaim;

  @override
  Widget build(BuildContext context) {
    final strings = CcbMobileLocalizations.of(context);
    return ExpansionTile(
      key: const ValueKey('gateway-pairing-panel'),
      tilePadding: EdgeInsets.zero,
      childrenPadding: const EdgeInsets.only(top: 8, bottom: 8),
      leading: const Icon(Icons.keyboard_outlined),
      title: Text(strings.enterConnectionCode),
      subtitle: Text(strings.connectionCodeSummary),
      children: [
        TextField(
          key: const ValueKey('connection-code-field'),
          controller: connectionCodeController,
          keyboardType: TextInputType.text,
          textInputAction: TextInputAction.done,
          autocorrect: false,
          enableSuggestions: false,
          smartDashesType: SmartDashesType.disabled,
          smartQuotesType: SmartQuotesType.disabled,
          maxLines: 3,
          minLines: 1,
          onSubmitted: claiming ? null : (_) => onClaim(),
          decoration: InputDecoration(
            labelText: strings.connectionCode,
            hintText: 'ccb1_...',
            helperText: strings.connectionCodeHint,
            helperMaxLines: 2,
            prefixIcon: const Icon(Icons.link),
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            key: const ValueKey('gateway-pairing-claim-button'),
            onPressed: claiming ? null : onClaim,
            icon:
                claiming
                    ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                    : const Icon(Icons.add_link),
            label: Text(strings.connectWithCode),
          ),
        ),
      ],
    );
  }
}
