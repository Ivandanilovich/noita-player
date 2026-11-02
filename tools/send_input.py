"""OS-level input injection via SendInput (no dependencies).

Used by automated live tests to drive Noita's menus (this game's menus need
the mouse: keyboard Enter does nothing unless an item is highlighted).
Also the building block for the Phase 2 reflex layer.

Usage:
    python tools/send_input.py key enter        # key press (default: enter)
    python tools/send_input.py key w
    python tools/send_input.py click 0.49 0.464 # click at RELATIVE screen coords (0..1)
    python tools/send_input.py click 1259 502   # ...or absolute pixels

Key names: enter escape space up down left right and a-z.
"""
from __future__ import annotations

import ctypes
import sys

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
VK = {
    "enter": 0x0D,
    "escape": 0x1B,
    "space": 0x20,
    "a": 0x41, "d": 0x44, "e": 0x45, "f": 0x46,
    "s": 0x53, "w": 0x57,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    **{c: 0x41 + i for i, c in enumerate("bcghijklmnopqrtuvxyz")},
}

user32 = ctypes.windll.user32
GetSystemMetrics = user32.GetSystemMetrics
SM_CXSCREEN, SM_CYSCREEN = 0, 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_size_t),  # ULONG_PTR (8 bytes on x64)
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamLo", ctypes.c_ushort),
        ("wParamHi", ctypes.c_ushort),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        # Union must be as big as its largest member (MOUSEINPUT) or
        # SendInput rejects the struct (ERROR_INVALID_PARAMETER, err=87).
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]

    _fields_ = [("type", ctypes.c_uint), ("u", _U)]


def _send_one(inp: _INPUT) -> None:
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    if sent != 1:
        raise RuntimeError(f"SendInput failed (err={ctypes.GetLastError()})")


def list_noita_windows():
    """All top-level windows with 'noita' in the title: [(hwnd, title), ...].

    NOTE: this also matches IDE windows showing the 'noita-player' project —
    callers that need the GAME window must use _find_noita_window().
    """
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if "noita" in buf.value.lower():
                out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(_cb, None)
    return out


def _find_noita_window():
    """Handle of the GAME window (title 'Noita - Build ...'), else None."""
    for hwnd, title in list_noita_windows():
        if title.lower().startswith("noita - build"):
            return hwnd
    return None


def focus_noita() -> bool:
    hwnd = _find_noita_window()
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # SetForegroundWindow often fails for background processes (focus-steal
    # protection); for CLICKS we don't need keyboard focus anyway, so also
    # raise the z-order, which always works, and clear strays in click().
    user32.SetForegroundWindow(hwnd)
    return True


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _raise_and_clear(hwnd, px: int, py: int) -> None:
    """Ensure the click point lands on `hwnd`.

    Raise hwnd to the top of the z-order (SetWindowPos works from a
    background process), then minimize whatever still covers the point.
    """
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
    for _ in range(8):
        target = user32.WindowFromPoint(_POINT(px, py))
        if not target or target == hwnd:
            return
        user32.ShowWindow(target, 6)  # SW_MINIMIZE
        print(f"note: minimized stray window 0x{target:x} covering the click point", flush=True)


def set_topmost(hwnd, on: bool) -> None:
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
    top = -1 if on else 1  # HWND_TOPMOST / HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, top, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)


def key(name: str) -> None:
    vk = VK.get(name.lower())
    if vk is None:
        raise SystemExit(f"unknown key: {name!r} (choices: {', '.join(sorted(VK))})")
    if not focus_noita():
        print("note: Noita window not found; sending to whatever is focused", flush=True)
    down, up = _INPUT(), _INPUT()
    down.type = up.type = INPUT_KEYBOARD
    down.u.ki.wVk = up.u.ki.wVk = vk
    up.u.ki.dwFlags = KEYEVENTF_KEYUP
    _send_one(down)
    _send_one(up)
    print(f"key '{name}' sent", flush=True)


def click(x: float, y: float, relative: bool = True) -> None:
    """Left mouse button click. relative=True: coords are fractions (0..1) of the
    primary screen; absolute pixel coords otherwise."""
    if not focus_noita():
        print("note: Noita window not found; sending to whatever is focused", flush=True)
    w, h = GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)
    if relative:
        px, py = x * w, y * h
    else:
        px, py = x, y
    hwnd = _find_noita_window()
    if hwnd:
        _raise_and_clear(hwnd, int(px), int(py))
    # SendInput absolute coords: 0..65535 over the virtual screen; use primary
    # screen metrics (single-monitor setup assumed).
    dx = int(65535 * (px / w)) if w else 0
    dy = int(65535 * (py / h)) if h else 0

    def _mouse(flags: int) -> _INPUT:
        inp = _INPUT()
        inp.type = 0  # INPUT_MOUSE
        inp.u.mi.dx = dx
        inp.u.mi.dy = dy
        inp.u.mi.dwFlags = flags
        return inp

    _send_one(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE))
    _send_one(_mouse(MOUSEEVENTF_LEFTDOWN))
    _send_one(_mouse(MOUSEEVENTF_LEFTUP))
    print(f"clicked at ({px:.0f},{py:.0f}) of ({w}x{h})", flush=True)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("key", "click", "topmost", "untopmost", "list", "fix-topmost"):
        print(__doc__, flush=True)
        raise SystemExit(2)
    cmd = sys.argv[1]
    if cmd == "list":
        for hwnd, title in list_noita_windows():
            print(f"0x{hwnd:x}  {title}", flush=True)
        return
    if cmd == "fix-topmost":
        # repair: drop topmost from every non-game 'noita' window, put the game on top
        game = _find_noita_window()
        if not game:
            raise SystemExit("game window not found")
        for hwnd, title in list_noita_windows():
            if hwnd != game:
                set_topmost(hwnd, False)
                print(f"untopmost: 0x{hwnd:x} {title!r}", flush=True)
        set_topmost(game, True)
        print(f"topmost:   0x{game:x} (game)", flush=True)
        return
    if cmd in ("topmost", "untopmost"):
        hwnd = _find_noita_window()
        if not hwnd:
            raise SystemExit("Noita window not found")
        set_topmost(hwnd, cmd == "topmost")
        print(f"noita {'topmost' if cmd == 'topmost' else 'notopmost'}: OK", flush=True)
        return
    arg = sys.argv[2]
    if cmd == "key":
        key(arg)
    else:
        x = float(arg)
        y = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
        relative = not (x > 1.0 and y > 1.0)
        click(x, y, relative=relative)


if __name__ == "__main__":
    main()