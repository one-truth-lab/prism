"""
Windows DWM acrylic/blur-behind helper.
Returns a dict: {blur: bool, native_corners: bool}
"""
import sys
import ctypes

IS_WIN = sys.platform == "win32"


def apply(hwnd: int) -> dict:
    result = {"blur": False, "native_corners": False}
    if not IS_WIN:
        return result

    # ── Acrylic blur via SetWindowCompositionAttribute (Win10+) ──────────────
    try:
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState",   ctypes.c_int),
                ("AccentFlags",   ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId",   ctypes.c_int),
            ]

        class WCAD(ctypes.Structure):
            _fields_ = [
                ("Attribute",   ctypes.c_int),
                ("Data",        ctypes.POINTER(ctypes.c_int32)),
                ("SizeOfData",  ctypes.c_size_t),
            ]

        accent = ACCENT_POLICY()
        accent.AccentState   = 4          # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags   = 0
        accent.GradientColor = 0x00000000 # zero tint — pure blur, Panel handles the glass color

        data = WCAD()
        data.Attribute   = 19             # WCA_ACCENT_POLICY
        data.SizeOfData  = ctypes.sizeof(accent)
        data.Data        = ctypes.cast(ctypes.pointer(accent),
                                       ctypes.POINTER(ctypes.c_int32))

        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        result["blur"] = True
    except Exception:
        pass

    # ── Native rounded corners via DWM (Win11 22000+) ────────────────────────
    if result["blur"]:
        try:
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
                ctypes.sizeof(ctypes.c_int),
            )
            result["native_corners"] = True
        except Exception:
            pass

    return result
