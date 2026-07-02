import tkinter as tk
from tkinter import messagebox
import keyboard
import mouse
import pyperclip
import threading
import time
import json
import queue
import sys
import os
import ctypes
import winreg as reg
import sounddevice as sd
import speech_recognition as sr
from vosk import Model, KaldiRecognizer
import pystray
from PIL import Image, ImageDraw

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# تلاش برای لود کردن فونت کلمه
try:
    font_path = resource_path("Kalameh-Bold.ttf")
    if os.path.exists(font_path):
        ctypes.windll.gdi32.AddFontResourceW(font_path)
    FONT_NAME = "Kalameh"
except:
    FONT_NAME = "Tahoma"

q = queue.Queue()

def audio_callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

# تابع برای اضافه کردن برنامه به استارت‌آپ ویندوز
def add_to_startup():
    try:
        # پیدا کردن مسیر فایل اجرایی (چه پایتون باشد چه exe)
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.abspath(__file__)
            
        key = reg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        open_key = reg.OpenKey(key, key_path, 0, reg.KEY_ALL_ACCESS)
        reg.SetValueEx(open_key, "PersianVoiceAssistant", 0, reg.REG_SZ, exe_path)
        reg.CloseKey(open_key)
    except Exception as e:
        print("خطا در اضافه کردن به استارت‌آپ:", e)

DEFAULT_CONFIG = {
    "key_push": "f9",     # نگه‌دارید و صحبت کنید (Push to Talk)
    "key_toggle": "f10",  # با یک ضربه روشن/خاموش شود
}

MOUSE_BUTTON_NAMES = {
    "left": "کلیک چپ موس",
    "right": "کلیک راست موس",
    "middle": "کلیک وسط موس",
    "x": "دکمه جانبی ۱ موس",
    "x2": "دکمه جانبی ۲ موس",
}

def format_key_name(key):
    if not key:
        return "-"
    if key.startswith("mouse:"):
        button = key.split(":", 1)[1]
        return MOUSE_BUTTON_NAMES.get(button, f"موس: {button}")
    return key.upper()

def get_config_path():
    appdata = os.getenv('APPDATA') or os.path.expanduser('~')
    config_dir = os.path.join(appdata, 'PersianVoiceAssistant')
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, 'config.json')

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    try:
        path = get_config_path()
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                cfg.update(json.load(f))
    except Exception as e:
        print("خطا در خواندن تنظیمات:", e)
    return cfg

def save_config(cfg):
    try:
        with open(get_config_path(), 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("خطا در ذخیره تنظیمات:", e)

class UltimateHybridApp:
    def __init__(self, root):
        self.root = root
        self.root.title("دستیار صوتی هوشمند")
        self.root.geometry("280x400+50+50")
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#202124")

        self.is_recording = False
        self.model_loaded = False
        self.config = load_config()

        # تغییر عملکرد دکمه ضربدر (X) برای رفتن به System Tray
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        # وقتی پنجره کوچک (minimize) می‌شود، به‌جای حالت پیش‌فرض ویندوز، حباب شناور نشان داده شود
        self.root.bind("<Unmap>", self.on_root_unmap)

        # --- UI پنجره اصلی ---
        self.toggle_btn = tk.Button(self.root, text="⏳ در حال بارگذاری مدل...", font=(FONT_NAME, 12, "bold"),
                                    bg="#f57c00", fg="white", borderwidth=0, cursor="hand2", command=self.toggle_recording)
        self.toggle_btn.pack(fill="x", pady=(15, 10), padx=15, ipady=8)

        self.settings_btn = tk.Button(self.root, text="⚙️ تنظیمات کلید میانبر", font=(FONT_NAME, 9), bg="#3c4043", fg="white",
                                       borderwidth=0, cursor="hand2", command=self.open_settings)
        self.settings_btn.pack(fill="x", padx=15, pady=(0, 10), ipady=4)

        header_frame = tk.Frame(self.root, bg="#202124")
        header_frame.pack(fill="x", padx=15, pady=(5, 0))
        
        tk.Label(header_frame, text="تاریخچه صحبت‌های شما:", font=(FONT_NAME, 10), bg="#202124", fg="#e8eaed").pack(side="left")
        
        self.clear_btn = tk.Button(header_frame, text="🗑️ پاک کردن", font=(FONT_NAME, 9), bg="#5f6368", fg="white", borderwidth=0, cursor="hand2", command=self.clear_history)
        self.clear_btn.pack(side="right", ipadx=5, ipady=1)

        self.history_box = tk.Text(self.root, height=12, font=(FONT_NAME, 11), bg="#303134", fg="#e8eaed", relief="flat", wrap="word", insertbackground="white", padx=10, pady=10)
        self.history_box.pack(padx=15, pady=10, fill="both", expand=True)
        self.history_box.config(state="disabled")

        # --- پنجره شیشه‌ای ---
        self.glass = tk.Toplevel(self.root)
        self.glass.overrideredirect(True)
        
        screen_width = self.root.winfo_screenwidth()
        box_width = 500
        x_position = (screen_width - box_width) // 2
        self.glass.geometry(f"{box_width}x100+{x_position}+80") 
        self.glass.attributes('-topmost', True)
        self.glass.attributes('-alpha', 0.85)
        
        self.transparent_color = "magenta"
        self.glass.attributes("-transparentcolor", self.transparent_color)
        self.glass.configure(bg=self.transparent_color)
        self.glass.withdraw()

        self.canvas = tk.Canvas(self.glass, width=box_width, height=100, bg=self.transparent_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        self.draw_rounded_rect(self.canvas, 5, 5, box_width-5, 95, radius=20, fill="#1c1c1c")

        self.live_label = tk.Label(self.glass, text="", font=(FONT_NAME, 16), fg="#00bfff", bg="#1c1c1c", wraplength=460)
        self.live_label.place(relx=0.5, rely=0.5, anchor="center")

        # --- حباب شناور (حالت minimize) ---
        self.setup_bubble()

        threading.Thread(target=self.load_model, daemon=True).start()
        
        # اجرای System Tray در یک ترد مجزا
        threading.Thread(target=self.setup_tray, daemon=True).start()

    def hide_window(self):
        """مخفی کردن پنجره اصلی به جای بستن آن"""
        self.bubble.withdraw()
        self.root.withdraw()

    def show_window(self, icon, item):
        """نمایش مجدد پنجره اصلی از طریق System Tray"""
        self.root.after(0, self.restore_from_bubble)

    def setup_bubble(self):
        """حباب گرد شناور که هنگام minimize کردن پنجره اصلی به‌جای آن نمایش داده می‌شود"""
        size = 56
        self.bubble = tk.Toplevel(self.root)
        self.bubble.overrideredirect(True)
        self.bubble.attributes('-topmost', True)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        bubble_x, bubble_y = screen_w - size - 30, screen_h - size - 90
        self.bubble.geometry(f"{size}x{size}+{bubble_x}+{bubble_y}")

        bubble_transparent = "magenta"
        self.bubble.configure(bg=bubble_transparent)
        self.bubble.attributes('-transparentcolor', bubble_transparent)
        self.bubble.withdraw()

        canvas = tk.Canvas(self.bubble, width=size, height=size, bg=bubble_transparent, highlightthickness=0)
        canvas.pack()
        self.bubble_canvas = canvas

        self.bubble_ring = canvas.create_oval(2, 2, size - 2, size - 2, fill="#202124", outline="#00bfff", width=2)
        canvas.create_text(size / 2, size / 2, text="🎙️", font=(FONT_NAME, 18))

        close_r = 9
        cx, cy = size - close_r - 1, close_r + 1
        canvas.create_oval(cx - close_r, cy - close_r, cx + close_r, cy + close_r, fill="#d32f2f", outline="#202124")
        canvas.create_text(cx, cy, text="✕", font=(FONT_NAME, 8, "bold"), fill="white")

        drag_state = {"x": 0, "y": 0, "moved": False}

        def on_press(event):
            drag_state["x"], drag_state["y"] = event.x, event.y
            drag_state["moved"] = False

        def on_motion(event):
            dx, dy = event.x - drag_state["x"], event.y - drag_state["y"]
            if abs(dx) > 3 or abs(dy) > 3:
                drag_state["moved"] = True
            x = self.bubble.winfo_x() + dx
            y = self.bubble.winfo_y() + dy
            self.bubble.geometry(f"+{x}+{y}")

        def on_release(event):
            if drag_state["moved"]:
                return
            dx, dy = event.x - cx, event.y - cy
            if dx * dx + dy * dy <= close_r * close_r:
                self.hide_window()
            else:
                self.restore_from_bubble()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_motion)
        canvas.bind("<ButtonRelease-1>", on_release)

    def on_root_unmap(self, event):
        """رهگیری minimize شدن پنجره اصلی برای نمایش حباب شناور به‌جای آن"""
        if event.widget is self.root and self.root.state() == 'iconic':
            self.root.after(10, self.show_bubble)

    def show_bubble(self):
        self.root.withdraw()
        self.bubble.deiconify()

    def restore_from_bubble(self):
        self.bubble.withdraw()
        self.root.deiconify()
        self.root.state('normal')

    def quit_app(self, icon, item):
        """بستن کامل برنامه"""
        icon.stop()
        self.root.quit()
        sys.exit()

    def setup_tray(self):
        """تنظیمات آیکون کنار ساعت"""
        # اگر فایل microphone.ico بود آن را می‌خواند، وگرنه یک آیکون ساده می‌سازد
        try:
            icon_path = resource_path("microphone1.ico")
            image = Image.open(icon_path)
        except:
            image = Image.new('RGB', (64, 64), color = (40, 40, 40))
            d = ImageDraw.Draw(image)
            d.ellipse((16, 16, 48, 48), fill=(0, 200, 0))

        menu = pystray.Menu(
            pystray.MenuItem('نمایش تاریخچه', self.show_window),
            pystray.MenuItem('خروج کامل', self.quit_app)
        )
        self.tray_icon = pystray.Icon("VoiceAssistant", image, "دستیار صوتی", menu)
        self.tray_icon.run()

    def clear_history(self):
        self.history_box.config(state="normal")
        self.history_box.delete("1.0", tk.END)
        self.history_box.config(state="disabled")

    def draw_rounded_rect(self, canvas, x1, y1, x2, y2, radius=25, **kwargs):
        points = [x1+radius, y1, x1+radius, y1, x2-radius, y1, x2-radius, y1,
                  x2, y1, x2, y1+radius, x2, y1+radius, x2, y2-radius, x2, y2-radius,
                  x2, y2, x2-radius, y2, x2-radius, y2, x1+radius, y2, x1+radius, y2,
                  x1, y2, x1, y2-radius, x1, y2-radius, x1, y1+radius, x1, y1+radius, x1, y1]
        return canvas.create_polygon(points, **kwargs, smooth=True)

    def make_pill_button(self, parent, text, bg, hover_bg, fg, command, width, height=40):
        """دکمه بیضی‌شکل با افکت hover، هماهنگ با ظاهر کارت‌های شیشه‌ای برنامه"""
        canvas = tk.Canvas(parent, width=width, height=height, bg=parent["bg"], highlightthickness=0, cursor="hand2")
        rect = self.draw_rounded_rect(canvas, 1, 1, width - 1, height - 1, radius=height // 2, fill=bg, outline="")
        canvas.create_text(width / 2, height / 2, text=text, font=(FONT_NAME, 10, "bold"), fill=fg)

        canvas.bind("<Enter>", lambda e: canvas.itemconfig(rect, fill=hover_bg))
        canvas.bind("<Leave>", lambda e: canvas.itemconfig(rect, fill=bg))
        canvas.bind("<Button-1>", lambda e: command())
        return canvas

    def load_model(self):
        try:
            model_path = resource_path("model")
            self.model = Model(model_path)
            self.model_loaded = True
            self.root.after(0, lambda: self.toggle_btn.config(text=f"🎙️ میکروفون خاموش {self.hotkey_hint()}", bg="#d32f2f"))
            self.root.after(0, self.apply_hotkeys)
        except Exception:
            self.root.after(0, lambda: self.toggle_btn.config(text="❌ خطا: مدل پیدا نشد!", bg="black"))

    def hotkey_hint(self):
        push = format_key_name(self.config.get('key_push', 'f9'))
        toggle = format_key_name(self.config.get('key_toggle', 'f10'))
        return f"(نگه‌دارید: {push} | ضربه: {toggle})"

    def unhook_hotkeys(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        try:
            mouse.unhook_all()
        except Exception:
            pass

    def register_key(self, key, on_down=None, on_up=None, toggle=False):
        """ثبت یک کلید صفحه‌کلید یا دکمه موس (از جمله دکمه‌های جانبی) برای رویدادهای فشردن/رهاسازی.
        برای حالت toggle روی صفحه‌کلید از add_hotkey استفاده می‌شود تا با تکرار خودکار کلید هنگام نگه‌داشتن آن، چندبار فعال/غیرفعال نشود."""
        if not key:
            return
        if key.startswith("mouse:"):
            button = key.split(":", 1)[1]
            if on_down:
                mouse.on_button(lambda: self.root.after(0, on_down), buttons=(button,), types=('down',))
            if on_up:
                mouse.on_button(lambda: self.root.after(0, on_up), buttons=(button,), types=('up',))
        elif toggle:
            if on_down:
                keyboard.add_hotkey(key, lambda: self.root.after(0, on_down))
        else:
            if on_down:
                keyboard.on_press_key(key, lambda e: self.root.after(0, on_down))
            if on_up:
                keyboard.on_release_key(key, lambda e: self.root.after(0, on_up))

    def apply_hotkeys(self):
        if not self.model_loaded:
            return
        self.unhook_hotkeys()
        try:
            key_push = self.config.get("key_push", "f9")
            key_toggle = self.config.get("key_toggle", "f10")
            if key_push:
                self.register_key(key_push, on_down=self.start_recording, on_up=self.stop_recording)
            if key_toggle and key_toggle != key_push:
                self.register_key(key_toggle, on_down=self.toggle_recording, toggle=True)
        except Exception as e:
            print("خطا در فعال‌سازی کلید میانبر:", e)

    def toggle_recording(self):
        if not self.model_loaded: return
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if not self.model_loaded or self.is_recording:
            return
        self.is_recording = True
        self.toggle_btn.config(text=f"🔴 در حال شنیدن... {self.hotkey_hint()}", bg="#388e3c")
        self.bubble_canvas.itemconfig(self.bubble_ring, outline="#ff5252")
        threading.Thread(target=self.process_hybrid_voice, daemon=True).start()

    def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self.toggle_btn.config(text=f"🎙️ میکروفون خاموش {self.hotkey_hint()}", bg="#d32f2f")
        self.bubble_canvas.itemconfig(self.bubble_ring, outline="#00bfff")
        self.glass.withdraw()
        with q.mutex:
            q.queue.clear()

    def open_settings(self):
        self.unhook_hotkeys()

        win_w = 340
        win = tk.Toplevel(self.root)
        win.title("تنظیمات کلیدهای میانبر")
        win.configure(bg="#17181a")
        win.geometry(f"{win_w}x420+380+80")
        win.attributes('-topmost', True)
        win.resizable(False, False)

        tk.Label(win, text="⌨️  کلیدهای میانبر میکروفون", font=(FONT_NAME, 13, "bold"), bg="#17181a", fg="#e8eaed").pack(anchor="w", padx=18, pady=(18, 2))
        tk.Label(win, text="هر دو روش هم‌زمان فعال هستند؛ می‌توانید کلید صفحه‌کلید یا دکمه موس (از جمله دکمه‌های جانبی) را برای هرکدام تنظیم کنید.",
                 font=(FONT_NAME, 8), bg="#17181a", fg="#9aa0a6", wraplength=win_w - 36, justify="right").pack(anchor="w", padx=18, pady=(0, 6))

        key_push_var = tk.StringVar(value=self.config.get("key_push", "f9"))
        key_toggle_var = tk.StringVar(value=self.config.get("key_toggle", "f10"))

        def make_card(icon, title, desc, var, accent):
            card_w, card_h = win_w - 36, 118
            canvas = tk.Canvas(win, width=card_w, height=card_h, bg="#17181a", highlightthickness=0)
            canvas.pack(padx=18, pady=8)
            self.draw_rounded_rect(canvas, 1, 1, card_w - 1, card_h - 1, radius=16, fill="#26272b", outline="")

            canvas.create_text(16, 24, anchor="w", text=f"{icon}  {title}", font=(FONT_NAME, 11, "bold"), fill="#e8eaed")
            canvas.create_text(16, 48, anchor="w", text=desc, font=(FONT_NAME, 8), fill="#9aa0a6", width=card_w - 32)

            display_var = tk.StringVar(value=format_key_name(var.get()))
            key_label = tk.Label(canvas, textvariable=display_var, font=(FONT_NAME, 11, "bold"), bg="#26272b", fg=accent)
            canvas.create_window(16, 92, anchor="w", window=key_label)

            change_btn = tk.Button(canvas, text="تغییر", font=(FONT_NAME, 9, "bold"), bg=accent, fg="#17181a",
                                    borderwidth=0, cursor="hand2", activebackground=accent, padx=12, pady=4)
            canvas.create_window(card_w - 16, 92, anchor="e", window=change_btn)

            def capture():
                change_btn.config(text="فشار دهید...", state="disabled")
                result = {"value": None}
                done = threading.Event()

                def on_key_event(e):
                    if e.event_type == 'down' and not done.is_set():
                        result["value"] = e.name
                        done.set()

                def on_mouse_event(e):
                    if isinstance(e, mouse.ButtonEvent) and e.event_type == 'down' and not done.is_set():
                        result["value"] = f"mouse:{e.button}"
                        done.set()

                key_hook = keyboard.hook(on_key_event)
                mouse_hook = mouse.hook(on_mouse_event)

                def worker():
                    done.wait(timeout=10)
                    keyboard.unhook(key_hook)
                    mouse.unhook(mouse_hook)

                    def apply():
                        change_btn.config(text="تغییر", state="normal")
                        if result["value"]:
                            var.set(result["value"])
                            display_var.set(format_key_name(result["value"]))
                    win.after(0, apply)

                threading.Thread(target=worker, daemon=True).start()

            change_btn.config(command=capture)

        make_card("🎙️", "نگه‌دارید و صحبت کنید", "این دکمه را نگه دارید تا میکروفون روشن بماند؛ با رها کردن، خاموش می‌شود.", key_push_var, "#00bfff")
        make_card("🔁", "روشن / خاموش با یک ضربه", "با هر بار فشردن این دکمه، میکروفون روشن یا خاموش می‌شود.", key_toggle_var, "#00e676")

        btn_frame = tk.Frame(win, bg="#17181a")
        btn_frame.pack(fill="x", padx=18, pady=18, side="bottom")

        def on_close(save):
            if save:
                if key_push_var.get() and key_push_var.get() == key_toggle_var.get():
                    messagebox.showwarning("کلید تکراری", "برای دو روش نمی‌توانید یک کلید یکسان انتخاب کنید.", parent=win)
                    return
                self.config.update({
                    "key_push": key_push_var.get(),
                    "key_toggle": key_toggle_var.get(),
                })
                save_config(self.config)
                if not self.is_recording:
                    self.toggle_btn.config(text=f"🎙️ میکروفون خاموش {self.hotkey_hint()}")
            self.apply_hotkeys()
            win.destroy()

        btn_w = (win_w - 36 - 10) // 2
        self.make_pill_button(btn_frame, "✔  ذخیره", "#00c853", "#00e676", "#0b1f12",
                               lambda: on_close(True), width=btn_w).pack(side="left", padx=(0, 10))
        self.make_pill_button(btn_frame, "✕  انصراف", "#3c4043", "#4d5155", "#e8eaed",
                               lambda: on_close(False), width=btn_w).pack(side="right")

        win.protocol('WM_DELETE_WINDOW', lambda: on_close(False))

    def update_ui(self, text, is_final=False, is_processing=False):
        if not is_final and not self.is_recording:
            return
        if text.strip():
            self.glass.deiconify()
            self.live_label.config(text=text)
            if is_processing:
                self.live_label.config(fg="#ffc107")
            elif is_final:
                self.live_label.config(fg="#00e676")
            else:
                self.live_label.config(fg="#00bfff")

    def finalize_text_and_paste(self, final_text):
        if final_text.strip():
            self.update_ui(final_text, is_final=True)
            self.history_box.config(state="normal")
            self.history_box.insert(tk.END, final_text + "\n\n")
            self.history_box.see(tk.END)
            self.history_box.config(state="disabled")
            if self.root.focus_get() is None:
                threading.Thread(target=self.paste_text, args=(final_text + " ",), daemon=True).start()
            threading.Thread(target=self.hide_glass_after_delay, daemon=True).start()

    def paste_text(self, text):
        # جایگذاری از طریق کلیپ‌بورد (Ctrl+V) به‌جای شبیه‌سازی تک‌تک کلیدها،
        # چون keyboard.write برای متن فارسی گاهی به‌جای حروف، کلیدهای دیگر
        # (مثل اسکرول یا فشردن دکمه‌های ناخواسته) شبیه‌سازی می‌کرد.
        try:
            previous_clip = pyperclip.paste()
        except Exception:
            previous_clip = None
        try:
            pyperclip.copy(text)
            time.sleep(0.05)
            keyboard.send('ctrl+v')
            time.sleep(0.1)
        finally:
            if previous_clip is not None:
                try:
                    pyperclip.copy(previous_clip)
                except Exception:
                    pass

    def hide_glass_after_delay(self):
        time.sleep(3.5)
        if self.live_label.cget("fg") == "#00e676": 
            self.glass.withdraw()

    def fetch_google_result(self, audio_bytes, fallback_text):
        r = sr.Recognizer()
        audio_data = sr.AudioData(audio_bytes, 16000, 2)
        try:
            google_text = r.recognize_google(audio_data, language="fa-IR")
            self.root.after(0, self.finalize_text_and_paste, google_text)
        except:
            self.root.after(0, self.finalize_text_and_paste, fallback_text)

    def process_hybrid_voice(self):
        with sd.RawInputStream(samplerate=16000, blocksize=8000, device=None,
                               dtype='int16', channels=1, callback=audio_callback):
            rec = KaldiRecognizer(self.model, 16000)
            audio_buffer = bytearray()
            
            while self.is_recording:
                data = q.get()
                audio_buffer.extend(data)
                
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    vosk_fallback = result.get("text", "")
                    
                    if vosk_fallback.strip():
                        self.root.after(0, self.update_ui, "در حال همگام‌سازی... ⏳", False, True)
                        audio_bytes = bytes(audio_buffer)
                        threading.Thread(target=self.fetch_google_result, args=(audio_bytes, vosk_fallback), daemon=True).start()
                        
                    audio_buffer.clear()
                else:
                    partial_result = json.loads(rec.PartialResult())
                    partial_text = partial_result.get("partial", "")
                    
                    if partial_text.strip():
                        self.root.after(0, self.update_ui, partial_text, False, False)

if __name__ == "__main__":
    # ثبت برنامه در استارت‌آپ ویندوز
    add_to_startup()
    
    root = tk.Tk()
    app = UltimateHybridApp(root)
    root.mainloop()