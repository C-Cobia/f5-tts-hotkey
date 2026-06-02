"""
F5-TTS global hotkey tool.

Ctrl+Alt+X: speak selected text
Ctrl+Alt+C: speak clipboard text
Alt+Q: quit
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import sounddevice as sd
import soundfile as sf

try:
    import keyboard
except Exception:
    keyboard = None

try:
    import pyperclip
except Exception:
    pyperclip = None


_builtin_print = print
_print_lock = threading.Lock()


def print(*args, **kwargs) -> None:  # type: ignore[override]
    text = " ".join(str(arg) for arg in args)
    try:
        _builtin_print(*args, **kwargs)
    except OSError:
        pass
    try:
        log_dir = Path(__file__).resolve().parents[1] / "logs"
        log_dir.mkdir(exist_ok=True)
        with _print_lock:
            with (log_dir / "f5_tts_hotkey.log").open("a", encoding="utf-8") as log_file:
                log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except OSError:
        pass


ROOT_DIR = Path(__file__).resolve().parents[1]
GRADIO_URL = "http://127.0.0.1:7860"
REF_AUDIO = ROOT_DIR / "resources" / "sample" / (
    "01_Ah, oh yeah, and here I go Valentino, just another fucking bay with bell. Hey hey hey..wav"
)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
VK_X = 0x58
VK_Q = 0x51
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_C = 0x43
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.CreateWindowExW.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.wintypes.HWND,
    ctypes.wintypes.HMENU,
    ctypes.wintypes.HINSTANCE,
    ctypes.wintypes.LPVOID,
]
user32.CreateWindowExW.restype = ctypes.wintypes.HWND
user32.RegisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.wintypes.UINT, ctypes.wintypes.UINT]
user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
user32.OpenClipboard.restype = ctypes.wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
user32.IsClipboardFormatAvailable.argtypes = [ctypes.wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = ctypes.wintypes.BOOL
user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
user32.GetClipboardData.restype = ctypes.wintypes.HANDLE
user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
user32.SetClipboardData.restype = ctypes.wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL

uploaded_ref_path: str | None = None
api_prefix = "/gradio_api"
window_proc_ref = None
auto = None
uia_disabled = os.environ.get("F5_TTS_USE_UIA", "0").strip().lower() not in {"1", "true", "yes", "on"}
WND_PROC_TYPE = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.c_long,
)


def get_default_ref_text() -> str:
    stem = REF_AUDIO.stem
    if "_" in stem:
        stem = stem.split("_", 1)[1]
    return stem.rstrip(".")


REF_TEXT = get_default_ref_text()


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.UINT),
        ("style", ctypes.wintypes.UINT),
        ("lpfnWndProc", WND_PROC_TYPE),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("hIcon", ctypes.wintypes.HANDLE),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HANDLE),
        ("lpszMenuName", ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
        ("hIconSm", ctypes.wintypes.HANDLE),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        # Windows INPUT is sized for the largest input union member. Without this
        # padding, SendInput receives a 32-byte structure on x64 and rejects it.
        ("_padding", ctypes.c_byte * 32),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


user32.SendInput.argtypes = [ctypes.wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.wintypes.UINT


def win_get_clipboard(retries: int = 8, delay: float = 0.03) -> str:
    for _ in range(retries):
        opened = False
        try:
            opened = bool(user32.OpenClipboard(None))
            if opened:
                if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    handle = user32.GetClipboardData(CF_UNICODETEXT)
                    if handle:
                        ptr = kernel32.GlobalLock(handle)
                        if ptr:
                            try:
                                return ctypes.wstring_at(ptr)
                            finally:
                                kernel32.GlobalUnlock(handle)
        finally:
            if opened:
                user32.CloseClipboard()
        time.sleep(delay)

    if pyperclip is not None:
        try:
            return pyperclip.paste() or ""
        except Exception:
            pass
    return ""


def win_set_clipboard(text: str, retries: int = 30, delay: float = 0.05) -> None:
    for _ in range(retries):
        opened = False
        try:
            opened = bool(user32.OpenClipboard(None))
            if opened:
                user32.EmptyClipboard()
                data = text.encode("utf-16-le") + b"\x00\x00"
                h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
                ptr = kernel32.GlobalLock(h_mem)
                if ptr:
                    ctypes.memmove(ptr, data, len(data))
                    kernel32.GlobalUnlock(h_mem)
                    if user32.SetClipboardData(CF_UNICODETEXT, h_mem):
                        return
        finally:
            if opened:
                user32.CloseClipboard()
        time.sleep(delay)

    if pyperclip is not None:
        try:
            pyperclip.copy(text)
            return
        except Exception:
            pass


def win_clear_clipboard(retries: int = 8, delay: float = 0.03) -> None:
    for _ in range(retries):
        opened = False
        try:
            opened = bool(user32.OpenClipboard(None))
            if opened:
                if user32.EmptyClipboard():
                    return
        finally:
            if opened:
                user32.CloseClipboard()
        time.sleep(delay)

    if pyperclip is not None:
        try:
            pyperclip.copy("")
            return
        except Exception:
            pass


def press_ctrl_c() -> None:
    def make_input(vk, flags=0):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
        return inp

    release = (INPUT * 6)(
        make_input(VK_MENU, KEYEVENTF_KEYUP),
        make_input(VK_LMENU, KEYEVENTF_KEYUP),
        make_input(VK_RMENU, KEYEVENTF_KEYUP),
        make_input(VK_CONTROL, KEYEVENTF_KEYUP),
        make_input(VK_LCONTROL, KEYEVENTF_KEYUP),
        make_input(VK_RCONTROL, KEYEVENTF_KEYUP),
    )
    user32.SendInput(len(release), release, ctypes.sizeof(INPUT))
    time.sleep(0.25)

    inputs = (INPUT * 4)(
        make_input(VK_CONTROL),
        make_input(VK_C),
        make_input(VK_C, KEYEVENTF_KEYUP),
        make_input(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        print(f"  SendInput sent {sent}/{len(inputs)} keys")


def press_ctrl_c_keyboard() -> bool:
    if keyboard is None:
        return False

    try:
        keyboard.release("alt")
        keyboard.release("ctrl")
        time.sleep(0.08)
        keyboard.send("ctrl+c")
        return True
    except Exception as exc:
        print(f"  keyboard fallback failed: {exc}")
        return False


def is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def wait_for_hotkey_release(timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    watched_keys = [VK_X, VK_MENU, VK_LMENU, VK_RMENU, VK_CONTROL, VK_LCONTROL, VK_RCONTROL]
    while time.time() < deadline:
        if not any(is_key_down(vk) for vk in watched_keys):
            time.sleep(0.12)
            return
        time.sleep(0.03)


def get_foreground_window_title() -> str:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_selected_text_from_control(control, depth: int = 0, deadline: float | None = None) -> str:
    if control is None or auto is None or depth > 4:
        return ""
    if deadline is not None and time.time() > deadline:
        return ""

    try:
        pattern = control.GetPattern(auto.PatternId.TextPattern)
        if pattern:
            ranges = pattern.GetSelection()
            parts = [text_range.GetText(-1).strip() for text_range in ranges]
            text = "\n".join(part for part in parts if part)
            if text:
                return text
    except Exception:
        pass

    try:
        for index, child in enumerate(control.GetChildren()):
            if index >= 80:
                break
            text = get_selected_text_from_control(child, depth + 1, deadline)
            if text:
                return text
    except Exception:
        pass

    return ""


def get_selected_text_uia() -> str:
    global auto, uia_disabled
    if uia_disabled:
        return ""

    def worker(result):
        global auto, uia_disabled
        try:
            if auto is None:
                import uiautomation as imported_auto

                auto = imported_auto
            result.append(get_selected_text_uia_inner())
        except Exception:
            result.append("")

    result: list[str] = []
    thread = threading.Thread(target=worker, args=(result,), daemon=True)
    thread.start()
    thread.join(1.8)
    if thread.is_alive():
        uia_disabled = True
        print("  UI Automation timed out; falling back to Ctrl+C")
        return ""

    return result[0] if result else ""


def get_selected_text_uia_inner() -> str:
    if auto is None:
        return ""

    deadline = time.time() + 1.5

    try:
        focused = auto.GetFocusedControl()
        text = get_selected_text_from_control(focused, deadline=deadline)
        if text:
            print("  Selected text read via UI Automation")
            return text
    except Exception:
        pass

    try:
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            foreground = auto.ControlFromHandle(int(hwnd))
            text = get_selected_text_from_control(foreground, deadline=deadline)
            if text:
                print("  Selected text read via UI Automation")
                return text
    except Exception:
        pass

    return ""


def copy_selected_text() -> str:
    wait_for_hotkey_release()
    title = get_foreground_window_title()
    if title:
        print(f"  Foreground: {title}")

    old_clipboard = win_get_clipboard()
    win_clear_clipboard()
    time.sleep(0.2)

    copy_methods = [("SendInput", press_ctrl_c)]
    if keyboard is not None:
        copy_methods.append(("keyboard", press_ctrl_c_keyboard))

    for attempt in range(4):
        method_name, method = copy_methods[attempt % len(copy_methods)]
        print(f"  Copy attempt {attempt + 1} via {method_name}")
        ok = method()
        if ok is False:
            continue
        # Wait longer for clipboard to update
        for i in range(15):
            time.sleep(0.1)
            text = win_get_clipboard(retries=2, delay=0.02)
            if text.strip():
                print(f"  Copied ({attempt + 1}): {text[:50]}{'...' if len(text) > 50 else ''}")
                if old_clipboard:
                    win_set_clipboard(old_clipboard)
                return text.strip()

    uia_text = get_selected_text_uia()
    if uia_text.strip():
        if old_clipboard:
            win_set_clipboard(old_clipboard)
        return uia_text.strip()

    print("  Clipboard unchanged after Ctrl+C")
    if old_clipboard.strip():
        print(f"  Using existing clipboard text: {old_clipboard[:50]}{'...' if len(old_clipboard) > 50 else ''}")
        return old_clipboard.strip()

    if old_clipboard:
        win_set_clipboard(old_clipboard)
    return ""


def fetch_config() -> dict:
    with urllib.request.urlopen(f"{GRADIO_URL}/config", timeout=10) as response:
        return json.load(response)


def check_server() -> bool:
    global api_prefix
    print(f"Connecting to {GRADIO_URL} ...")
    try:
        config = fetch_config()
        api_prefix = config.get("api_prefix", "/gradio_api") or "/gradio_api"
        print(f"Connected! api_prefix={api_prefix}")
        return True
    except Exception as exc:
        print(f"Failed to connect: {exc}")
        return False


def build_url(path: str) -> str:
    return urllib.parse.urljoin(f"{GRADIO_URL}/", path.lstrip("/"))


def upload_file(filepath: Path) -> str:
    boundary = "----FormBoundary7MA4YWxkTrZu0gW"
    with filepath.open("rb") as file_obj:
        file_data = file_obj.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filepath.name}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

    request = urllib.request.Request(
        build_url(f"{api_prefix}/upload"),
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))[0]


def download_file(url: str) -> str:
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=120) as response:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(response.read())
        tmp.close()
        return tmp.name


def call_tts(ref_audio_path: str, ref_text: str, gen_text: str) -> str | None:
    payload = {
        "data": [
            {"path": ref_audio_path, "meta": {"_type": "gradio.FileData"}},
            ref_text,
            gen_text,
            True,
            True,
            42,
            0.15,
            32,
            1.0,
        ]
    }

    request = urllib.request.Request(
        build_url(f"{api_prefix}/call/basic_tts"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        event_id = json.loads(response.read().decode("utf-8"))["event_id"]

    request = urllib.request.Request(build_url(f"{api_prefix}/call/basic_tts/{event_id}"), method="GET")
    with urllib.request.urlopen(request, timeout=300) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload_text = line[5:].strip()
            if not payload_text or payload_text == "[DONE]":
                continue

            data = json.loads(payload_text)
            if not data:
                continue

            first_item = data[0]
            if isinstance(first_item, dict):
                audio_url = first_item.get("url")
                if audio_url:
                    return download_file(audio_url)
                local_path = first_item.get("path")
                if local_path and os.path.exists(local_path):
                    return local_path

    return None


def do_speak() -> None:
    text = copy_selected_text()
    if not text:
        print("No text selected")
        return

    text = text[:500]
    print(f"Speaking: {text[:80]}{'...' if len(text) > 80 else ''}")

    try:
        audio_path = call_tts(uploaded_ref_path, REF_TEXT, text)  # type: ignore[arg-type]
        if not audio_path or not os.path.exists(audio_path):
            print("No audio was generated")
            return

        audio, sample_rate = sf.read(audio_path)
        sd.play(audio, sample_rate)
        sd.wait()

        try:
            os.unlink(audio_path)
        except OSError:
            pass

        print("Done!")
    except Exception as exc:
        print(f"Error: {exc}")


def do_speak_clipboard() -> None:
    text = win_get_clipboard().strip()
    if not text:
        print("Clipboard is empty")
        return

    text = text[:500]
    print(f"Speaking clipboard: {text[:80]}{'...' if len(text) > 80 else ''}")

    try:
        audio_path = call_tts(uploaded_ref_path, REF_TEXT, text)  # type: ignore[arg-type]
        if not audio_path or not os.path.exists(audio_path):
            print("No audio was generated")
            return

        audio, sample_rate = sf.read(audio_path)
        sd.play(audio, sample_rate)
        sd.wait()

        try:
            os.unlink(audio_path)
        except OSError:
            pass

        print("Done!")
    except Exception as exc:
        print(f"Error: {exc}")


def create_message_window():
    global window_proc_ref
    window_proc_ref = WND_PROC_TYPE(
        lambda hwnd, msg, wparam, lparam: user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    )

    wnd_class = WNDCLASSEX()
    wnd_class.cbSize = ctypes.sizeof(wnd_class)
    wnd_class.lpfnWndProc = window_proc_ref
    wnd_class.hInstance = kernel32.GetModuleHandleW(None)
    wnd_class.lpszClassName = "F5TTSHotkey"
    user32.RegisterClassExW(ctypes.byref(wnd_class))

    hwnd_message = ctypes.wintypes.HWND(-3)
    return user32.CreateWindowExW(0, "F5TTSHotkey", None, 0, 0, 0, 0, 0, hwnd_message, None, wnd_class.hInstance, None)


def register_hotkeys(hwnd: int) -> bool:
    if user32.RegisterHotKey(hwnd, 1, MOD_ALT | MOD_CONTROL, VK_X):
        print("Hotkey: Ctrl+Alt+X = Speak selected text")
    else:
        print("ERROR: Ctrl+Alt+X is already taken.")
        return False

    if user32.RegisterHotKey(hwnd, 3, MOD_ALT | MOD_CONTROL, VK_C):
        print("Hotkey: Ctrl+Alt+C = Speak clipboard text")
    else:
        print("ERROR: Ctrl+Alt+C is already taken.")
        user32.UnregisterHotKey(hwnd, 1)
        return False

    if user32.RegisterHotKey(hwnd, 2, MOD_ALT, VK_Q):
        print("Hotkey: Alt+Q = Quit")
    else:
        print("ERROR: Alt+Q is already taken.")
        user32.UnregisterHotKey(hwnd, 1)
        user32.UnregisterHotKey(hwnd, 3)
        return False

    return True


def main() -> None:
    global uploaded_ref_path

    print("=" * 50)
    print("  F5-TTS Global Speak Tool")
    print("=" * 50)
    print(f"Reference audio: {REF_AUDIO}")
    print(f"Reference text : {REF_TEXT}")
    print()

    if not REF_AUDIO.exists():
        print("Reference audio file is missing.")
        input("Press Enter to exit...")
        return

    if not check_server():
        input("Press Enter to exit...")
        return

    print("Uploading reference audio...")
    try:
        uploaded_ref_path = upload_file(REF_AUDIO)
        print("Reference uploaded!")
    except Exception as exc:
        print(f"Upload failed: {exc}")
        input("Press Enter to exit...")
        return

    hwnd = create_message_window()
    if not register_hotkeys(hwnd):
        input("Press Enter to exit...")
        return

    print()
    print("Ready! Select text and press Ctrl+Alt+X.")
    print()

    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), hwnd, 0, 0) != 0:
        if msg.message == WM_HOTKEY:
            if msg.wParam == 1:
                threading.Thread(target=do_speak, daemon=True).start()
            elif msg.wParam == 2:
                print("Quitting...")
                break
            elif msg.wParam == 3:
                threading.Thread(target=do_speak_clipboard, daemon=True).start()

    user32.UnregisterHotKey(hwnd, 1)
    user32.UnregisterHotKey(hwnd, 2)
    user32.UnregisterHotKey(hwnd, 3)
    user32.DestroyWindow(hwnd)


if __name__ == "__main__":
    main()
