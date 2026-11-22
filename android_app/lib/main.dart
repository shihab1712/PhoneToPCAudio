import 'dart:async';
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
            title: 'Phone to PC Audio',
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
          title: Text(_selectedIndex == 0 ? 'Phone to PC Audio' : 'Settings'),
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
  String _status = 'Ready';
  bool _running = false;
  int _bytes = 0;
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
      _bytes = 0;
    });
    try {
      final socket = WebSocketChannel.connect(
          Uri(scheme: 'ws', host: host, port: port, path: '/audio'));
      await socket.ready.timeout(const Duration(seconds: 5));
      _socket = socket;
      final deviceName = await _methods.invokeMethod<String>('getDeviceName') ??
          'Android device';
      socket.sink.add('DEVICE_NAME:$deviceName');
      await _methods.invokeMethod<void>('startCapture');
      _subscription = _audio.receiveBroadcastStream().listen((dynamic data) {
        if (data is Uint8List) {
          _socket?.sink.add(data);
          _bytes += data.length;
        }
        if (mounted) setState(() {});
      }, onError: (Object error) {
        if (mounted) setState(() => _status = 'Capture error: $error');
      });
      setState(() {
        _running = true;
        _status = 'Streaming';
      });
    } catch (error) {
      await _stop();
      setState(() => _status = 'Could not start: $error');
    }
  }

  Future<void> _stop() async {
    await _subscription?.cancel();
    _subscription = null;
    try {
      await _methods.invokeMethod<void>('stopCapture');
    } catch (_) {}
    await _socket?.sink.close();
    _socket = null;
    if (mounted)
      setState(() {
        _running = false;
        if (_status == 'Streaming') _status = 'Stopped';
      });
  }

  @override
  void dispose() {
    _subscription?.cancel();
    _socket?.sink.close();
    _methods.invokeMethod<void>('stopCapture');
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
                    onSelectionChanged: _running
                        ? null
                        : (selection) => _selectConnectionMode(selection.first),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _host,
                    enabled: !_running,
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
                    enabled: !_running,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Port',
                      prefixIcon: Icon(Icons.lan_outlined),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: _running ? _stop : _start,
                    icon: Icon(_running ? Icons.stop : Icons.play_arrow),
                    label:
                        Text(_running ? 'Stop streaming' : 'Start streaming'),
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
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Icon(Icons.info_outline),
              title: const Text('Playback capture'),
              subtitle: const Text(
                'Android will ask for approval. Some apps block capture. Keep this app open while streaming.',
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
