"""Simple Windows desktop app for receiving phone PCM audio."""

import asyncio
import ctypes
import json
from io import BytesIO
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

import sounddevice as sd
from websockets.asyncio.server import serve

from audio_receiver import AudioBufferControl, FRAME_BYTES, OutputDeviceControl, VolumeControl, receive_audio


APP_VERSION = "1.1.0"
LATEST_RELEASE_API = "https://api.github.com/repos/shihab1712/PhoneToPC/releases/latest"


def _version_tuple(value):
    match = re.match(r"v?(\d+(?:\.\d+){0,3})", str(value).strip(), re.IGNORECASE)
    if not match:
        return ()
    parts = [int(part) for part in match.group(1).split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])


class FlowCard(tk.Canvas):
    """Rounded card surface with a small animated teal hover sweep."""

    INSET = 10
    RADIUS = 18

    def __init__(self, master, *, colors, padding=10):
        super().__init__(
            master,
            background=colors["window"],
            highlightthickness=0,
            borderwidth=0,
            width=400,
            height=120,
        )
        self.surface_color = colors["container"]
        self.outline_color = colors["outline"]
        self.hover_color = colors["primary"]
        self._current_outline = self.outline_color
        self._hovered = False
        self._hover_enabled = True
        self._hover_job = None
        self._flow_job = None
        self._flow_position = 0.0

        self._surface = self.create_polygon(
            0, 0, 0, 0,
            fill=self.surface_color,
            outline=self.outline_color,
            width=1,
            smooth=True,
            splinesteps=24,
        )
        self._flow = self.create_line(
            0, 0, 0, 0,
            fill=self.hover_color,
            width=2,
            capstyle="round",
            state="hidden",
        )
        self.content = ttk.Frame(self, padding=padding, style="Card.TFrame")
        self._content_window = self.create_window(
            self.INSET,
            self.INSET,
            anchor="nw",
            window=self.content,
        )
        self.bind("<Configure>", self._resize_content, add="+")
        self.content.bind("<Configure>", self._sync_height, add="+")
        self._draw_surface()

    def _rounded_points(self, width, height):
        inset = 1
        radius = min(self.RADIUS, max(2, (width - 2) / 2), max(2, (height - 2) / 2))
        left, top, right, bottom = inset, inset, width - inset, height - inset
        points = [(left + radius, top), (right - radius, top)]
        corners = (
            (right - radius, top + radius, -90, 0),
            (right - radius, bottom - radius, 0, 90),
            (left + radius, bottom - radius, 90, 180),
            (left + radius, top + radius, 180, 270),
        )
        for cx, cy, start, end in corners:
            for step in range(1, 17):
                angle = math.radians(start + (end - start) * step / 16)
                points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
            if end == 0:
                points.append((right, bottom - radius))
            elif end == 90:
                points.append((left + radius, bottom))
            elif end == 180:
                points.append((left, top + radius))
        return [coordinate for point in points for coordinate in point]

    def _draw_surface(self):
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        self.coords(self._surface, *self._rounded_points(width, height))
        self.coords(self._flow, self.RADIUS, 2, self.RADIUS + 1, 2)

    def _resize_content(self, event):
        width = max(1, event.width - 2 * self.INSET)
        self.itemconfigure(self._content_window, width=width)
        self._draw_surface()

    def _sync_height(self, _event=None):
        if not self.winfo_exists():
            return
        required = self.content.winfo_reqheight() + 2 * self.INSET
        if abs(self.winfo_reqheight() - required) > 1:
            self.configure(height=required)

    def enable_hover(self):
        def bind_tree(widget):
            widget.bind("<Enter>", self._on_pointer_enter, add="+")
            widget.bind("<Leave>", self._on_pointer_leave, add="+")
            for child in widget.winfo_children():
                bind_tree(child)

        bind_tree(self)

    def _on_pointer_enter(self, _event=None):
        if not self._hover_enabled or self._hovered:
            return
        self._hovered = True
        self._animate_outline()
        self._flow_position = 0.0
        self.itemconfigure(self._flow, state="normal")
        self._animate_flow()

    def _on_pointer_leave(self, _event=None):
        if not self._hover_enabled:
            self._hovered = False
            if self._hover_job is not None:
                self.after_cancel(self._hover_job)
                self._hover_job = None
            if self._flow_job is not None:
                self.after_cancel(self._flow_job)
                self._flow_job = None
            self._current_outline = self.outline_color
            self.itemconfigure(self._surface, outline=self.outline_color, width=1)
            self.itemconfigure(self._flow, state="hidden")
            return
        self.after(25, self._check_pointer)

    def _check_pointer(self):
        if not self.winfo_exists():
            return
        x, y = self.winfo_pointerxy()
        inside = (
            self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
            and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height()
        )
        if inside or not self._hovered:
            return
        self._hovered = False
        self._animate_outline()
        if self._flow_job is not None:
            self.after_cancel(self._flow_job)
            self._flow_job = None
        self.itemconfigure(self._flow, state="hidden")

    @staticmethod
    def _mix_color(first, second, amount):
        first = tuple(int(first[index:index + 2], 16) for index in (1, 3, 5))
        second = tuple(int(second[index:index + 2], 16) for index in (1, 3, 5))
        mixed = tuple(round(a + (b - a) * amount) for a, b in zip(first, second))
        return "#" + "".join(f"{component:02x}" for component in mixed)

    def _animate_outline(self, step=0):
        if self._hover_job is not None:
            self.after_cancel(self._hover_job)
        start = self._current_outline
        target = self.hover_color if self._hovered else self.outline_color

        def frame(index):
            amount = min(1.0, index / 8)
            self._current_outline = self._mix_color(start, target, amount)
            self.itemconfigure(self._surface, outline=self._current_outline, width=1 + amount)
            if index < 8:
                self._hover_job = self.after(16, lambda: frame(index + 1))
            else:
                self._hover_job = None

        frame(step)

    def _animate_flow(self):
        width = self.winfo_width()
        usable = max(1, width - 2 * self.RADIUS)
        segment = min(44, usable)
        x1 = self.RADIUS + (usable - segment) * self._flow_position
        self.coords(self._flow, x1, 2, x1 + segment, 2)
        self._flow_position += 0.12
        if self._flow_position <= 1:
            self._flow_job = self.after(18, self._animate_flow)
        else:
            self._flow_job = None
            self.itemconfigure(self._flow, state="hidden")


class ReceiverApp:
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    HOTKEY_ACTIONS = {
        "up": "Volume up",
        "down": "Volume down",
        "mute": "Mute / unmute",
    }
    DEFAULT_HOTKEYS = {
        "up": {"modifiers": MOD_CONTROL | MOD_ALT, "vk": 0x26, "label": "Ctrl+Alt+Up"},
        "down": {"modifiers": MOD_CONTROL | MOD_ALT, "vk": 0x28, "label": "Ctrl+Alt+Down"},
        "mute": {"modifiers": MOD_CONTROL | MOD_ALT, "vk": 0x4D, "label": "Ctrl+Alt+M"},
    }
    DASHBOARD_SECTIONS = (
        ("settings", "Receiver settings"),
        ("status", "Receiver status"),
        ("wifi", "Wi-Fi stream"),
        ("usb", "USB stream"),
        ("shortcuts", "Global volume shortcuts"),
        ("activity", "Activity"),
        ("video", "Video stream"),
    )

    def __init__(self, root):
        self.root = root
        self.root.title("PhoneToPC")
        self.root.geometry("920x720")
        self.root.minsize(860, 680)
        self.style = ttk.Style(self.root)
        self._apply_theme()

        self.events = queue.SimpleQueue()
        self.video_frame_lock = threading.Lock()
        self.pending_video_frame = None
        self.connection_lock = threading.Lock()
        self.active_websocket = None
        self.display_power_lock = threading.Lock()
        self.phone_display_off = False
        self.display_power_desired = False
        self.video_stream_active = False
        self.display_power_serial = None
        self.phone_screen_size = None
        self.latest_video_jpeg = None
        self.fullscreen_video_window = None
        self.fullscreen_video_label = None
        self.fullscreen_video_photo = None
        self.settings_path = Path(os.environ.get("APPDATA", Path.home())) / "PhoneToPcAudio" / "settings.json"
        self.hotkey_config = {action: settings.copy() for action, settings in self.DEFAULT_HOTKEYS.items()}
        self.dashboard_order = [key for key, _ in self.DASHBOARD_SECTIONS]
        self.wifi_buffer_ms = 100
        self.usb_buffer_ms = 0
        self._load_hotkey_settings()
        self.wifi_buffer_control = AudioBufferControl(self.wifi_buffer_ms)
        self.usb_buffer_control = AudioBufferControl(self.usb_buffer_ms)
        self.shortcut_vars = {}
        self.capture_action = None
        self.hotkey_thread = None
        self.hotkey_thread_id = None
        self.muted_restore_percent = None
        self.loop = None
        self.server = None
        self.stop_event = None
        self.worker = None
        self.closing = False
        self.client = None
        self.client_device_name = None
        self.video_label = None
        self.video_placeholder = None
        self.video_photo = None
        self.video_source_size = None
        self.video_gesture_points = None
        self.video_gesture_started_at = 0.0
        self.transport_device_name = None
        self.active_transport = None
        self.adb_path = None
        self.start_failed = False
        self.latest_rtt_ms = None
        self.output_devices = {"System default": None}

        self.port_var = tk.StringVar(value="8765")
        self.output_var = tk.StringVar(value="System default")
        self.status_var = tk.StringVar(value="Stopped")
        self.client_var = tk.StringVar(value="Waiting for phone")
        self.network_rtt_var = tk.StringVar(value="—")
        self.estimated_delay_var = tk.StringVar(value="—")
        self.wifi_buffer_var = tk.DoubleVar(value=self.wifi_buffer_ms)
        self.wifi_buffer_text_var = tk.StringVar(value=f"{self.wifi_buffer_ms} ms")
        self.usb_buffer_var = tk.DoubleVar(value=self.usb_buffer_ms)
        self.usb_buffer_text_var = tk.StringVar(value=f"{self.usb_buffer_ms} ms")
        self.wifi_status_var = tk.StringVar(value="Ready to connect over Wi-Fi")
        self.usb_status_var = tk.StringVar(value="Ready to connect over USB")
        self.volume_control = VolumeControl()
        self.output_device_control = OutputDeviceControl()
        self.volume_var = tk.DoubleVar(value=100.0)
        self.volume_text = tk.StringVar(value="100%")
        self.remote_control_var = tk.BooleanVar(value=False)
        self.phone_mute_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._load_output_devices()
        self._refresh_addresses()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<KeyPress-f>", self._open_video_fullscreen, add="+")
        self.root.bind("<KeyPress-F>", self._open_video_fullscreen, add="+")
        self.root.after(100, self._process_events)
        self.root.after(16, self._process_pending_video_frame)
        self._start_hotkey_listener()

    def _apply_theme(self):
        """Use a Material 3-inspired surface palette that follows Windows light/dark mode."""
        dark = False
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                dark = winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        except (ImportError, OSError):
            pass

        if dark:
            self.colors = {
                "window": "#101413", "surface": "#181E1C", "container": "#202725",
                "raised": "#2B3330", "text": "#E0E5E2", "muted": "#C0C9C5",
                "outline": "#414A46", "primary": "#A0D0C4", "on_primary": "#00382F",
                "selected": "#354A44",
            }
        else:
            self.colors = {
                "window": "#F5F7F6", "surface": "#FFFFFF", "container": "#EDF2F0",
                "raised": "#DFE9E5", "text": "#191D1B", "muted": "#414945",
                "outline": "#D1DAD6", "primary": "#38685F", "on_primary": "#FFFFFF",
                "selected": "#D5E8E2",
            }

        c = self.colors
        self.root.configure(background=c["window"])
        self.style.theme_use("clam")
        self.style.configure("App.TFrame", background=c["window"])
        self.style.configure("Surface.TFrame", background=c["surface"])
        self.style.configure("Card.TFrame", background=c["container"])
        self.style.configure("App.TLabel", background=c["window"], foreground=c["text"], font=("Segoe UI", 9))
        self.style.configure("Muted.TLabel", background=c["window"], foreground=c["muted"], font=("Segoe UI", 9))
        self.style.configure("Card.TLabel", background=c["container"], foreground=c["text"], font=("Segoe UI", 9))
        self.style.configure("CardMuted.TLabel", background=c["container"], foreground=c["muted"], font=("Segoe UI", 9))
        self.style.configure("Card.TCheckbutton", background=c["container"], foreground=c["text"], font=("Segoe UI", 9))
        self.style.map("Card.TCheckbutton", background=[("active", c["container"])], foreground=[("disabled", c["muted"])])
        self.style.configure("Title.TLabel", background=c["window"], foreground=c["text"], font=("Segoe UI Semibold", 21))
        self.style.configure("Section.TLabel", background=c["container"], foreground=c["text"], font=("Segoe UI Semibold", 12))
        self.style.configure("Primary.TButton", font=("Segoe UI Semibold", 9), foreground=c["on_primary"], background=c["primary"], padding=(14, 7), borderwidth=0)
        self.style.map("Primary.TButton", background=[("active", c["primary"]), ("disabled", c["outline"])], foreground=[("disabled", c["muted"])])
        self.style.configure("Secondary.TButton", font=("Segoe UI Semibold", 9), foreground=c["text"], background=c["raised"], padding=(12, 6), borderwidth=0)
        self.style.map("Secondary.TButton", background=[("active", c["selected"])])
        self.style.configure("TEntry", fieldbackground=c["surface"], foreground=c["text"], insertcolor=c["text"], padding=6, borderwidth=1, relief="flat")
        self.style.configure("TCombobox", fieldbackground=c["surface"], background=c["surface"], foreground=c["text"], padding=6, arrowcolor=c["muted"])
        self.style.map("TCombobox", fieldbackground=[("readonly", c["surface"])], foreground=[("readonly", c["text"])])
        self.style.configure("Horizontal.TScale", background=c["container"], troughcolor=c["outline"], sliderthickness=14)
        self.style.configure("TScrollbar", background=c["raised"], troughcolor=c["container"], arrowcolor=c["muted"])

    def _build_ui(self):
        c = self.colors
        outer = ttk.Frame(self.root, padding=12, style="App.TFrame")
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x")
        header_text = ttk.Frame(header, style="App.TFrame")
        header_text.pack(side="left", fill="x", expand=True)
        ttk.Label(header_text, text="PhoneToPC", style="Title.TLabel").pack(anchor="w")
        self.dashboard_hint = ttk.Label(
            header_text,
            text="Stream Android audio over Wi-Fi or USB.",
            style="Muted.TLabel",
        )
        self.dashboard_hint.pack(anchor="w", pady=(2, 8))
        self.customize_button = ttk.Button(
            header,
            text="Edit dashboard",
            style="Secondary.TButton",
            command=self._toggle_dashboard_edit,
        )
        self.customize_button.pack(side="right", padx=(12, 0), pady=(2, 8))
        self.update_button = ttk.Button(
            header,
            text="Check for updates",
            style="Secondary.TButton",
            command=self._check_for_updates,
        )
        self.update_button.pack(side="right", padx=(8, 0), pady=(2, 8))
        self.add_section_button = ttk.Menubutton(
            header, text="Add section", style="Secondary.TButton"
        )
        self.add_section_menu = tk.Menu(self.add_section_button, tearoff=False)
        self.add_section_button.configure(menu=self.add_section_menu)

        dashboard_holder = ttk.Frame(outer, style="App.TFrame")
        dashboard_holder.pack(fill="both", expand=True)
        self.dashboard_canvas = tk.Canvas(
            dashboard_holder,
            background=c["window"],
            highlightthickness=0,
            borderwidth=0,
        )
        self.dashboard_canvas.pack(side="left", fill="both", expand=True)
        self.dashboard_scrollbar = ttk.Scrollbar(
            dashboard_holder,
            orient="vertical",
            command=self.dashboard_canvas.yview,
        )
        self.dashboard_scrollbar.pack(side="right", fill="y")
        self.dashboard_canvas.configure(yscrollcommand=self.dashboard_scrollbar.set)
        self.dashboard_frame = ttk.Frame(self.dashboard_canvas, style="App.TFrame")
        self._dashboard_window = self.dashboard_canvas.create_window(
            (0, 0), window=self.dashboard_frame, anchor="nw"
        )
        self.dashboard_frame.bind("<Configure>", self._update_dashboard_scrollregion)
        self.dashboard_canvas.bind(
            "<Configure>",
            lambda event: self.dashboard_canvas.itemconfigure(
                self._dashboard_window, width=event.width
            ),
        )
        self.dashboard_canvas.bind("<Enter>", self._enable_dashboard_wheel)
        self.dashboard_canvas.bind("<Leave>", self._disable_dashboard_wheel)
        self.dashboard_frame.grid_columnconfigure((0, 1), weight=1, uniform="dashboard")

        settings_card = FlowCard(self.dashboard_frame, colors=c, padding=10)
        settings = settings_card.content
        ttk.Label(settings, text="Receiver settings", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        ttk.Label(settings, text="Port", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w")
        self.port_entry = ttk.Entry(settings, textvariable=self.port_var, width=9)
        self.port_entry.grid(row=1, column=1, sticky="w", padx=(8, 16))
        ttk.Label(settings, text="Audio output", style="CardMuted.TLabel").grid(row=1, column=2, sticky="w")
        self.output_combo = ttk.Combobox(
            settings,
            textvariable=self.output_var,
            state="readonly",
            width=26,
        )
        self.output_combo.grid(row=1, column=3, sticky="ew", padx=(10, 0))
        self.output_combo.bind("<<ComboboxSelected>>", self._on_output_selected)
        settings.columnconfigure(3, weight=1)

        volume = ttk.Frame(settings, style="Card.TFrame")
        volume.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(7, 0))
        ttk.Label(volume, text="Receiver volume", style="Card.TLabel").pack(side="left")
        self.volume_scale = ttk.Scale(
            volume,
            from_=0,
            to=100,
            variable=self.volume_var,
            command=self._on_volume_changed,
        )
        self.volume_scale.pack(side="left", fill="x", expand=True, padx=(12, 10))
        ttk.Label(volume, textvariable=self.volume_text, width=5, anchor="e", style="Card.TLabel").pack(side="left")

        shortcuts_card = FlowCard(self.dashboard_frame, colors=c, padding=10)
        shortcuts = shortcuts_card.content
        ttk.Label(shortcuts, text="Global volume shortcuts", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            shortcuts,
            text="Works while minimized. Volume changes by 5% per press.",
            style="CardMuted.TLabel",
            wraplength=700,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 4))
        self.capture_buttons = {}
        for row, (action, title) in enumerate(self.HOTKEY_ACTIONS.items(), start=2):
            ttk.Label(shortcuts, text=title, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=1)
            shortcut_var = tk.StringVar(value=self.hotkey_config[action]["label"])
            self.shortcut_vars[action] = shortcut_var
            ttk.Label(shortcuts, textvariable=shortcut_var, style="CardMuted.TLabel", width=22).grid(
                row=row, column=1, sticky="w", padx=(10, 8), pady=1
            )
            button = ttk.Button(
                shortcuts,
                text="Change",
                style="Secondary.TButton",
                command=lambda selected_action=action: self._begin_hotkey_capture(selected_action),
            )
            button.grid(row=row, column=2, sticky="e", pady=1)
            self.capture_buttons[action] = button
        shortcuts.columnconfigure(1, weight=1)

        wifi_card = FlowCard(self.dashboard_frame, colors=c, padding=10)
        wifi = wifi_card.content
        ttk.Label(wifi, text="Wi-Fi stream", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            wifi,
            text="Connect both devices to the same Wi-Fi network.",
            style="CardMuted.TLabel",
            wraplength=280,
            justify="left",
        ).pack(anchor="w", pady=(4, 6))
        self.wifi_address_label = ttk.Label(
            wifi, text="PC addresses: checking…", style="Card.TLabel", wraplength=280, justify="left"
        )
        self.wifi_address_label.pack(anchor="w", fill="x")
        buffer_heading = ttk.Frame(wifi, style="Card.TFrame")
        buffer_heading.pack(fill="x", pady=(7, 0))
        ttk.Label(buffer_heading, text="Wi-Fi audio buffer", style="Card.TLabel").pack(side="left")
        ttk.Label(buffer_heading, textvariable=self.wifi_buffer_text_var, style="CardMuted.TLabel").pack(side="right")
        self.wifi_buffer_scale = ttk.Scale(
            wifi,
            from_=0,
            to=500,
            variable=self.wifi_buffer_var,
            command=self._on_wifi_buffer_changed,
        )
        self.wifi_buffer_scale.pack(fill="x", pady=(4, 1))
        self.wifi_buffer_scale.bind("<ButtonRelease-1>", lambda _event: self._save_hotkey_settings())
        self.wifi_buffer_scale.bind("<KeyRelease>", lambda _event: self._save_hotkey_settings())
        ttk.Label(
            wifi,
            text="More buffer reduces dropouts but adds delay.",
            style="CardMuted.TLabel",
            wraplength=360,
        ).pack(anchor="w")
        self.wifi_button = ttk.Button(
            wifi, text="Start Wi-Fi receiver", command=lambda: self._start("wifi"), style="Primary.TButton"
        )
        self.wifi_button.pack(anchor="w", pady=(7, 4))
        ttk.Label(wifi, textvariable=self.wifi_status_var, style="CardMuted.TLabel", wraplength=280).pack(anchor="w")

        usb_card = FlowCard(self.dashboard_frame, colors=c, padding=10)
        usb = usb_card.content
        ttk.Label(usb, text="USB stream", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            usb,
            text="Connect the phone by USB and approve this PC.",
            style="CardMuted.TLabel",
            wraplength=280,
            justify="left",
        ).pack(anchor="w", pady=(4, 5))
        ttk.Label(
            usb,
            text="Forwarding starts automatically. Phone address: 127.0.0.1.",
            style="Card.TLabel",
            wraplength=280,
            justify="left",
        ).pack(anchor="w", fill="x")
        usb_buffer_heading = ttk.Frame(usb, style="Card.TFrame")
        usb_buffer_heading.pack(fill="x", pady=(7, 0))
        ttk.Label(usb_buffer_heading, text="USB audio buffer", style="Card.TLabel").pack(side="left")
        ttk.Label(usb_buffer_heading, textvariable=self.usb_buffer_text_var, style="CardMuted.TLabel").pack(side="right")
        self.usb_buffer_scale = ttk.Scale(
            usb, from_=0, to=500, variable=self.usb_buffer_var, command=self._on_usb_buffer_changed
        )
        self.usb_buffer_scale.pack(fill="x", pady=(4, 1))
        self.usb_buffer_scale.bind("<ButtonRelease-1>", lambda _event: self._save_hotkey_settings())
        self.usb_buffer_scale.bind("<KeyRelease>", lambda _event: self._save_hotkey_settings())
        ttk.Label(
            usb, text="More buffer reduces dropouts but adds delay.",
            style="CardMuted.TLabel", wraplength=360,
        ).pack(anchor="w")
        self.usb_button = ttk.Button(
            usb, text="Start USB receiver", command=lambda: self._start("usb"), style="Primary.TButton"
        )
        self.usb_button.pack(anchor="w", pady=(7, 4))
        ttk.Label(usb, textvariable=self.usb_status_var, style="CardMuted.TLabel", wraplength=280).pack(anchor="w")

        actions = ttk.Frame(settings, style="Card.TFrame")
        actions.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.refresh_button = ttk.Button(actions, text="Refresh audio devices", command=self._load_output_devices, style="Secondary.TButton")
        self.refresh_button.pack(side="left")
        ttk.Checkbutton(
            actions,
            text="Mute phone media while connected (restore on disconnect)",
            variable=self.phone_mute_var,
            command=self._on_phone_mute_toggle,
            style="Card.TCheckbutton",
        ).pack(side="left", padx=(10, 0))

        status_card = FlowCard(self.dashboard_frame, colors=c, padding=10)
        status = status_card.content
        status.grid_columnconfigure(1, weight=1)
        ttk.Label(status, text="Receiver status", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Label(status, text="Receiver", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(status, textvariable=self.status_var, style="Card.TLabel", font=("Segoe UI Semibold", 10)).grid(row=1, column=1, sticky="w", padx=(18, 0))
        ttk.Label(status, text="Phone", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(status, textvariable=self.client_var, style="Card.TLabel").grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(4, 0))
        ttk.Label(status, text="Network RTT", style="CardMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Label(status, textvariable=self.network_rtt_var, style="Card.TLabel").grid(row=3, column=1, sticky="w", padx=(10, 0), pady=(4, 0))
        ttk.Label(status, text="Estimated audio delay", style="CardMuted.TLabel").grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Label(status, textvariable=self.estimated_delay_var, style="Card.TLabel").grid(row=4, column=1, sticky="w", padx=(10, 0), pady=(4, 0))
        ttk.Label(
            status,
            text="Estimate includes network, buffer, and capture delay.",
            style="CardMuted.TLabel",
            wraplength=400,
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        log_card = FlowCard(self.dashboard_frame, colors=c, padding=10)
        log_box = log_card.content
        ttk.Label(log_box, text="Activity", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        log_area = ttk.Frame(log_box, style="Card.TFrame")
        log_area.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_area, height=3, wrap="word", state="disabled", font=("Segoe UI", 9),
                                bg=c["surface"], fg=c["text"], insertbackground=c["text"],
                                selectbackground=c["selected"], relief="flat", padx=8, pady=6)
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_scrollbar = ttk.Scrollbar(log_area, orient="vertical", command=self.log_text.yview)
        self.log_scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=self.log_scrollbar.set)

        video_card = FlowCard(self.dashboard_frame, colors=c, padding=10)
        video = video_card.content
        ttk.Label(video, text="Video stream", style="Section.TLabel").pack(anchor="w", pady=(0, 5))
        ttk.Label(
            video,
            text="Choose Audio + video on your phone to share its screen.",
            style="CardMuted.TLabel",
            wraplength=700,
        ).pack(anchor="w", pady=(0, 6))
        self.video_placeholder = tk.Label(
            video,
            text="Waiting for phone screen",
            height=6,
            anchor="center",
            justify="center",
            wraplength=700,
            background=c["surface"],
            foreground=c["muted"],
            highlightthickness=1,
            highlightbackground=c["outline"],
        )
        self.video_placeholder.pack(fill="x", expand=True)
        self.video_label = tk.Label(
            video,
            anchor="center",
            background=c["surface"],
            highlightthickness=1,
            highlightbackground=c["outline"],
        )
        self.video_label.bind("<ButtonPress-1>", self._on_video_mouse_press)
        self.video_label.bind("<B1-Motion>", self._on_video_mouse_motion)
        self.video_label.bind("<ButtonRelease-1>", self._on_video_mouse_release)
        self.fullscreen_video_button = ttk.Button(
            video,
            text="Fullscreen (F)",
            command=self._open_video_fullscreen,
            style="Secondary.TButton",
            state="disabled",
        )
        self.fullscreen_video_button.pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(
            video,
            text="Allow mouse control",
            variable=self.remote_control_var,
            command=self._on_remote_control_toggle,
            style="Card.TCheckbutton",
        ).pack(anchor="w", pady=(6, 0))
        self.display_power_var = tk.BooleanVar(value=False)
        self.display_power_check = ttk.Checkbutton(
            video,
            text="Turn off phone display while mirroring (Android 15+; USB debugging required)",
            variable=self.display_power_var,
            command=self._on_display_power_toggle,
            style="Card.TCheckbutton",
            state="disabled",
        )
        self.display_power_check.pack(anchor="w", pady=(4, 0))

        self.dashboard_cards = {
            "settings": settings_card,
            "status": status_card,
            "wifi": wifi_card,
            "usb": usb_card,
            "shortcuts": shortcuts_card,
            "activity": log_card,
            "video": video_card,
        }
        self.drag_placeholder = ttk.Frame(self.dashboard_frame, style="Card.TFrame")
        self.drag_placeholder.grid_propagate(False)
        self.dashboard_editing = False
        self._drag_state = None
        self._remove_buttons = {}
        for key, card in self.dashboard_cards.items():
            button = ttk.Button(
                card, text="×", width=2, style="Secondary.TButton",
                command=lambda section=key: self._remove_dashboard_section(section),
            )
            self._remove_buttons[key] = button
            card.bind("<ButtonPress-1>", lambda event, section=key: self._start_card_drag(event, section), add="+")
            card.bind("<B1-Motion>", self._move_card_drag, add="+")
            card.bind("<ButtonRelease-1>", self._finish_card_drag, add="+")
            self._bind_card_drag_children(card, key)
        self._apply_dashboard_layout()
        self.flow_cards = list(self.dashboard_cards.values())
        for card in self.flow_cards:
            card.enable_hover()

    def _update_dashboard_scrollregion(self, _event=None):
        bounds = self.dashboard_canvas.bbox("all")
        self.dashboard_canvas.configure(scrollregion=bounds or (0, 0, 0, 0))

    def _enable_dashboard_wheel(self, _event=None):
        self.root.bind_all("<MouseWheel>", self._on_dashboard_mousewheel)
        self.root.bind_all("<Button-4>", self._on_dashboard_mousewheel)
        self.root.bind_all("<Button-5>", self._on_dashboard_mousewheel)

    def _disable_dashboard_wheel(self, _event=None):
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")

    def _on_dashboard_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -int(event.delta / 120) if event.delta else 0
        if delta:
            self.dashboard_canvas.yview_scroll(delta * 3, "units")
        return "break"

    def _load_hotkey_settings(self):
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            saved_buffer = int(saved.get("wifi_buffer_ms", self.wifi_buffer_ms))
            if 0 <= saved_buffer <= 500:
                self.wifi_buffer_ms = saved_buffer
            saved_usb_buffer = int(saved.get("usb_buffer_ms", self.usb_buffer_ms))
            if 0 <= saved_usb_buffer <= 500:
                self.usb_buffer_ms = saved_usb_buffer
            all_sections = {key for key, _ in self.DASHBOARD_SECTIONS}
            saved_order = saved.get("dashboard_order", self.dashboard_order)
            saved_hidden = saved.get("dashboard_hidden", [])
            if isinstance(saved_order, list) and isinstance(saved_hidden, list):
                hidden = {key for key in saved_hidden if key in all_sections}
                order = [key for key in saved_order if key in all_sections and key not in hidden]
                order.extend(key for key, _ in self.DASHBOARD_SECTIONS if key not in hidden and key not in order)
                self.dashboard_order = order
            for action in self.HOTKEY_ACTIONS:
                value = saved.get("hotkeys", {}).get(action)
                if not isinstance(value, dict):
                    continue
                modifiers = int(value.get("modifiers", 0))
                virtual_key = int(value.get("vk", 0))
                label = str(value.get("label", ""))
                if modifiers & (self.MOD_CONTROL | self.MOD_ALT) and 0 < virtual_key <= 255 and label:
                    self.hotkey_config[action] = {
                        "modifiers": modifiers & (self.MOD_CONTROL | self.MOD_ALT | self.MOD_SHIFT),
                        "vk": virtual_key,
                        "label": label,
                    }
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _save_hotkey_settings(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(
                json.dumps(
                    {
                        "hotkeys": self.hotkey_config,
                        "wifi_buffer_ms": self.wifi_buffer_control.get_ms(),
                        "usb_buffer_ms": self.usb_buffer_control.get_ms(),
                        "dashboard_order": self.dashboard_order,
                        "dashboard_hidden": [
                            key for key, _ in self.DASHBOARD_SECTIONS if key not in self.dashboard_order
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return True
        except OSError as error:
            self._log(f"Could not save keyboard shortcuts: {error}")
            return False

    def _apply_dashboard_layout(self):
        dragged_key = (
            self._drag_state.get("key")
            if self._drag_state and self._drag_state.get("moved")
            else None
        )
        for card in self.dashboard_cards.values():
            card.grid_forget()
        if not dragged_key:
            self.drag_placeholder.grid_forget()
        for index, key in enumerate(self.dashboard_order):
            row, column = divmod(index, 2)
            last_full_width = index == len(self.dashboard_order) - 1 and column == 0
            target = self.drag_placeholder if key == dragged_key else self.dashboard_cards[key]
            target.grid(
                row=row,
                column=column,
                columnspan=2 if last_full_width else 1,
                sticky="nsew",
                padx=(0, 5) if column == 0 and not last_full_width else (5, 0) if column else 0,
                pady=(0, 8),
            )
        for key, button in self._remove_buttons.items():
            if self.dashboard_editing and key in self.dashboard_order:
                button.place(relx=1.0, x=-16, y=16, anchor="ne")
                self.dashboard_cards[key].content.configure(padding=(10, 26, 10, 10))
            else:
                button.place_forget()
                self.dashboard_cards[key].content.configure(padding=10)

    def _animate_dashboard_drop(self, key, start, target, frame):
        if not self._drag_state or self._drag_state.get("key") != key:
            return
        progress = min(1.0, frame / 10)
        eased = 1 - (1 - progress) ** 3
        values = tuple(round(a + (b - a) * eased) for a, b in zip(start, target))
        self.dashboard_cards[key].place(
            x=values[0], y=values[1], width=max(1, values[2]), height=max(1, values[3])
        )
        if frame < 10:
            self.root.after(12, lambda: self._animate_dashboard_drop(key, start, target, frame + 1))
            return
        self._drag_state = None
        self.dashboard_cards[key].place_forget()
        self.drag_placeholder.grid_forget()
        self._apply_dashboard_layout()
        for card in self.dashboard_cards.values():
            card._hover_enabled = not self.dashboard_editing
        self._refresh_add_section_menu()
        self._save_hotkey_settings()

    def _bind_card_drag_children(self, widget, key):
        for child in widget.winfo_children():
            if child in (self.video_label, self.video_placeholder):
                continue
            if not isinstance(child, (tk.Button, tk.Entry, tk.Scale, ttk.Button, ttk.Checkbutton, ttk.Entry, ttk.Combobox, ttk.Scale, ttk.Scrollbar)):
                child.bind("<ButtonPress-1>", lambda event, section=key: self._start_card_drag(event, section), add="+")
                child.bind("<B1-Motion>", self._move_card_drag, add="+")
                child.bind("<ButtonRelease-1>", self._finish_card_drag, add="+")
                self._bind_card_drag_children(child, key)

    def _toggle_dashboard_edit(self):
        self.dashboard_editing = not self.dashboard_editing
        for card in self.dashboard_cards.values():
            card._hover_enabled = not self.dashboard_editing
        if self.dashboard_editing:
            self.customize_button.configure(text="Done editing")
            self.dashboard_hint.configure(text="Drag cards to rearrange. Use × to hide a section; Add section restores it.")
            self.add_section_button.pack(side="right", padx=(0, 8), pady=(2, 8))
        else:
            self.customize_button.configure(text="Edit dashboard")
            self.dashboard_hint.configure(text="Stream Android audio over Wi-Fi or USB.")
            self.add_section_button.pack_forget()
            self._save_hotkey_settings()
        self._apply_dashboard_layout()
        self._refresh_add_section_menu()

    def _refresh_add_section_menu(self):
        self.add_section_menu.delete(0, "end")
        hidden = [(key, label) for key, label in self.DASHBOARD_SECTIONS if key not in self.dashboard_order]
        if not hidden:
            self.add_section_menu.add_command(label="All sections are on the dashboard", state="disabled")
            return
        for key, label in hidden:
            self.add_section_menu.add_command(label=label, command=lambda section=key: self._add_dashboard_section(section))

    def _remove_dashboard_section(self, key):
        if key in self.dashboard_order:
            self.dashboard_order.remove(key)
            self._apply_dashboard_layout()
            self._refresh_add_section_menu()
            self._save_hotkey_settings()

    def _add_dashboard_section(self, key):
        if key not in self.dashboard_order:
            self.dashboard_order.append(key)
            self._apply_dashboard_layout()
            self._refresh_add_section_menu()
            self._save_hotkey_settings()

    def _start_card_drag(self, event, key):
        if not self.dashboard_editing or key not in self.dashboard_order:
            return
        card = self.dashboard_cards[key]
        self._drag_state = {
            "key": key,
            "start_x": event.x_root,
            "start_y": event.y_root,
            "origin_x": card.winfo_x(),
            "origin_y": card.winfo_y(),
            "width": card.winfo_width(),
            "height": card.winfo_height(),
            "moved": False,
        }

    def _move_card_drag(self, event):
        state = self._drag_state
        if not state or not self.dashboard_editing:
            return
        card = self.dashboard_cards[state["key"]]
        dx, dy = event.x_root - state["start_x"], event.y_root - state["start_y"]
        if not state["moved"] and abs(dx) + abs(dy) < 7:
            return
        if not state["moved"]:
            state["moved"] = True
            card.grid_remove()
            self.drag_placeholder.configure(width=state["width"], height=state["height"])
            self._apply_dashboard_layout()
            card.place(x=state["origin_x"], y=state["origin_y"], width=state["width"], height=state["height"])
            card.lift()
        card.place(x=state["origin_x"] + dx, y=state["origin_y"] + dy,
                   width=state["width"], height=state["height"])
        current_index = self.dashboard_order.index(state["key"])
        center_x = card.winfo_x() + card.winfo_width() / 2
        center_y = card.winfo_y() + card.winfo_height() / 2
        threshold = 24
        direction = 0
        if current_index + 1 < len(self.dashboard_order):
            neighbor = self.dashboard_cards[self.dashboard_order[current_index + 1]]
            nx = neighbor.winfo_x() + neighbor.winfo_width() / 2
            ny = neighbor.winfo_y() + neighbor.winfo_height() / 2
            if center_y > ny + threshold or (abs(center_y - ny) <= threshold and center_x > nx + threshold):
                direction = 1
        if not direction and current_index > 0:
            neighbor = self.dashboard_cards[self.dashboard_order[current_index - 1]]
            nx = neighbor.winfo_x() + neighbor.winfo_width() / 2
            ny = neighbor.winfo_y() + neighbor.winfo_height() / 2
            if center_y < ny - threshold or (abs(center_y - ny) <= threshold and center_x < nx - threshold):
                direction = -1
        if direction:
            neighbor_index = current_index + direction
            self.dashboard_order[current_index], self.dashboard_order[neighbor_index] = (
                self.dashboard_order[neighbor_index], self.dashboard_order[current_index]
            )
            self._apply_dashboard_layout()

    def _finish_card_drag(self, _event=None):
        state = self._drag_state
        if state and state["moved"]:
            self._apply_dashboard_layout()
            index = self.dashboard_order.index(state["key"])
            row, column = divmod(index, 2)
            span = 2 if index == len(self.dashboard_order) - 1 and column == 0 else 1
            x, y, width, height = self.dashboard_frame.grid_bbox(column, row, span, 1)
            left_pad = 5 if column else 0
            top_pad = 0
            target = (x + left_pad, y + top_pad, max(1, width - left_pad - (5 if span == 1 and column == 0 else 0)), max(1, height))
            current = self.dashboard_cards[state["key"]].place_info()
            start = tuple(int(float(current[name])) for name in ("x", "y", "width", "height"))
            self._animate_dashboard_drop(state["key"], start, target, 0)
        else:
            self._drag_state = None

    def _begin_hotkey_capture(self, action):
        if self.capture_action is not None:
            self.capture_buttons[self.capture_action].configure(text="Change")
        self.capture_action = action
        self.shortcut_vars[action].set("Press shortcut… (Esc cancels)")
        self.capture_buttons[action].configure(text="Listening…")
        self.root.bind_all("<KeyPress>", self._capture_hotkey)
        self.root.focus_force()

    def _capture_hotkey(self, event):
        action = self.capture_action
        if action is None:
            return
        if event.keysym in ("Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R"):
            return "break"
        if event.keysym == "Escape":
            self._cancel_hotkey_capture()
            return "break"

        modifiers = 0
        if event.state & 0x0004:
            modifiers |= self.MOD_CONTROL
        if event.state & 0x0008:
            modifiers |= self.MOD_ALT
        if event.state & 0x0001:
            modifiers |= self.MOD_SHIFT
        if not modifiers & (self.MOD_CONTROL | self.MOD_ALT):
            self.shortcut_vars[action].set("Include Ctrl or Alt")
            return "break"

        virtual_key = int(event.keycode)
        if not 0 < virtual_key <= 255:
            return "break"
        for other_action, current in self.hotkey_config.items():
            if other_action != action and current["modifiers"] == modifiers and current["vk"] == virtual_key:
                self.shortcut_vars[action].set("Already assigned")
                self.root.after(1200, lambda: self.shortcut_vars[action].set(self.hotkey_config[action]["label"]))
                self._cancel_hotkey_capture(restore_label=False)
                return "break"

        key_name = {
            "Prior": "Page Up",
            "Next": "Page Down",
            "Return": "Enter",
            "space": "Space",
            "plus": "+",
            "minus": "-",
        }.get(event.keysym, event.keysym.upper() if len(event.keysym) == 1 else event.keysym)
        parts = []
        if modifiers & self.MOD_CONTROL:
            parts.append("Ctrl")
        if modifiers & self.MOD_ALT:
            parts.append("Alt")
        if modifiers & self.MOD_SHIFT:
            parts.append("Shift")
        parts.append(key_name)
        self.hotkey_config[action] = {"modifiers": modifiers, "vk": virtual_key, "label": "+".join(parts)}
        self.shortcut_vars[action].set(self.hotkey_config[action]["label"])
        self._cancel_hotkey_capture(restore_label=False)
        self._save_hotkey_settings()
        self._restart_hotkey_listener()
        self._log(f"Global shortcut set: {self.HOTKEY_ACTIONS[action]} — {self.hotkey_config[action]['label']}")
        return "break"

    def _cancel_hotkey_capture(self, restore_label=True):
        action = self.capture_action
        self.root.unbind_all("<KeyPress>")
        self.capture_action = None
        if action is not None:
            self.capture_buttons[action].configure(text="Change")
            if restore_label:
                self.shortcut_vars[action].set(self.hotkey_config[action]["label"])

    def _restart_hotkey_listener(self):
        self._stop_hotkey_listener()
        self._start_hotkey_listener()

    def _start_hotkey_listener(self):
        self.hotkey_thread = threading.Thread(
            target=self._hotkey_listener,
            args=({action: value.copy() for action, value in self.hotkey_config.items()},),
            name="PhoneToPcHotkeys",
            daemon=True,
        )
        self.hotkey_thread.start()

    def _stop_hotkey_listener(self):
        thread = self.hotkey_thread
        thread_id = self.hotkey_thread_id
        if thread is None:
            return
        if thread_id is not None:
            try:
                ctypes.windll.user32.PostThreadMessageW(thread_id, self.WM_QUIT, 0, 0)
            except (AttributeError, OSError):
                pass
        if thread is not threading.current_thread():
            thread.join(timeout=2)
        if not thread.is_alive():
            self.hotkey_thread = None
            self.hotkey_thread_id = None

    def _hotkey_listener(self, configuration):
        from ctypes import wintypes

        class Message(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("lPrivate", wintypes.DWORD),
            ]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [ctypes.POINTER(Message), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(Message), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        registered = {}
        message = Message()
        try:
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self.hotkey_thread_id = kernel32.GetCurrentThreadId()
            for hotkey_id, (action, shortcut) in enumerate(configuration.items(), start=1):
                modifiers = shortcut["modifiers"] | self.MOD_NOREPEAT
                if user32.RegisterHotKey(None, hotkey_id, modifiers, shortcut["vk"]):
                    registered[hotkey_id] = action
                else:
                    error_code = ctypes.get_last_error()
                    self.events.put(("hotkey_error", f"{shortcut['label']} could not be registered (Windows error {error_code})."))
            self.events.put(("hotkeys_ready", len(registered)))

            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == self.WM_HOTKEY and message.wParam in registered:
                    self.events.put(("hotkey", registered[message.wParam]))
        except Exception as error:
            self.events.put(("hotkey_error", f"Global shortcuts are unavailable: {error}"))
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
            self.hotkey_thread_id = None

    def _apply_volume_shortcut(self, action):
        current = round(self.volume_var.get())
        if action == "up":
            self._set_volume_from_shortcut(min(100, current + 5))
        elif action == "down":
            self._set_volume_from_shortcut(max(0, current - 5))
        elif action == "mute":
            if current > 0:
                self.muted_restore_percent = current
                self._set_volume_from_shortcut(0)
            else:
                restored = self.muted_restore_percent or 100
                self.muted_restore_percent = None
                self._set_volume_from_shortcut(restored)

    def _set_volume_from_shortcut(self, percent):
        self.volume_var.set(percent)
        self._on_volume_changed(percent)
        self._log(f"Receiver volume: {percent}%")

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
            self._on_output_selected()
        self._log(f"Found {len(devices) - 1} audio output device(s).")

    def _on_output_selected(self, _event=None):
        device = self.output_devices.get(self.output_var.get())
        self.output_device_control.set_device(device)
        label = self.output_var.get() or "System default"
        self._log(f"Audio output selected: {label}")

    def _on_volume_changed(self, value):
        percent = round(float(value))
        self.volume_control.set_percent(percent)
        self.volume_text.set(f"{percent}%")
        if percent > 0:
            self.muted_restore_percent = None

    def _on_wifi_buffer_changed(self, value):
        milliseconds = max(0, min(500, int(round(float(value) / 20.0) * 20)))
        if round(self.wifi_buffer_var.get()) != milliseconds:
            self.wifi_buffer_var.set(milliseconds)
        self.wifi_buffer_control.set_ms(milliseconds)
        self.wifi_buffer_text_var.set(f"{milliseconds} ms")
        self._update_latency_display()

    def _on_usb_buffer_changed(self, value):
        milliseconds = max(0, min(500, int(round(float(value) / 20.0) * 20)))
        if round(self.usb_buffer_var.get()) != milliseconds:
            self.usb_buffer_var.set(milliseconds)
        self.usb_buffer_control.set_ms(milliseconds)
        self.usb_buffer_text_var.set(f"{milliseconds} ms")
        self._update_latency_display()

    def _update_latency_display(self):
        if self.latest_rtt_ms is None:
            self.network_rtt_var.set("—")
            self.estimated_delay_var.set("—")
            return
        self.network_rtt_var.set(f"{self.latest_rtt_ms:.1f} ms RTT")
        if self.active_transport == "wifi":
            buffer_ms = self.wifi_buffer_control.get_ms()
        elif self.active_transport == "usb":
            buffer_ms = self.usb_buffer_control.get_ms()
        else:
            buffer_ms = 0
        estimated_ms = self.latest_rtt_ms / 2.0 + buffer_ms + 10.0
        self.estimated_delay_var.set(f"≈ {estimated_ms:.0f} ms")

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
        self.wifi_address_label.configure(text=f"PC address for Wi-Fi:\n{address_text}")

    def _start(self, transport):
        try:
            port = int(self.port_var.get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port", "Enter a port number from 1 to 65535.", parent=self.root)
            return

        output_device = self.output_devices.get(self.output_var.get())
        self.output_device_control.set_device(output_device)
        self.start_failed = False
        self.active_transport = transport
        self.transport_device_name = None
        self.latest_rtt_ms = None
        self._update_latency_display()
        self.status_var.set("Setting up USB…" if transport == "usb" else "Starting Wi-Fi receiver…")
        self.client_var.set("Waiting for phone")
        self.wifi_button.configure(state="disabled")
        self.usb_button.configure(state="disabled")
        self.port_entry.configure(state="disabled")
        self.output_combo.configure(state="readonly")
        if transport == "usb":
            self.usb_status_var.set("Setting up USB forwarding…")
            self._log(f"Setting up USB forwarding for port {port}…")
        else:
            self.wifi_status_var.set("Starting Wi-Fi receiver…")
            self._log(f"Starting Wi-Fi receiver on port {port}…")
        self.worker = threading.Thread(
            target=self._server_worker,
            args=(port, output_device, transport),
            name="PhoneToPcReceiver",
            daemon=True,
        )
        self.worker.start()

    @staticmethod
    def _find_adb():
        candidates = [shutil.which("adb")]
        for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            sdk_path = os.environ.get(variable)
            if sdk_path:
                candidates.append(str(Path(sdk_path) / "platform-tools" / "adb.exe"))
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(str(Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / "adb.exe"))
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        raise FileNotFoundError(
            "Android Debug Bridge (adb) was not found. Install Android SDK Platform-Tools "
            "or add its platform-tools folder to PATH."
        )

    def _server_worker(self, port, output_device, transport):
        try:
            if transport == "usb":
                self.adb_path = self._find_adb()
                command = [self.adb_path, "reverse", f"tcp:{port}", f"tcp:{port}"]
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                if result.returncode != 0:
                    details = result.stderr.strip() or result.stdout.strip() or "adb reverse failed."
                    raise RuntimeError(details)
                devices_result = subprocess.run(
                    [self.adb_path, "devices", "-l"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                for line in devices_result.stdout.splitlines():
                    fields = line.split()
                    if len(fields) >= 3 and fields[1] == "device":
                        model = next((field.split(":", 1)[1] for field in fields[2:] if field.startswith("model:")), "")
                        if model:
                            self.events.put(("device_name", model.replace("_", " ")))
                        break
                self.events.put(("usb_ready", self.adb_path))

            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._serve(port, output_device, transport))
        except Exception as error:
            self.events.put(("server_error", str(error)))
            self.events.put(("stopped", None))
        finally:
            if self.loop is not None:
                self.loop.close()
                self.loop = None

    async def _serve(self, port, output_device, transport):
        def on_event(name, value):
            if name == "websocket":
                with self.connection_lock:
                    self.active_websocket = value
                return
            if name == "video_frame":
                with self.video_frame_lock:
                    self.pending_video_frame = value
                return
            if name == "disconnected":
                with self.video_frame_lock:
                    self.pending_video_frame = None
                with self.connection_lock:
                    self.active_websocket = None
            self.events.put((name, value))

        handler = lambda websocket: receive_audio(
            websocket,
            output_device=output_device,
            output_device_control=self.output_device_control,
            volume_control=self.volume_control,
            buffer_control=self.wifi_buffer_control if transport == "wifi" else self.usb_buffer_control,
            low_latency=transport == "usb",
            on_event=on_event,
        )
        try:
            self.server = await serve(
                handler,
                "0.0.0.0",
                port,
                # JPEG screen frames are much larger than 10 ms PCM packets.
                max_size=4 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=2,
            )
            self.stop_event = asyncio.Event()
            self.events.put(("started", port))
            await self.stop_event.wait()
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), timeout=4)
            except asyncio.TimeoutError:
                # A handler may be blocked while draining audio during shutdown.
                # Cancel it after the graceful WebSocket close window expires.
                handlers = tuple(self.server.handlers.values())
                for task in handlers:
                    task.cancel()
                if handlers:
                    await asyncio.gather(*handlers, return_exceptions=True)
                await asyncio.wait_for(self.server.wait_closed(), timeout=2)
        except Exception as error:
            self.events.put(("server_error", str(error)))
        finally:
            self.server = None
            self.stop_event = None
            self.events.put(("stopped", None))

    def _stop(self):
        if self.status_var.get() == "Stopping…":
            return
        self.status_var.set("Stopping…")
        self.latest_rtt_ms = None
        self._update_latency_display()
        self.wifi_button.configure(state="disabled")
        self.usb_button.configure(state="disabled")
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
            if name == "usb_ready":
                self.usb_status_var.set("USB forwarding is ready")
                self._log("USB forwarding configured. Use 127.0.0.1 in the phone app.")
            elif name == "started":
                transport_name = "USB" if self.active_transport == "usb" else "Wi-Fi"
                self.status_var.set(f"Listening for {transport_name} on port {value}")
                active_button = self.usb_button if self.active_transport == "usb" else self.wifi_button
                other_button = self.wifi_button if self.active_transport == "usb" else self.usb_button
                active_button.configure(text=f"Stop {transport_name} receiver", state="normal", command=self._stop)
                other_button.configure(state="disabled")
                self._log(f"Receiver ready at ws://0.0.0.0:{value}/audio")
                if self.closing:
                    self._stop()
            elif name == "connected":
                self.client = value
                self.client_device_name = self.transport_device_name if self.active_transport == "usb" else None
                self._update_client_display()
                self.status_var.set("Phone connected")
                self.latest_rtt_ms = None
                self._update_latency_display()
                self._log(f"Phone connected: {value}")
                if self.phone_mute_var.get():
                    self._send_phone_mute(True)
            elif name == "device_name":
                self.client_device_name = value
                self.transport_device_name = value
                self._update_client_display()
                self._log(f"Connected device: {value}")
            elif name == "disconnected":
                self._restore_phone_display()
                self.video_stream_active = False
                self.display_power_check.configure(state="disabled")
                self.fullscreen_video_button.configure(state="disabled")
                self.latest_video_jpeg = None
                self._close_video_fullscreen()
                self.video_photo = None
                self.video_label.configure(image="")
                self.video_label.pack_forget()
                self.video_placeholder.pack(fill="x", expand=True)
                self.client = None
                self.client_device_name = None
                self._update_client_display()
                self.latest_rtt_ms = None
                self._update_latency_display()
                if self.server is not None:
                    transport_name = "USB" if self.active_transport == "usb" else "Wi-Fi"
                    self.status_var.set(f"Listening for {transport_name} phone")
                self._log(f"Phone disconnected: {value}")
            elif name == "latency":
                self.latest_rtt_ms = value
                self._update_latency_display()
            elif name == "hotkey":
                self._apply_volume_shortcut(value)
            elif name == "hotkeys_ready":
                self._log(f"Global volume shortcuts active: {value}/3.")
            elif name == "hotkey_error":
                self._log(str(value))
            elif name == "warning":
                self._log(str(value))
            elif name == "control_error":
                self._log(str(value))
            elif name == "update_check_result":
                self.update_button.configure(state="normal", text="Check for updates")
                status, version, release_url, error = value
                if status == "available":
                    if messagebox.askyesno(
                        "Update available",
                        f"PhoneToPC {version} is available. Open the GitHub release page?",
                        parent=self.root,
                    ):
                        webbrowser.open(release_url)
                elif status == "current":
                    messagebox.showinfo(
                        "No updates available",
                        f"You are using the latest version of PhoneToPC ({APP_VERSION}).",
                        parent=self.root,
                    )
                else:
                    messagebox.showerror(
                        "Update check failed",
                        f"Could not check GitHub for updates.\n\n{error}",
                        parent=self.root,
                    )
            elif name == "phone_mute_result":
                if value == "muted":
                    self._log("Phone media volume muted.")
                elif value == "unmuted":
                    self._log("Phone media volume restored.")
                else:
                    self._log("Phone could not change its media volume.")
            elif name == "display_power_result":
                desired, error = value
                if error:
                    self.display_power_var.set(self.phone_display_off)
                    self.display_power_desired = self.phone_display_off
                    self._log(f"Could not change phone display power: {error}")
                    messagebox.showerror("Phone display", error, parent=self.root)
                else:
                    self.phone_display_off = desired
                    self._log(
                        "Phone display turned off; mirroring continues and mouse input uses USB debugging."
                        if desired else "Phone display turned on."
                    )
                self.display_power_check.configure(
                    state="normal" if self.video_stream_active else "disabled"
                )
            elif name == "output_changed":
                self._log("Audio output switched.")
            elif name == "output_switch_error":
                self._log(f"Could not switch audio output: {value}")
            elif name == "error":
                self._log(f"Audio output error: {value}")
                self.status_var.set("Audio output error")
            elif name == "server_error":
                self.start_failed = True
                self._log(f"Could not start receiver: {value}")
                self.status_var.set("Could not start receiver")
                if self.active_transport == "usb":
                    self.usb_status_var.set("USB setup failed")
                elif self.active_transport == "wifi":
                    self.wifi_status_var.set("Could not start")
                messagebox.showerror("Receiver error", str(value), parent=self.root)
            elif name == "stopped":
                self._restore_phone_display()
                self.video_stream_active = False
                self.display_power_check.configure(state="disabled")
                self.client = None
                self.client_device_name = None
                self.transport_device_name = None
                self._update_client_display()
                self.status_var.set("Stopped")
                if self.active_transport == "usb" and not self.start_failed:
                    self.usb_status_var.set("Stopped")
                elif self.active_transport == "wifi" and not self.start_failed:
                    self.wifi_status_var.set("Stopped")
                self.active_transport = None
                self.latest_rtt_ms = None
                self._update_latency_display()
                self.wifi_button.configure(text="Start Wi-Fi receiver", state="normal", command=lambda: self._start("wifi"))
                self.usb_button.configure(text="Start USB receiver", state="normal", command=lambda: self._start("usb"))
                self.port_entry.configure(state="normal")
                self.output_combo.configure(state="readonly")
                self._log("Receiver stopped.")
                if self.closing:
                    self.root.destroy()
        self.root.after(100, self._process_events)

    def _process_pending_video_frame(self):
        with self.video_frame_lock:
            latest_video_frame = self.pending_video_frame
            self.pending_video_frame = None
        if latest_video_frame is not None:
            self._show_video_frame(latest_video_frame)
        if not self.closing:
            self.root.after(16, self._process_pending_video_frame)

    def _update_client_display(self):
        if self.client is None:
            self.client_var.set("Waiting for phone")
            return
        address = f"{self.client[0]}:{self.client[1]}"
        if self.client_device_name:
            self.client_var.set(f"{self.client_device_name} ({address})")
        else:
            self.client_var.set(address)

    def _show_video_frame(self, jpeg):
        try:
            from PIL import Image, ImageTk

            with Image.open(BytesIO(jpeg)) as image:
                self.video_source_size = image.size
                self.latest_video_jpeg = jpeg
                main_preview = image.copy()
                main_preview.thumbnail((520, 300), Image.Resampling.LANCZOS)
                fullscreen_preview = image.copy()
            self.video_photo = ImageTk.PhotoImage(main_preview, master=self.video_label)
            self.video_placeholder.pack_forget()
            self.video_label.configure(image=self.video_photo)
            if not self.video_label.winfo_manager():
                self.video_label.pack(fill="both", expand=True)
            if self.fullscreen_video_label is not None:
                width = max(1, self.fullscreen_video_label.winfo_width() - 16)
                height = max(1, self.fullscreen_video_label.winfo_height() - 16)
                if width <= 1 or height <= 1:
                    width = self.root.winfo_screenwidth() - 16
                    height = self.root.winfo_screenheight() - 64
                scale = min(
                    width / fullscreen_preview.width,
                    height / fullscreen_preview.height,
                )
                target_size = (
                    max(1, round(fullscreen_preview.width * scale)),
                    max(1, round(fullscreen_preview.height * scale)),
                )
                fullscreen_preview = fullscreen_preview.resize(
                    target_size, Image.Resampling.LANCZOS
                )
                self.fullscreen_video_photo = ImageTk.PhotoImage(
                    fullscreen_preview, master=self.fullscreen_video_label
                )
                self.fullscreen_video_label.configure(image=self.fullscreen_video_photo)
            self.fullscreen_video_button.configure(state="normal")
            self.video_stream_active = True
            if not self.display_power_desired:
                self.display_power_check.configure(state="normal")
        except Exception as error:
            self._log(f"Could not display phone screen: {error}")

    def _open_video_fullscreen(self, _event=None):
        if self.capture_action is not None:
            return None
        if not self.video_stream_active:
            return "break"
        if self.fullscreen_video_window is not None:
            try:
                self.fullscreen_video_window.focus_force()
                return "break"
            except tk.TclError:
                self.fullscreen_video_window = None
        window = tk.Toplevel(self.root)
        window.title("Phone screen")
        window.configure(background=self.colors["window"])
        window.attributes("-fullscreen", True)
        self.fullscreen_video_window = window
        self.fullscreen_video_photo = None
        label = tk.Label(window, anchor="center", background=self.colors["window"])
        label.pack(fill="both", expand=True)
        self.fullscreen_video_label = label
        label.bind("<ButtonPress-1>", self._on_video_mouse_press)
        label.bind("<B1-Motion>", self._on_video_mouse_motion)
        label.bind("<ButtonRelease-1>", self._on_video_mouse_release)
        window.bind("<Escape>", self._close_video_fullscreen)
        window.bind("<KeyPress-f>", self._close_video_fullscreen)
        window.bind("<KeyPress-F>", self._close_video_fullscreen)
        window.protocol("WM_DELETE_WINDOW", self._close_video_fullscreen)
        window.update_idletasks()
        if self.latest_video_jpeg is not None:
            self._show_video_frame(self.latest_video_jpeg)
        window.focus_force()
        return "break"

    def _close_video_fullscreen(self, _event=None):
        window = self.fullscreen_video_window
        self.fullscreen_video_window = None
        self.fullscreen_video_label = None
        self.fullscreen_video_photo = None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass
        return "break"

    def _video_mouse_point(self, event):
        photo = (
            self.fullscreen_video_photo
            if event.widget is self.fullscreen_video_label
            else self.video_photo
        )
        if photo is None:
            return None
        image_width = photo.width()
        image_height = photo.height()
        label_width = event.widget.winfo_width()
        label_height = event.widget.winfo_height()
        left = (label_width - image_width) / 2
        top = (label_height - image_height) / 2
        x = (event.x - left) / max(1, image_width)
        y = (event.y - top) / max(1, image_height)
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            return None
        return float(x), float(y)

    def _on_video_mouse_press(self, event):
        if not self.remote_control_var.get():
            return
        point = self._video_mouse_point(event)
        if point is None:
            return
        self.video_gesture_points = [point]
        self.video_gesture_started_at = time.monotonic()

    def _on_video_mouse_motion(self, event):
        if not self.remote_control_var.get() or not self.video_gesture_points:
            return
        point = self._video_mouse_point(event)
        if point is None or len(self.video_gesture_points) >= 64:
            return
        previous = self.video_gesture_points[-1]
        if abs(point[0] - previous[0]) + abs(point[1] - previous[1]) >= 0.004:
            self.video_gesture_points.append(point)

    def _on_video_mouse_release(self, event):
        points = self.video_gesture_points
        self.video_gesture_points = None
        if not self.remote_control_var.get() or not points:
            return
        point = self._video_mouse_point(event)
        if point is not None and len(points) < 64:
            points.append(point)
        elapsed_ms = round((time.monotonic() - self.video_gesture_started_at) * 1000)
        if len(points) == 1:
            points.append(points[0])
        self._send_remote_gesture(points, max(100, elapsed_ms))

    def _on_remote_control_toggle(self):
        if self.remote_control_var.get():
            self._log("Mouse control is enabled for this connection. Click or drag on the Video stream image.")
        else:
            self.video_gesture_points = None
            self._log("Mouse control is disabled.")

    def _check_for_updates(self):
        self.update_button.configure(state="disabled", text="Checking…")
        threading.Thread(
            target=self._check_for_updates_worker,
            name="PhoneToPCUpdateCheck",
            daemon=True,
        ).start()

    def _check_for_updates_worker(self):
        try:
            request = urllib.request.Request(
                LATEST_RELEASE_API,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"PhoneToPC/{APP_VERSION}",
                },
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                release = json.loads(response.read().decode("utf-8"))
            latest_version = release.get("tag_name", "").strip()
            release_url = release.get("html_url", "https://github.com/shihab1712/PhoneToPC/releases/latest")
            if not latest_version or not _version_tuple(latest_version):
                raise ValueError("The latest GitHub release does not have a valid version tag.")
            status = "available" if _version_tuple(latest_version) > _version_tuple(APP_VERSION) else "current"
            self.events.put(("update_check_result", (status, latest_version, release_url, None)))
        except Exception as error:
            self.events.put(("update_check_result", ("error", None, None, str(error))))

    def _on_phone_mute_toggle(self):
        muted = self.phone_mute_var.get()
        if self.client is None:
            self._log(
                "Phone media will be muted when a phone connects."
                if muted else "Phone media mute is off."
            )
            return
        self._send_phone_mute(muted)

    def _send_phone_mute(self, muted):
        with self.connection_lock:
            websocket = self.active_websocket
        loop = self.loop
        if websocket is None or loop is None or not loop.is_running():
            self._log("Phone media mute will apply when a phone connects.")
            return
        command = f"PHONE_MUTE:{1 if muted else 0}"
        future = asyncio.run_coroutine_threadsafe(websocket.send(command), loop)

        def report_error(result):
            try:
                result.result()
            except Exception as error:
                self.events.put(("control_error", f"Could not change phone media volume: {error}"))

        future.add_done_callback(report_error)
        self._log("Mute requested on phone." if muted else "Phone media restore requested.")

    def _on_display_power_toggle(self):
        self._set_phone_display_power(self.display_power_var.get())

    def _set_phone_display_power(self, turn_off):
        desired = bool(turn_off)
        self.display_power_desired = desired
        self.display_power_check.configure(state="disabled")
        threading.Thread(
            target=self._display_power_worker,
            args=(desired,),
            name="PhoneDisplayPower",
            daemon=True,
        ).start()

    def _display_power_worker(self, turn_off):
        error_text = None
        try:
            with self.display_power_lock:
                adb = self._find_adb()
                devices = subprocess.run(
                    [adb, "devices"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                serials = [
                    fields[0]
                    for line in devices.stdout.splitlines()
                    if len(fields := line.split()) >= 2 and fields[1] == "device"
                ]
                if len(serials) != 1:
                    raise RuntimeError(
                        "Connect exactly one Android phone over USB, unlock it, and approve USB debugging."
                    )
                serial = serials[0]
                size_result = subprocess.run(
                    [adb, "-s", serial, "shell", "wm", "size"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                screen_size = None
                for line in size_result.stdout.splitlines():
                    size_text = line.rsplit(":", 1)[-1].strip()
                    if "x" in size_text:
                        try:
                            width_text, height_text = size_text.split("x", 1)
                            screen_size = (int(width_text), int(height_text))
                        except ValueError:
                            continue
                if size_result.returncode != 0 or screen_size is None:
                    raise RuntimeError("Could not read the phone screen dimensions for mouse control.")
                sdk = subprocess.run(
                    [adb, "-s", serial, "shell", "getprop", "ro.build.version.sdk"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                if sdk.returncode != 0 or int(sdk.stdout.strip() or "0") < 35:
                    raise RuntimeError("Turning the display off while mirroring requires Android 15 or newer.")
                command = "power-off" if turn_off else "power-reset"
                result = subprocess.run(
                    [adb, "-s", serial, "shell", "cmd", "display", command, "0"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                if result.returncode != 0:
                    details = result.stderr.strip() or result.stdout.strip()
                    raise RuntimeError(details or f"Android display command failed: {command}")
                self.display_power_serial = serial
                self.phone_screen_size = screen_size
        except Exception as error:
            error_text = str(error)
        self.events.put(("display_power_result", (turn_off, error_text)))

    def _restore_phone_display(self):
        if not self.phone_display_off and not self.display_power_desired:
            return
        self.display_power_var.set(False)
        self._set_phone_display_power(False)

    def _send_remote_gesture(self, points, duration_ms):
        if not self.remote_control_var.get():
            return
        if self.phone_display_off:
            self._send_adb_gesture(points, duration_ms)
            return
        with self.connection_lock:
            websocket = self.active_websocket
        loop = self.loop
        if websocket is None or loop is None or not loop.is_running():
            self._log("Connect the phone and start screen sharing before using mouse control.")
            return
        command = "CONTROL:" + json.dumps(
            {"type": "gesture", "points": points, "durationMs": duration_ms},
            separators=(",", ":"),
        )
        future = asyncio.run_coroutine_threadsafe(websocket.send(command), loop)

        def report_error(result):
            try:
                result.result()
            except Exception as error:
                self.events.put(("control_error", f"Could not send mouse gesture: {error}"))

        future.add_done_callback(report_error)

    def _send_adb_gesture(self, points, duration_ms):
        serial = self.display_power_serial
        screen_size = self.phone_screen_size
        frame_size = self.video_source_size
        if not serial or not screen_size or not frame_size:
            self._log("Mouse control while the phone display is off needs an authorized USB debugging connection.")
            return
        screen_width, screen_height = screen_size
        frame_width, frame_height = frame_size
        if (frame_width > frame_height) != (screen_width > screen_height):
            screen_width, screen_height = screen_height, screen_width
        coords = [
            (
                max(0, min(screen_width - 1, round(x * (screen_width - 1)))),
                max(0, min(screen_height - 1, round(y * (screen_height - 1)))),
            )
            for x, y in points
        ]
        first, last = coords[0], coords[-1]
        adb = self.adb_path
        if not adb:
            try:
                adb = self._find_adb()
            except Exception as error:
                self._log(f"Mouse control while display is off failed: {error}")
                return
        if len(coords) < 2 or first == last:
            command = [
                adb, "-s", serial, "shell", "input", "-d", "0", "tap",
                str(first[0]), str(first[1]),
            ]
        else:
            command = [
                adb, "-s", serial, "shell", "input", "-d", "0", "swipe",
                str(first[0]), str(first[1]), str(last[0]), str(last[1]),
                str(max(50, min(2000, duration_ms))),
            ]
        threading.Thread(
            target=self._run_adb_gesture,
            args=(command,),
            name="PhoneMouseGesture",
            daemon=True,
        ).start()

    def _run_adb_gesture(self, command):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            details = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part)
            if result.returncode != 0 or "error" in details.lower() or "exception" in details.lower():
                details = details or "ADB input command failed."
                self.events.put(("control_error", f"Phone mouse input failed: {details}"))
        except Exception as error:
            self.events.put(("control_error", f"Phone mouse input failed: {error}"))

    def _log(self, message):
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self):
        self._restore_phone_display()
        self._stop_hotkey_listener()
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
