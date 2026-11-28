import 'dart:async';
import 'dart:convert';
import 'package:dynamic_color/dynamic_color.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

void main() => runApp(const PhoneToPcApp());

class PhoneToPcApp extends StatefulWidget {
  const PhoneToPcApp({super.key});

  @override
  State<PhoneToPcApp> createState() => _PhoneToPcAppState();
}

class _PhoneToPcAppState extends State<PhoneToPcApp> {
  static const _settings = MethodChannel('phonetopc/settings');
  ThemeMode _themeMode = ThemeMode.system;

  @override
  void initState() {
    super.initState();
    _loadThemeMode();
  }

  Future<void> _loadThemeMode() async {
    try {
      final saved = await _settings.invokeMethod<String>('getThemeMode');
      if (!mounted || saved == null) return;
      setState(() {
        _themeMode = ThemeMode.values.firstWhere(
          (mode) => mode.name == saved,
          orElse: () => ThemeMode.system,
        );
      });
    } on PlatformException catch (error) {
      debugPrint('Could not load theme preference: ${error.message}');
    }
  }

  Future<void> _setThemeMode(ThemeMode mode) async {
    setState(() => _themeMode = mode);
    try {
      await _settings
          .invokeMethod<void>('setThemeMode', {'themeMode': mode.name});
    } on PlatformException catch (error) {
      debugPrint('Could not save theme preference: ${error.message}');
    }
  }

  @override
  Widget build(BuildContext context) => DynamicColorBuilder(
        builder: (lightDynamic, darkDynamic) {
          final lightScheme = lightDynamic ??
              ColorScheme.fromSeed(seedColor: const Color(0xff176b5b));
          final darkScheme = darkDynamic ??
              ColorScheme.fromSeed(
                seedColor: const Color(0xff176b5b),
                brightness: Brightness.dark,
              );
          return MaterialApp(
            title: 'PhoneToPC',
            theme: ThemeData(colorScheme: lightScheme, useMaterial3: true),
            darkTheme: ThemeData(colorScheme: darkScheme, useMaterial3: true),
            themeMode: _themeMode,
            home: AppHome(
                themeMode: _themeMode, onThemeModeChanged: _setThemeMode),
          );
        },
      );
}

class AppHome extends StatefulWidget {
  const AppHome(
      {super.key, required this.themeMode, required this.onThemeModeChanged});

  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeModeChanged;

  @override
  State<AppHome> createState() => _AppHomeState();
}

class _AppHomeState extends State<AppHome> {
  int _selectedIndex = 0;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: Text(_selectedIndex == 0 ? 'PhoneToPC' : 'Settings'),
        ),
        body: IndexedStack(
          index: _selectedIndex,
          children: [
            const StreamPage(),
            SettingsPage(
              themeMode: widget.themeMode,
              onThemeModeChanged: widget.onThemeModeChanged,
            ),
          ],
        ),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _selectedIndex,
          onDestinationSelected: (index) =>
              setState(() => _selectedIndex = index),
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.graphic_eq_outlined),
              selectedIcon: Icon(Icons.graphic_eq),
              label: 'Stream',
            ),
            NavigationDestination(
              icon: Icon(Icons.settings_outlined),
              selectedIcon: Icon(Icons.settings),
              label: 'Settings',
            ),
          ],
        ),
      );
}

class SettingsPage extends StatelessWidget {
  const SettingsPage(
      {super.key, required this.themeMode, required this.onThemeModeChanged});

  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeModeChanged;

  String get _themeDescription => switch (themeMode) {
        ThemeMode.system => 'Follows your Android light or dark appearance.',
        ThemeMode.light => 'Always use the light appearance.',
        ThemeMode.dark => 'Always use the dark appearance.',
      };

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('Appearance', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Theme', style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 16),
                  SegmentedButton<ThemeMode>(
                    showSelectedIcon: false,
                    segments: const [
                      ButtonSegment(
                          value: ThemeMode.system, label: Text('System')),
                      ButtonSegment(
                          value: ThemeMode.light, label: Text('Light')),
                      ButtonSegment(value: ThemeMode.dark, label: Text('Dark')),
                    ],
                    selected: {themeMode},
                    onSelectionChanged: (selection) =>
                        onThemeModeChanged(selection.first),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    _themeDescription,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Icon(Icons.palette_outlined),
              title: const Text('Material You colors'),
              subtitle: const Text(
                'On Android 12 and newer, colors follow your wallpaper. Older versions use the app color palette.',
              ),
              isThreeLine: true,
            ),
          ),
        ],
      );
}

class StreamPage extends StatefulWidget {
  const StreamPage({super.key});

  @override
  State<StreamPage> createState() => _StreamPageState();
}

class _StreamPageState extends State<StreamPage> {
  static const _methods = MethodChannel('phonetopc/capture');
  static const _settings = MethodChannel('phonetopc/settings');
  static const _audio = EventChannel('phonetopc/audio');
  final _host = TextEditingController();
  final _port = TextEditingController(text: '8765');
  WebSocketChannel? _socket;
  StreamSubscription<dynamic>? _subscription;
  StreamSubscription<dynamic>? _controlSubscription;
  String _status = 'Ready';
  bool _running = false;
  bool _starting = false;
  bool _includeVideo = false;
  String _videoQuality = 'balanced';
  String _videoFrameRate = '30';
  int _bytes = 0;
  int _videoFrames = 0;
  String _connectionMode = 'wifi';
  String _lastWifiHost = '';

  @override
  void initState() {
    super.initState();
    _loadConnectionSettings();
  }

  Future<void> _loadConnectionSettings() async {
    try {
      final saved = await _settings
          .invokeMapMethod<String, String>('getConnectionSettings');
      if (!mounted || saved == null) return;
      final mode = saved['mode'] == 'usb' ? 'usb' : 'wifi';
      _lastWifiHost = saved['wifiHost'] ?? '';
      setState(() {
        _connectionMode = mode;
        _host.text = mode == 'usb' ? '127.0.0.1' : (saved['host'] ?? '');
        _port.text = saved['port'] ?? '8765';
      });
    } on PlatformException {
      // Keep the default connection fields if saved settings aren't available.
    }
  }

  Future<void> _saveConnectionSettings() async {
    await _settings.invokeMethod<void>('setConnectionSettings', {
      'host': _host.text.trim(),
      'port': _port.text.trim(),
      'mode': _connectionMode,
      'wifiHost': _lastWifiHost,
    });
  }

  void _selectConnectionMode(String mode) {
    if (mode == _connectionMode) return;
    if (_connectionMode == 'wifi' && _host.text.trim() != '127.0.0.1') {
      _lastWifiHost = _host.text.trim();
    }
    setState(() {
      _connectionMode = mode;
      _host.text = mode == 'usb' ? '127.0.0.1' : _lastWifiHost;
    });
    _saveConnectionSettings();
  }

  Future<void> _start() async {
    final host = _host.text.trim();
    final port = int.tryParse(_port.text.trim());
    if (host.isEmpty || port == null || port < 1 || port > 65535) {
      setState(() => _status = 'Enter a valid PC address and port.');
      return;
    }
    if (_connectionMode == 'wifi') _lastWifiHost = host;
    await _saveConnectionSettings();
    setState(() {
      _status = 'Connecting…';
      _starting = true;
      _bytes = 0;
      _videoFrames = 0;
    });
    try {
      final socket = WebSocketChannel.connect(
          Uri(scheme: 'ws', host: host, port: port, path: '/audio'));
      await socket.ready.timeout(const Duration(seconds: 5));
      _socket = socket;
      final deviceName = await _methods.invokeMethod<String>('getDeviceName') ??
          'Android device';
      socket.sink.add('DEVICE_NAME:$deviceName');
      _controlSubscription = socket.stream.listen(
        (dynamic message) {
          if (message is String && message.startsWith('CONTROL:')) {
            unawaited(
                _handleRemoteGesture(message.substring('CONTROL:'.length)));
          } else if (message is String && message.startsWith('PHONE_MUTE:')) {
            unawaited(
                _handlePhoneMute(message.substring('PHONE_MUTE:'.length)));
          }
        },
        onDone: () => unawaited(_setPhoneMuted(false)),
        onError: (Object _) => unawaited(_setPhoneMuted(false)),
      );
      await _methods.invokeMethod<void>(
        'startCapture',
        {
          'includeVideo': _includeVideo,
          'videoQuality': _videoQuality,
          'videoFrameRate': _videoFrameRate,
        },
      );
      _subscription = _audio.receiveBroadcastStream().listen((dynamic data) {
        if (data is Uint8List) {
          _socket?.sink.add(data);
          _bytes += data.length;
        } else if (data is Map) {
          final type = data['type'];
          final payload = data['data'];
          if (payload is Uint8List && type == 'audio') {
            _socket?.sink.add(Uint8List.fromList([
              ...ascii.encode('PTP1A'),
              ...payload,
            ]));
            _bytes += payload.length;
          } else if (payload is Uint8List && type == 'video') {
            _socket?.sink.add(Uint8List.fromList([
              ...ascii.encode('PTP1V'),
              ...payload,
            ]));
            _videoFrames++;
          }
        }
        if (mounted) setState(() {});
      }, onError: (Object error) {
        if (mounted) setState(() => _status = 'Capture error: $error');
      });
      setState(() {
        _starting = false;
        _running = true;
        _status = 'Streaming';
      });
    } catch (error) {
      await _stop();
      setState(() {
        _starting = false;
        _status = 'Could not start: $error';
      });
    }
  }

  Future<void> _stop() async {
    await _setPhoneMuted(false);
    await _subscription?.cancel();
    _subscription = null;
    await _controlSubscription?.cancel();
    _controlSubscription = null;
    try {
      await _methods.invokeMethod<void>('stopCapture');
    } catch (_) {}
    await _socket?.sink.close();
    _socket = null;
    if (mounted)
      setState(() {
        _starting = false;
        _running = false;
        if (_status == 'Streaming') _status = 'Stopped';
      });
  }

  Future<void> _handlePhoneMute(String value) async {
    final socket = _socket;
    if (socket == null) return;
    final muted = value.trim() == '1';
    if (value.trim() != '1' && value.trim() != '0') return;
    var applied = false;
    try {
      applied = await _methods.invokeMethod<bool>(
            'setPhoneMuted',
            {'muted': muted},
          ) ??
          false;
    } on Object catch (_) {}
    if (identical(_socket, socket)) {
      final result = !applied ? 'unavailable' : (muted ? 'muted' : 'unmuted');
      socket.sink.add('PHONE_MUTE_RESULT:$result');
    }
  }

  Future<void> _setPhoneMuted(bool muted) async {
    try {
      await _methods.invokeMethod<bool>('setPhoneMuted', {'muted': muted});
    } on Object catch (_) {}
  }

  Future<void> _restorePhoneMuteAndStopCapture() async {
    await _setPhoneMuted(false);
    try {
      await _methods.invokeMethod<void>('stopCapture');
    } on Object catch (_) {}
  }

  Future<void> _handleRemoteGesture(String json) async {
    final socket = _socket;
    if (socket == null) return;
    try {
      final command = jsonDecode(json) as Map<String, dynamic>;
      if (command['type'] != 'gesture' || command['points'] is! List) return;
      final accepted = await _methods.invokeMethod<bool>(
            'dispatchMouseGesture',
            {
              'points': command['points'],
              'durationMs': command['durationMs'] ?? 120,
            },
          ) ??
          false;
      if (!accepted)
        socket.sink.add(
            'CONTROL_ERROR:Enable PhoneToPC mouse control in Android Accessibility settings.');
    } on Object catch (error) {
      socket.sink.add('CONTROL_ERROR:Could not send mouse gesture: $error');
    }
  }

  @override
  void dispose() {
    _subscription?.cancel();
    _controlSubscription?.cancel();
    _socket?.sink.close();
    unawaited(_restorePhoneMuteAndStopCapture());
    _host.dispose();
    _port.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('Stream phone audio',
              style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 6),
          Text(
            'Send eligible Android playback to your Windows PC over Wi-Fi or USB.',
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 20),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('PC connection',
                      style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 16),
                  Text('What to stream',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  SegmentedButton<bool>(
                    showSelectedIcon: false,
                    segments: const [
                      ButtonSegment<bool>(
                        value: false,
                        label: Text('Audio only'),
                        icon: Icon(Icons.graphic_eq),
                      ),
                      ButtonSegment<bool>(
                        value: true,
                        label: Text('Audio + video'),
                        icon: Icon(Icons.screen_share_outlined),
                      ),
                    ],
                    selected: {_includeVideo},
                    onSelectionChanged: _running || _starting
                        ? null
                        : (selection) =>
                            setState(() => _includeVideo = selection.first),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _includeVideo
                        ? 'Android will ask you to approve screen sharing. The PC will show your screen in Video stream.'
                        : 'Send phone playback audio without sharing the screen.',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                  if (_includeVideo) ...[
                    const SizedBox(height: 12),
                    Text('Screen quality',
                        style: Theme.of(context).textTheme.titleSmall),
                    const SizedBox(height: 6),
                    SegmentedButton<String>(
                      showSelectedIcon: false,
                      segments: const [
                        ButtonSegment(value: 'low', label: Text('Low')),
                        ButtonSegment(
                            value: 'balanced', label: Text('Balanced')),
                        ButtonSegment(value: 'high', label: Text('High')),
                      ],
                      selected: {_videoQuality},
                      onSelectionChanged: _running || _starting
                          ? null
                          : (selection) => setState(
                                () => _videoQuality = selection.first,
                              ),
                    ),
                    const SizedBox(height: 12),
                    Text('Screen frame rate',
                        style: Theme.of(context).textTheme.titleSmall),
                    const SizedBox(height: 6),
                    SegmentedButton<String>(
                      showSelectedIcon: false,
                      segments: const [
                        ButtonSegment(value: '30', label: Text('30 FPS')),
                        ButtonSegment(value: '60', label: Text('60 FPS')),
                      ],
                      selected: {_videoFrameRate},
                      onSelectionChanged: _running || _starting
                          ? null
                          : (selection) => setState(
                                () => _videoFrameRate = selection.first,
                              ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '60 FPS uses more phone processing and network bandwidth; the actual rate depends on your phone and connection.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      onPressed: () => _methods.invokeMethod<void>(
                        'openMouseControlSettings',
                      ),
                      icon: const Icon(Icons.mouse_outlined),
                      label: const Text('Enable mouse control on phone'),
                    ),
                    Text(
                      'In Android Accessibility settings, enable PhoneToPC mouse control. Then turn on Allow mouse control in Windows. Android 15+ phones can also turn off their display from the Windows Video stream section when USB debugging is authorized.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(
                          value: 'wifi',
                          label: Text('Wi-Fi'),
                          icon: Icon(Icons.wifi)),
                      ButtonSegment(
                          value: 'usb',
                          label: Text('USB'),
                          icon: Icon(Icons.usb)),
                    ],
                    selected: {_connectionMode},
                    onSelectionChanged: _running || _starting
                        ? null
                        : (selection) => _selectConnectionMode(selection.first),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _host,
                    enabled: !_running && !_starting,
                    keyboardType: TextInputType.url,
                    decoration: InputDecoration(
                      labelText: 'PC address',
                      hintText: _connectionMode == 'usb'
                          ? '127.0.0.1'
                          : '192.168.1.20',
                      prefixIcon: Icon(Icons.computer_outlined),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _port,
                    enabled: !_running && !_starting,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Port',
                      prefixIcon: Icon(Icons.lan_outlined),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: _starting ? null : (_running ? _stop : _start),
                    icon: Icon(
                      _starting
                          ? Icons.hourglass_top
                          : (_running ? Icons.stop : Icons.play_arrow),
                    ),
                    label: Text(
                      _starting
                          ? 'Connecting…'
                          : (_running ? 'Stop streaming' : 'Start streaming'),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Stream status',
                      style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 12),
                  _StatusRow(label: 'Status', value: _status),
                  _StatusRow(
                      label: 'Audio sent',
                      value: '${(_bytes / 1024).toStringAsFixed(1)} KB'),
                  if (_includeVideo)
                    _StatusRow(
                      label: 'Screen frames sent',
                      value: '$_videoFrames',
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Icon(Icons.info_outline),
              title: Text(_includeVideo
                  ? 'Audio and screen capture'
                  : 'Playback capture'),
              subtitle: Text(
                _includeVideo
                    ? 'Android will ask for approval to share your screen. Some apps block audio capture. Keep this app open while streaming.'
                    : 'Android will ask for approval. Some apps block capture. Keep this app open while streaming.',
              ),
              isThreeLine: true,
            ),
          ),
        ],
      );
}

class _StatusRow extends StatelessWidget {
  const _StatusRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant),
              ),
            ),
            Text(value, style: Theme.of(context).textTheme.bodyLarge),
          ],
        ),
      );
}
