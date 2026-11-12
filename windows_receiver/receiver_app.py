"""Simple Windows desktop app for receiving phone PCM audio."""

import asyncio
import queue
import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import sounddevice as sd
from websockets.asyncio.server import serve

from audio_receiver import FRAME_BYTES, VolumeControl, receive_audio


class ReceiverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Phone to PC Audio")
        self.root.geometry("650x560")
        self.root.minsize(560, 500)

        self.events = queue.SimpleQueue()
        self.loop = None
        self.server = None
        self.stop_event = None
        self.worker = None
        self.closing = False
        self.client = None
        self.total_bytes = 0
        self.output_devices = {"System default": None}

        self.port_var = tk.StringVar(value="8765")
        self.output_var = tk.StringVar(value="System default")
        self.status_var = tk.StringVar(value="Stopped")
        self.client_var = tk.StringVar(value="Waiting for phone")
        self.bytes_var = tk.StringVar(value="0 B received")
        self.volume_control = VolumeControl()
        self.volume_var = tk.DoubleVar(value=100.0)
        self.volume_text = tk.StringVar(value="100%")

        self._build_ui()
        self._load_output_devices()
        self._refresh_addresses()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._process_events)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Phone to PC Audio", font=("Segoe UI", 21, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Receive phone audio over your private Wi-Fi or USB connection.",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 18))

        connection = ttk.LabelFrame(outer, text="Connection", padding=14)
        connection.pack(fill="x")
        ttk.Label(connection, text="Port").grid(row=0, column=0, sticky="w")
        self.port_entry = ttk.Entry(connection, textvariable=self.port_var, width=9)
        self.port_entry.grid(row=0, column=1, sticky="w", padx=(10, 22))
        ttk.Label(connection, text="Audio output").grid(row=0, column=2, sticky="w")
        self.output_combo = ttk.Combobox(
            connection,
            textvariable=self.output_var,
            state="readonly",
            width=34,
        )
        self.output_combo.grid(row=0, column=3, sticky="ew", padx=(10, 0))
        connection.columnconfigure(3, weight=1)

        self.address_label = ttk.Label(connection, text="PC addresses: checking…", justify="left")
        self.address_label.grid(row=1, column=0, columnspan=4, sticky="w", pady=(14, 0))

        volume = ttk.Frame(connection)
        volume.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Label(volume, text="Receiver volume").pack(side="left")
        self.volume_scale = ttk.Scale(
            volume,
            from_=0,
            to=100,
            variable=self.volume_var,
            command=self._on_volume_changed,
        )
        self.volume_scale.pack(side="left", fill="x", expand=True, padx=(12, 10))
        ttk.Label(volume, textvariable=self.volume_text, width=5, anchor="e").pack(side="left")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=16)
        self.start_button = ttk.Button(actions, text="Start receiver", command=self._start)
        self.start_button.pack(side="left")
        self.refresh_button = ttk.Button(actions, text="Refresh audio devices", command=self._load_output_devices)
        self.refresh_button.pack(side="left", padx=(10, 0))

        status = ttk.LabelFrame(outer, text="Status", padding=14)
        status.pack(fill="x")
        ttk.Label(status, text="Receiver:").grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(status, text="Phone:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(status, textvariable=self.client_var).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(status, text="Audio received:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(status, textvariable=self.bytes_var).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        instructions = ttk.LabelFrame(outer, text="Connect your phone", padding=14)
        instructions.pack(fill="x", pady=(16, 0))
        ttk.Label(
            instructions,
            text=(
                "Wi-Fi: connect both devices to the same private network, then enter one of the PC addresses above in the phone app.\n\n"
                "USB: run  adb reverse tcp:8765 tcp:8765  on the PC, then use  127.0.0.1  in the phone app."
            ),
            justify="left",
            wraplength=560,
        ).pack(anchor="w")

        log_box = ttk.LabelFrame(outer, text="Activity", padding=8)
        log_box.pack(fill="both", expand=True, pady=(16, 0))
        self.log_text = tk.Text(log_box, height=7, wrap="word", state="disabled", font=("Consolas", 9))
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

    def _load_output_devices(self):
        devices = {"System default": None}
        try:
            for index, device in enumerate(sd.query_devices()):
                if device["max_output_channels"] > 0:
                    name = f"{index}: {device['name']}"
                    devices[name] = index
        except Exception as error:
            self._log(f"Could not list audio outputs: {error}")
        self.output_devices = devices
        self.output_combo["values"] = list(devices)
        if self.output_var.get() not in devices:
            self.output_var.set("System default")
        self._log(f"Found {len(devices) - 1} audio output device(s).")

    def _on_volume_changed(self, value):
        percent = round(float(value))
        self.volume_control.set_percent(percent)
        self.volume_text.set(f"{percent}%")

    def _refresh_addresses(self):
        addresses = set()
        try:
            for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = result[4][0]
                if not ip.startswith("127.") and not ip.startswith("169.254."):
                    addresses.add(ip)
        except OSError:
            pass
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect(("192.0.2.1", 9))
                ip = probe.getsockname()[0]
                if not ip.startswith("127.") and not ip.startswith("169.254."):
                    addresses.add(ip)
            finally:
                probe.close()
        except OSError:
            pass
        wifi_addresses = sorted(addresses)
        address_text = ", ".join(wifi_addresses) if wifi_addresses else "No local IPv4 address found"
        self.address_label.configure(
            text=f"PC addresses for Wi-Fi: {address_text}\nUSB reverse address: 127.0.0.1"
        )

    def _start(self):
        try:
            port = int(self.port_var.get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port", "Enter a port number from 1 to 65535.", parent=self.root)
            return

        output_device = self.output_devices.get(self.output_var.get())
        self.total_bytes = 0
        self.bytes_var.set("0 B received")
        self.status_var.set("Starting…")
        self.client_var.set("Waiting for phone")
        self.start_button.configure(state="disabled")
        self.port_entry.configure(state="disabled")
        self.output_combo.configure(state="disabled")
        self._log(f"Starting receiver on port {port}…")
        self.worker = threading.Thread(
            target=self._server_worker,
            args=(port, output_device),
            name="PhoneToPcReceiver",
            daemon=True,
        )
        self.worker.start()

    def _server_worker(self, port, output_device):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve(port, output_device))
        self.loop.close()
        self.loop = None

    async def _serve(self, port, output_device):
        def on_event(name, value):
            self.events.put((name, value))

        handler = lambda websocket: receive_audio(
            websocket,
            output_device=output_device,
            volume_control=self.volume_control,
            on_event=on_event,
        )
        try:
            self.server = await serve(
                handler,
                "0.0.0.0",
                port,
                max_size=FRAME_BYTES * 8,
                ping_interval=20,
                ping_timeout=20,
            )
            self.stop_event = asyncio.Event()
            self.events.put(("started", port))
            await self.stop_event.wait()
            self.server.close()
            await self.server.wait_closed()
        except Exception as error:
            self.events.put(("server_error", str(error)))
        finally:
            self.server = None
            self.stop_event = None
            self.events.put(("stopped", None))

    def _stop(self):
        self.status_var.set("Stopping…")
        self.start_button.configure(state="disabled")
        if self.loop is not None and self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        else:
            self.events.put(("stopped", None))

    def _process_events(self):
        while True:
            try:
                name, value = self.events.get_nowait()
            except queue.Empty:
                break
            if name == "started":
                self.status_var.set(f"Listening on port {value}")
                self.start_button.configure(text="Stop receiver", state="normal", command=self._stop)
                self._log(f"Receiver ready at ws://0.0.0.0:{value}/audio")
                if self.closing:
                    self._stop()
            elif name == "connected":
                self.client = value
                self.client_var.set(str(value))
                self.status_var.set("Phone connected")
                self._log(f"Phone connected: {value}")
            elif name == "disconnected":
                self.client = None
                self.client_var.set("Waiting for phone")
                if self.server is not None:
                    self.status_var.set("Listening for phone")
                self._log(f"Phone disconnected: {value}")
            elif name == "bytes":
                self.total_bytes += value
                self.bytes_var.set(self._format_bytes(self.total_bytes))
            elif name == "warning":
                self._log(str(value))
            elif name == "error":
                self._log(f"Audio output error: {value}")
                self.status_var.set("Audio output error")
            elif name == "server_error":
                self._log(f"Could not start receiver: {value}")
                messagebox.showerror("Receiver error", str(value), parent=self.root)
            elif name == "stopped":
                self.client = None
                self.client_var.set("Waiting for phone")
                self.status_var.set("Stopped")
                self.start_button.configure(text="Start receiver", state="normal", command=self._start)
                self.port_entry.configure(state="normal")
                self.output_combo.configure(state="readonly")
                self._log("Receiver stopped.")
                if self.closing:
                    self.root.destroy()
        self.root.after(100, self._process_events)

    def _log(self, message):
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def _format_bytes(value):
        if value < 1024:
            return f"{value} B received"
        if value < 1024 * 1024:
            return f"{value / 1024:.1f} KB received"
        return f"{value / (1024 * 1024):.2f} MB received"

    def _on_close(self):
        if self.worker is not None and self.worker.is_alive():
            self.closing = True
            if self.stop_event is not None:
                self._stop()
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    ReceiverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
