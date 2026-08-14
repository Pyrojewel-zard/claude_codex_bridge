import 'package:flutter/widgets.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;

/// Keeps xterm's implicit input/focus scrolls from overriding history reading.
class TerminalHistoryScrollController extends ScrollController {
  TerminalHistoryScrollController({
    super.debugLabel,
    this.onUserScrollDirectionChanged,
  });

  static const _latestTolerance = 8.0;

  final ValueChanged<ScrollDirection>? onUserScrollDirectionChanged;

  bool _isReadingHistory = false;

  bool get isReadingHistory =>
      _isReadingHistory &&
      hasClients &&
      position.extentAfter > _latestTolerance;

  bool get isAtLatestOutput =>
      hasClients && position.extentAfter <= _latestTolerance;

  @override
  ScrollPosition createScrollPosition(
    ScrollPhysics physics,
    ScrollContext context,
    ScrollPosition? oldPosition,
  ) {
    return _TerminalHistoryScrollPosition(
      owner: this,
      physics: physics,
      context: context,
      initialPixels: initialScrollOffset,
      keepScrollOffset: keepScrollOffset,
      oldPosition: oldPosition,
      debugLabel: debugLabel,
    );
  }

  void jumpToLatestOutput() {
    if (!hasClients) {
      return;
    }
    _isReadingHistory = false;
    (position as _TerminalHistoryScrollPosition).jumpToLatestOutput();
  }

  void _recordUserPosition(ScrollPosition position) {
    _isReadingHistory = position.extentAfter > _latestTolerance;
  }

  void _recordUserOffset(double delta) {
    if (delta < 0) {
      onUserScrollDirectionChanged?.call(ScrollDirection.reverse);
    } else if (delta > 0) {
      onUserScrollDirectionChanged?.call(ScrollDirection.forward);
    }
  }

  bool _shouldSuppressImplicitLatestJump(
    ScrollPosition position,
    double value,
  ) {
    if (!_isReadingHistory) {
      return false;
    }
    if (position.extentAfter <= _latestTolerance) {
      _isReadingHistory = false;
      return false;
    }
    return value >= position.maxScrollExtent - _latestTolerance;
  }
}

class _TerminalHistoryScrollPosition extends ScrollPositionWithSingleContext {
  _TerminalHistoryScrollPosition({
    required this.owner,
    required super.physics,
    required super.context,
    super.initialPixels,
    super.keepScrollOffset,
    super.oldPosition,
    super.debugLabel,
  });

  final TerminalHistoryScrollController owner;

  @override
  void applyUserOffset(double delta) {
    super.applyUserOffset(delta);
    owner._recordUserPosition(this);
    owner._recordUserOffset(delta);
  }

  @override
  void jumpTo(double value) {
    if (owner._shouldSuppressImplicitLatestJump(this, value)) {
      return;
    }
    super.jumpTo(value);
  }

  void jumpToLatestOutput() {
    super.jumpTo(maxScrollExtent);
  }
}
