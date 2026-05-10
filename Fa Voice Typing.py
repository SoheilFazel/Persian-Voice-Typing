import tkinter as tk
import keyboard
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

class UltimateHybridApp:
    def __init__(self, root):
        self.root = root
        self.root.title("دستیار صوتی هوشمند")
        self.root.geometry("280x400+50+50")
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#202124")

        self.is_recording = False
        self.model_loaded = False

        # تغییر عملکرد دکمه ضربدر (X) برای رفتن به System Tray
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)

        # --- UI پنجره اصلی ---
        self.toggle_btn = tk.Button(self.root, text="⏳ در حال بارگذاری مدل...", font=(FONT_NAME, 12, "bold"), 
                                    bg="#f57c00", fg="white", borderwidth=0, cursor="hand2", command=self.toggle_recording)
        self.toggle_btn.pack(fill="x", pady=(15, 10), padx=15, ipady=8)

        header_frame = tk.Frame(self.root, bg="#202124")
        header_frame.pack(fill="x", padx=15, pady=(5, 0))
        
        tk.Label(header_frame, text="تاریخچه صحبت‌های شما:", font=(FONT_NAME, 10), bg="#202124", fg="#e8eaed").pack(side="left")
        
        self.clear_btn = tk.Button(header_frame, text="🗑️ پاک کردن", font=(FONT_NAME, 9), bg="#5f6368", fg="white", borderwidth=0, cursor="hand2", command=self.clear_history)
        self.clear_btn.pack(side="right", ipadx=5, ipady=1)

        self.history_box = tk.Text(self.root, height=12, font=(FONT_NAME, 11), bg="#303134", fg="#e8eaed", relief="flat", wrap="word", insertbackground="white", padx=10, pady=10)
        self.history_box.pack(padx=15, pady=10, fill="both", expand=True)

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

        threading.Thread(target=self.load_model, daemon=True).start()
        
        # اجرای System Tray در یک ترد مجزا
        threading.Thread(target=self.setup_tray, daemon=True).start()

    def hide_window(self):
        """مخفی کردن پنجره اصلی به جای بستن آن"""
        self.root.withdraw()

    def show_window(self, icon, item):
        """نمایش مجدد پنجره اصلی از طریق System Tray"""
        self.root.after(0, self.root.deiconify)

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
        self.history_box.delete("1.0", tk.END)

    def draw_rounded_rect(self, canvas, x1, y1, x2, y2, radius=25, **kwargs):
        points = [x1+radius, y1, x1+radius, y1, x2-radius, y1, x2-radius, y1,
                  x2, y1, x2, y1+radius, x2, y1+radius, x2, y2-radius, x2, y2-radius,
                  x2, y2, x2-radius, y2, x2-radius, y2, x1+radius, y2, x1+radius, y2,
                  x1, y2, x1, y2-radius, x1, y2-radius, x1, y1+radius, x1, y1+radius, x1, y1]
        return canvas.create_polygon(points, **kwargs, smooth=True)

    def load_model(self):
        try:
            model_path = resource_path("model")
            self.model = Model(model_path)
            self.model_loaded = True
            self.root.after(0, lambda: self.toggle_btn.config(text="🎙️ میکروفون خاموش (F9)", bg="#d32f2f"))
            keyboard.add_hotkey('f9', self.toggle_recording)
        except Exception:
            self.root.after(0, lambda: self.toggle_btn.config(text="❌ خطا: مدل پیدا نشد!", bg="black"))

    def toggle_recording(self):
        if not self.model_loaded: return
        if not self.is_recording:
            self.is_recording = True
            self.toggle_btn.config(text="🔴 در حال شنیدن... (F9)", bg="#388e3c")
            threading.Thread(target=self.process_hybrid_voice, daemon=True).start()
        else:
            self.is_recording = False
            self.toggle_btn.config(text="🎙️ میکروفون خاموش (F9)", bg="#d32f2f")
            self.glass.withdraw()

    def update_ui(self, text, is_final=False, is_processing=False):
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
            self.history_box.insert(tk.END, final_text + "\n\n")
            self.history_box.see(tk.END)
            if self.root.focus_get() is None:
                time.sleep(0.05)
                keyboard.write(final_text + " ")
            threading.Thread(target=self.hide_glass_after_delay, daemon=True).start()

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