import 'dart:async';
import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

void main() => runApp(const PhoneToPcApp());

class PhoneToPcApp extends StatelessWidget {
  const PhoneToPcApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Phone to PC Audio',
    theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff176b5b)), useMaterial3: true),
    home: const StreamPage(),
  );
}

class StreamPage extends StatefulWidget {
  const StreamPage({super.key});
  @override
  State<StreamPage> createState() => _StreamPageState();
}

class _StreamPageState extends State<StreamPage> {
  static const _methods = MethodChannel('phonetopc/capture');
  static const _audio = EventChannel('phonetopc/audio');
  final _host = TextEditingController();
  final _port = TextEditingController(text: '8765');
  WebSocketChannel? _socket;
  StreamSubscription<dynamic>? _subscription;
  String _status = 'Ready';
  bool _running = false;
  int _bytes = 0;

  Future<void> _start() async {
    final host = _host.text.trim();
    final port = int.tryParse(_port.text.trim());
    if (host.isEmpty || port == null || port < 1 || port > 65535) {
      setState(() => _status = 'Enter a valid PC address and port.'); return;
    }
    setState(() { _status = 'Connecting…'; _bytes = 0; });
    try {
      final socket = WebSocketChannel.connect(Uri(scheme: 'ws', host: host, port: port, path: '/audio'));
      await socket.ready.timeout(const Duration(seconds: 5));
      _socket = socket;
      await _methods.invokeMethod<void>('startCapture');
      _subscription = _audio.receiveBroadcastStream().listen((dynamic data) {
        if (data is Uint8List) { _socket?.sink.add(data); _bytes += data.length; }
        if (mounted) setState(() {});
      }, onError: (Object error) { if (mounted) setState(() => _status = 'Capture error: $error'); });
      setState(() { _running = true; _status = 'Streaming'; });
    } catch (error) {
      await _stop();
      setState(() => _status = 'Could not start: $error');
    }
  }

  Future<void> _stop() async {
    await _subscription?.cancel(); _subscription = null;
    try { await _methods.invokeMethod<void>('stopCapture'); } catch (_) {}
    await _socket?.sink.close(); _socket = null;
    if (mounted) setState(() { _running = false; if (_status == 'Streaming') _status = 'Stopped'; });
  }

  @override
  void dispose() { _subscription?.cancel(); _socket?.sink.close(); _methods.invokeMethod<void>('stopCapture'); _host.dispose(); _port.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Phone to PC Audio')),
    body: ListView(padding: const EdgeInsets.all(24), children: [
      const Text('Stream eligible Android playback to your Windows PC over Wi-Fi or USB.', style: TextStyle(fontSize: 16)),
      const SizedBox(height: 24),
      TextField(controller: _host, enabled: !_running, keyboardType: TextInputType.url, decoration: const InputDecoration(labelText: 'PC address', border: OutlineInputBorder(), hintText: '192.168.1.20')),
      const SizedBox(height: 12),
      TextField(controller: _port, enabled: !_running, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Port', border: OutlineInputBorder())),
      const SizedBox(height: 24),
      FilledButton.icon(onPressed: _running ? _stop : _start, icon: Icon(_running ? Icons.stop : Icons.play_arrow), label: Text(_running ? 'Stop streaming' : 'Start streaming')),
      const SizedBox(height: 20),
      Text('Status: $_status'),
      Text('Audio sent: ${(_bytes / 1024).toStringAsFixed(1)} KB'),
      const SizedBox(height: 16),
      const Text('Android will ask you to approve playback capture. Some apps block audio capture. Keep this app open while streaming.', style: TextStyle(color: Colors.black54)),
    ]),
  );
}
