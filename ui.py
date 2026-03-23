import json
import re
import openai
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QScrollArea, QSizeGrip, QFrame,
    QApplication, QSlider, QComboBox,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QEvent, QObject, QRectF,
    QPropertyAnimation, QEasingCurve, QPoint, pyqtProperty,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QBitmap, QPainterPath,
)

import config as cfg
import api as api_module
import glass

# ── Constants ─────────────────────────────────────────────────────────────────

WIN_RADIUS  = 20   # window / panel corner radius
CARD_RADIUS = 12   # section card corner radius
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# ── Liquid Glass palette ───────────────────────────────────────────────────────
# All alpha values are 0-255 (Qt convention)

# For QColor (used in paintEvent)
PANEL_BORDER     = QColor(255, 255, 255,  76)   # 0.30 white — crisp glass edge
_DARK_BASE       = (30, 30, 35)                 # dark mode RGB
_LIGHT_BASE      = (185, 178, 205)              # light mode RGB (warm lavender)
CARD_BG        = QColor(255, 255, 255,  20)   # 0.08 white
CARD_BORDER    = QColor(255, 255, 255,  38)   # 0.15 white

# For Qt stylesheets (rgba with 0-255 alpha)
S = {
    "text":         "#FFFFFF",
    "text_sub":     "rgba(255,255,255,153)",   # 0.60
    "section_hdr":  "rgba(255,255,255,153)",   # 0.60 — dim white label
    "input_bg":     "rgba(255,255,255, 31)",   # 0.12
    "input_border": "rgba(255,255,255, 64)",   # 0.25
    "input_focus":  "rgba(255,255,255,210)",   # 0.82 — bright glow
    "divider":      "rgba(255,255,255, 25)",   # subtle
    "btn_bg":       "rgba(255,255,255, 51)",   # 0.20
    "btn_border":   "rgba(255,255,255, 76)",   # 0.30
    "btn_hover":    "rgba(255,255,255, 76)",   # 0.30
    "btn_disabled": "rgba(255,255,255, 13)",   # 0.05
    "icon":         "rgba(255,255,255,153)",   # 0.60
    "icon_hover":   "rgba(255,255,255, 38)",   # 0.15 bg
}


# ── Worker ────────────────────────────────────────────────────────────────────

class LookupWorker(QThread):
    result_ready   = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, api_key: str, word: str, model: str = "gpt-4o-mini"):
        super().__init__()
        self.api_key = api_key
        self.word    = word
        self.model   = model

    def run(self):
        try:
            self.result_ready.emit(api_module.lookup_word(self.api_key, self.word, self.model))
        except openai.AuthenticationError:
            self.error_occurred.emit("🔑 API Key 无效或已过期，请在设置中更新")
        except openai.APITimeoutError:
            self.error_occurred.emit("⏱️ 请求超时，请重试")
        except openai.APIConnectionError:
            self.error_occurred.emit("🔌 网络连接失败，请检查网络后重试")
        except openai.RateLimitError:
            self.error_occurred.emit("⚠️ 请求过于频繁，请稍后再试")
        except json.JSONDecodeError as e:
            print(f"[Prism] JSON parse error: {e}")
            self.error_occurred.emit("⚠️ 解析失败，请重试")
        except Exception as e:
            print(f"[Prism] Unexpected error: {e}")
            self.error_occurred.emit("⚠️ 未能找到该词的结果，请重试")


# ── Drag filter ───────────────────────────────────────────────────────────────

class _DragFilter(QObject):
    def __init__(self, window: "MainWindow", parent=None):
        super().__init__(parent)
        self._win = window

    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton):
            return False
        t = event.type()
        if t == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and not self._win._locked:
                self._win._drag_pos = (
                    event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
                )
        elif t == QEvent.Type.MouseMove:
            if (self._win._drag_pos is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                    and not self._win._locked):
                self._win.move(event.globalPosition().toPoint() - self._win._drag_pos)
        elif t == QEvent.Type.MouseButtonRelease:
            if self._win._drag_pos is not None:
                self._win._drag_pos = None
                self._win._save_geometry()
        return False


# ── Title bar ─────────────────────────────────────────────────────────────────

class TitleBar(QWidget):
    def __init__(self, window: "MainWindow", parent=None):
        super().__init__(parent)
        self._win    = window
        self._filter = _DragFilter(window, self)
        self.setFixedHeight(48)

    def register_children(self):
        for w in self.findChildren(QWidget):
            w.installEventFilter(self._filter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._win._locked:
            self._win._drag_pos = (
                event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if (self._win._drag_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and not self._win._locked):
            self._win.move(event.globalPosition().toPoint() - self._win._drag_pos)

    def mouseReleaseEvent(self, event):
        self._win._drag_pos = None
        self._win._save_geometry()


# ── Glass Panel ───────────────────────────────────────────────────────────────

class Panel(QWidget):
    def __init__(self, opacity: float = 0.38, theme: str = "dark", parent=None):
        super().__init__(parent)
        self._opacity       = opacity
        self._base_rgb      = _DARK_BASE if theme == "dark" else _LIGHT_BASE
        self.blur_active    = False
        self.native_corners = False

    def set_overlay_opacity(self, val: float):
        self._opacity = max(0.10, min(0.98, val))
        self.update()

    def set_theme(self, theme: str):
        self._base_rgb = _DARK_BASE if theme == "dark" else _LIGHT_BASE
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        use_round = not self.native_corners
        cr = float(WIN_RADIUS) if use_round else 0.0
        rect = QRectF(self.rect())

        r, g, b = self._base_rgb
        alpha = int(self._opacity * 255)
        if not self.blur_active:
            alpha = max(alpha, 200)   # solid fallback if no blur

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(r, g, b, alpha)))
        if use_round:
            painter.drawRoundedRect(rect, cr, cr)
        else:
            painter.drawRect(rect)

        # ── Glass edge border ─────────────────────────────────────────────────
        pen = QPen(PANEL_BORDER)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        if use_round:
            painter.drawRoundedRect(inset, cr - 0.5, cr - 0.5)
        else:
            painter.drawRect(inset)

    def update_blur(self, blur: bool, native: bool):
        self.blur_active    = blur
        self.native_corners = native
        self.update()


# ── Section card ──────────────────────────────────────────────────────────────

class SectionWidget(QWidget):
    def __init__(self, icon: str, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._icon  = QLabel(icon)
        self._title = QLabel(title)
        self._icon.setStyleSheet(
            "font-size: 12px; background: transparent;"
        )
        self._title.setStyleSheet(
            f"color: {S['section_hdr']}; font-size: 10px; font-weight: 400; "
            f"letter-spacing: 1.2px; background: transparent;"
        )
        header.addWidget(self._icon)
        header.addWidget(self._title)
        header.addStretch()
        layout.addLayout(header)

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._body.setStyleSheet(
            f"color: {S['text']}; font-size: 12px; font-weight: 400; "
            f"line-height: 1.6; background: transparent;"
        )
        layout.addWidget(self._body)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        # Card background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(CARD_BG))
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

        # Card border
        pen = QPen(CARD_BORDER)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), CARD_RADIUS - 0.5, CARD_RADIUS - 0.5)

    def set_text(self, text: str, muted: bool = False):
        color = S["text_sub"] if muted else S["text"]
        self._body.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 400; "
            f"line-height: 1.6; background: transparent;"
        )
        self._body.setText(text)


# ── Toggle switch ─────────────────────────────────────────────────────────────

class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._knob_x  = 20.0 if checked else 4.0
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool, emit: bool = True):
        if val == self._checked:
            return
        self._checked = val
        anim = QPropertyAnimation(self, b"knobX")
        anim.setDuration(150)
        anim.setStartValue(self._knob_x)
        anim.setEndValue(20.0 if val else 4.0)
        anim.start()
        self._anim = anim
        if emit:
            self.toggled.emit(val)

    def _get_knob_x(self) -> float:
        return self._knob_x

    def _set_knob_x(self, v: float):
        self._knob_x = v
        self.update()

    knobX = pyqtProperty(float, _get_knob_x, _set_knob_x)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(100, 200, 120, 200) if self._checked else QColor(255, 255, 255, 55)
        p.setBrush(QBrush(track))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 44, 24, 12, 12)
        p.setBrush(QBrush(QColor(255, 255, 255, 230)))
        p.drawEllipse(int(self._knob_x), 2, 20, 20)


# ── Loading spinner ───────────────────────────────────────────────────────────

class LoadingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        layout = QHBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        self._spinner = QLabel(SPINNER_FRAMES[0])
        self._label   = QLabel("查询中...")
        self._spinner.setStyleSheet(
            f"color: {S['text']}; font-size: 15px; background: transparent;"
        )
        self._label.setStyleSheet(
            f"color: {S['text_sub']}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(self._spinner)
        layout.addWidget(self._label)

    def start(self):
        self._frame = 0
        self._timer.start(80)
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        self._spinner.setText(SPINNER_FRAMES[self._frame])


# ── Settings Panel ────────────────────────────────────────────────────────────

SETTINGS_SS = f"""
    QWidget {{
        font-family: 'Alibaba PuHuiTi', 'Alibaba PuHuiTi 2.0', 'Microsoft YaHei UI', 'Segoe UI', Arial, sans-serif;
        font-weight: 400;
        background: transparent;
        color: {S['text']};
    }}
    QLabel {{ background: transparent; }}
    QLabel#sectionTitle {{
        font-size: 11px;
        font-weight: 500;
        color: {S['section_hdr']};
        letter-spacing: 1px;
    }}
    QLabel#fieldLabel {{
        font-size: 11px;
        color: {S['text_sub']};
    }}
    QLabel#statusOk  {{ color: rgba(100,220,130,220); font-size: 11px; }}
    QLabel#statusErr {{ color: rgba(255,100,100,220); font-size: 11px; }}
    QLabel#aboutText {{ color: {S['text_sub']}; font-size: 11px; }}
    QLineEdit {{
        background: {S['input_bg']};
        border: 1px solid {S['input_border']};
        border-radius: 9px;
        padding: 7px 11px;
        color: {S['text']};
        font-size: 12px;
    }}
    QLineEdit:focus {{ border: 1px solid {S['input_focus']}; }}
    QPushButton#spBack {{
        background: transparent; border: none;
        border-radius: 7px; font-size: 16px; color: {S['icon']};
        padding: 0px 6px;
    }}
    QPushButton#spBack:hover {{ background: {S['icon_hover']}; color: {S['text']}; }}
    QPushButton#spEdit, QPushButton#spSave, QPushButton#spCancel {{
        background: {S['btn_bg']};
        color: {S['text']};
        border: 1px solid {S['btn_border']};
        border-radius: 8px;
        padding: 5px 12px;
        font-size: 11px;
    }}
    QPushButton#spEdit:hover, QPushButton#spSave:hover, QPushButton#spCancel:hover {{
        background: {S['btn_hover']};
    }}
    QPushButton#themeBtn {{
        background: {S['btn_bg']};
        color: {S['text_sub']};
        border: 1px solid {S['btn_border']};
        border-radius: 9px;
        padding: 6px 14px;
        font-size: 12px;
    }}
    QPushButton#themeBtn:checked {{
        background: rgba(255,255,255,90);
        color: {S['text']};
        border-color: rgba(255,255,255,130);
    }}
    QComboBox {{
        background: {S['input_bg']};
        border: 1px solid {S['input_border']};
        border-radius: 9px;
        padding: 6px 11px;
        color: {S['text']};
        font-size: 12px;
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox::down-arrow {{ color: {S['text_sub']}; }}
    QComboBox QAbstractItemView {{
        background: rgba(30,30,40,240);
        border: 1px solid {S['input_border']};
        color: {S['text']};
        selection-background-color: rgba(255,255,255,40);
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: rgba(255,255,255,40);
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: rgba(255,255,255,220);
        border: none;
        width: 16px; height: 16px;
        margin: -6px 0;
        border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: rgba(255,255,255,150);
        border-radius: 2px;
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{
        background: transparent; width: 4px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,60); border-radius: 2px; min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def _sp_divider() -> QFrame:
    """Thin horizontal divider line for settings panel."""
    div = QFrame()
    div.setFrameShape(QFrame.Shape.HLine)
    div.setFixedHeight(1)
    div.setStyleSheet("background: rgba(255,255,255,20); border: none;")
    return div


def _sp_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    """Label + right-aligned widget row."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(label_text)
    lbl.setObjectName("fieldLabel")
    row.addWidget(lbl)
    row.addStretch()
    row.addWidget(widget)
    return row


class SettingsPanel(QWidget):
    """Floating settings panel that slides in from the left."""

    def __init__(self, main_window: "MainWindow"):
        super().__init__(None)
        self._win  = main_window
        self._anim = None

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        if main_window._config.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._build_ui()
        self.setStyleSheet(SETTINGS_SS)

    # ── Show / hide ───────────────────────────────────────────────────────────

    def show_panel(self):
        mw   = self._win
        w, h = mw.width(), mw.height()
        mx, my = mw.x(), mw.y()
        self.resize(w, h)
        self.move(mx - w, my)
        self._panel.update_blur(*self._apply_glass())
        self.show()
        self.raise_()

        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(220)
        anim.setStartValue(QPoint(mx - w, my))
        anim.setEndValue(QPoint(mx, my))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._anim = anim

    def close_panel(self):
        mw = self._win
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(180)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(mw.x() - self.width(), mw.y()))
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self.hide)
        anim.start()
        self._anim = anim

    def _apply_glass(self):
        result = glass.apply(int(self.winId()))
        return result["blur"], result["native_corners"]

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        opacity = self._win._config.get("opacity", 0.38)
        theme   = self._win._config.get("theme", "dark")
        self._panel = Panel(opacity, theme)
        root.addWidget(self._panel)

        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        # Header
        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 14, 0)
        header.setFixedHeight(48)

        back_btn = QPushButton("←")
        back_btn.setObjectName("spBack")
        back_btn.setFixedSize(32, 32)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.close_panel)
        hl.addWidget(back_btn)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        t1 = QLabel("设置")
        t1.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {S['text']};")
        title_col.addWidget(t1)
        hl.addLayout(title_col)
        hl.addStretch()
        pl.addWidget(header)

        div = _sp_divider()
        pl.addWidget(div)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pl.addWidget(scroll, 1)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(14)
        cl.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        cl.addWidget(self._build_api_section())
        cl.addWidget(self._build_appearance_section())
        cl.addWidget(self._build_about_section())

    def _section_card(self, icon: str, title: str) -> tuple:
        """Returns (card QWidget, inner QVBoxLayout)."""
        card = SectionWidget(icon, title)
        inner = QVBoxLayout()
        inner.setContentsMargins(0, 6, 0, 0)
        inner.setSpacing(10)
        card.layout().addLayout(inner)
        return card, inner

    # ── Section: API 配置 ─────────────────────────────────────────────────────

    def _build_api_section(self) -> QWidget:
        card, inner = self._section_card("🔑", "API 配置")

        # API key display row
        key = self._win._config.get("api_key", "")
        masked = ("sk-" + "•" * 16) if key else "（未设置）"
        self._key_display = QLabel(masked)
        self._key_display.setStyleSheet(f"color: {S['text_sub']}; font-size: 11px;")

        self._edit_btn = QPushButton("修改")
        self._edit_btn.setObjectName("spEdit")
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.clicked.connect(self._start_key_edit)

        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("API Key")
        lbl.setObjectName("fieldLabel")
        key_row.addWidget(lbl)
        key_row.addStretch()
        key_row.addWidget(self._key_display)
        key_row.addSpacing(8)
        key_row.addWidget(self._edit_btn)
        inner.addLayout(key_row)

        # Edit area (hidden by default)
        self._key_edit_widget = QWidget()
        ew = QVBoxLayout(self._key_edit_widget)
        ew.setContentsMargins(0, 0, 0, 0)
        ew.setSpacing(6)

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("sk-••••••••••••••••••")
        ew.addWidget(self._key_input)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setObjectName("spSave")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_key)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("spCancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self._cancel_key_edit)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        ew.addLayout(btn_row)

        self._key_status = QLabel("")
        self._key_status.setObjectName("statusOk")
        ew.addWidget(self._key_status)

        self._key_edit_widget.hide()
        inner.addWidget(self._key_edit_widget)

        # Model selector
        inner.addWidget(_sp_divider())
        self._model_combo = QComboBox()
        self._model_combo.addItems(["gpt-4o-mini", "gpt-4o"])
        current_model = self._win._config.get("model", "gpt-4o-mini")
        idx = self._model_combo.findText(current_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        self._model_combo.currentTextChanged.connect(self._on_model_change)
        inner.addLayout(_sp_row("模型 Model", self._model_combo))

        return card

    def _start_key_edit(self):
        self._key_input.setText(self._win._config.get("api_key", ""))
        self._key_status.setText("")
        self._key_edit_widget.show()
        self._edit_btn.hide()
        self._key_input.setFocus()

    def _cancel_key_edit(self):
        self._key_edit_widget.hide()
        self._edit_btn.show()

    def _save_key(self):
        key = self._key_input.text().strip()
        if key and not key.startswith("sk-"):
            self._key_status.setObjectName("statusErr")
            self._key_status.setStyleSheet("color: rgba(255,100,100,220); font-size: 11px;")
            self._key_status.setText("❌ Key 格式无效（须以 sk- 开头）")
            return
        self._win._config["api_key"] = key
        cfg.save(self._win._config)
        masked = ("sk-" + "•" * 16) if key else "（未设置）"
        self._key_display.setText(masked)
        self._key_status.setObjectName("statusOk")
        self._key_status.setStyleSheet("color: rgba(100,220,130,220); font-size: 11px;")
        self._key_status.setText("✅ 已保存")
        self._key_edit_widget.hide()
        self._edit_btn.show()

    def _on_model_change(self, model: str):
        self._win._config["model"] = model
        cfg.save(self._win._config)

    # ── Section: 外观 ─────────────────────────────────────────────────────────

    def _build_appearance_section(self) -> QWidget:
        card, inner = self._section_card("🎨", "外观")

        # Opacity slider
        opacity_pct = int(self._win._config.get("opacity", 0.38) * 100)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(20, 95)
        self._opacity_slider.setValue(opacity_pct)
        self._opacity_slider.setFixedWidth(140)

        self._opacity_label = QLabel(f"{opacity_pct}%")
        self._opacity_label.setFixedWidth(32)
        self._opacity_label.setStyleSheet(f"color: {S['text_sub']}; font-size: 11px;")

        self._opacity_slider.valueChanged.connect(self._on_opacity_change)
        self._opacity_slider.sliderReleased.connect(self._on_opacity_released)

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("窗口透明度")
        lbl.setObjectName("fieldLabel")
        slider_row.addWidget(lbl)
        slider_row.addStretch()
        slider_row.addWidget(self._opacity_slider)
        slider_row.addSpacing(6)
        slider_row.addWidget(self._opacity_label)
        inner.addLayout(slider_row)

        # Theme toggle
        inner.addWidget(_sp_divider())
        self._dark_btn  = QPushButton("🌙 深色")
        self._light_btn = QPushButton("☀️ 浅色")
        for b in (self._dark_btn, self._light_btn):
            b.setObjectName("themeBtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        current_theme = self._win._config.get("theme", "dark")
        self._dark_btn.setChecked(current_theme == "dark")
        self._light_btn.setChecked(current_theme == "light")
        self._dark_btn.clicked.connect(lambda: self._on_theme("dark"))
        self._light_btn.clicked.connect(lambda: self._on_theme("light"))

        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(0, 0, 0, 0)
        lbl2 = QLabel("主题")
        lbl2.setObjectName("fieldLabel")
        theme_row.addWidget(lbl2)
        theme_row.addStretch()
        theme_row.addWidget(self._dark_btn)
        theme_row.addSpacing(6)
        theme_row.addWidget(self._light_btn)
        inner.addLayout(theme_row)

        return card

    def _on_opacity_change(self, value: int):
        self._opacity_label.setText(f"{value}%")
        self._win._panel.set_overlay_opacity(value / 100.0)
        self._panel.set_overlay_opacity(value / 100.0)

    def _on_opacity_released(self):
        val = self._opacity_slider.value() / 100.0
        self._win._config["opacity"] = val
        cfg.save(self._win._config)

    def _on_theme(self, theme: str):
        self._dark_btn.setChecked(theme == "dark")
        self._light_btn.setChecked(theme == "light")
        self._win._config["theme"] = theme
        cfg.save(self._win._config)
        self._win._panel.set_theme(theme)
        self._panel.set_theme(theme)

    # ── Section: 关于 ─────────────────────────────────────────────────────────

    def _build_about_section(self) -> QWidget:
        card, inner = self._section_card("ℹ️", "关于")
        name = QLabel("Prism 棱镜查词  v1.0.0")
        name.setObjectName("aboutText")
        inner.addWidget(name)
        return card


# ── Welcome / first-run dialog ────────────────────────────────────────────────

class WelcomeDialog(QWidget):
    """First-run dialog shown when no API key is configured."""

    accepted = pyqtSignal(str)   # emits the api_key on confirm
    rejected = pyqtSignal()      # emits when user closes without saving

    def __init__(self):
        super().__init__(None)
        flags = (Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.Window |
                 Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(340, 280)
        self._glass_applied = False
        self._build_ui()
        self._center()

    def _center(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._glass_applied:
            self._glass_applied = True
            QTimer.singleShot(0, self._apply_glass)

    def _apply_glass(self):
        result = glass.apply(int(self.winId()))
        self._panel.update_blur(result["blur"], result["native_corners"])
        if not result["native_corners"]:
            bmp = QBitmap(self.size())
            bmp.fill(Qt.GlobalColor.color0)
            p = QPainter(bmp)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(Qt.GlobalColor.color1)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(0, 0, self.width(), self.height(), WIN_RADIUS, WIN_RADIUS)
            p.end()
            self.setMask(bmp)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._panel = Panel(0.55)
        root.addWidget(self._panel)

        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(24, 24, 24, 24)
        pl.setSpacing(14)

        title = QLabel("欢迎使用 Prism 棱镜查词")
        title.setStyleSheet(
            f"color: {S['text']}; font-size: 14px; font-weight: 500; background: transparent;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(title)

        desc = QLabel("请输入你的 OpenAI API Key 以开始使用")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(
            f"color: {S['text_sub']}; font-size: 12px; background: transparent;"
        )
        pl.addWidget(desc)

        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("sk-••••••••••••••••••")
        self._key_input.setMinimumHeight(40)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: {S['input_bg']};
                border: 1px solid {S['input_border']};
                border-radius: 10px;
                padding: 8px 12px;
                color: {S['text']};
                font-size: 13px;
                font-family: 'Alibaba PuHuiTi', 'Alibaba PuHuiTi 2.0', 'Microsoft YaHei UI', 'Segoe UI', Arial;
            }}
            QLineEdit:focus {{ border: 1px solid {S['input_focus']}; }}
        """)
        self._key_input.returnPressed.connect(self._confirm)
        pl.addWidget(self._key_input)

        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet(
            "color: rgba(255,100,100,220); font-size: 11px; background: transparent;"
        )
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_lbl.hide()
        pl.addWidget(self._error_lbl)

        confirm_btn = QPushButton("开始使用")
        confirm_btn.setMinimumHeight(40)
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: {S['btn_bg']};
                color: {S['text']};
                border: 1px solid {S['btn_border']};
                border-radius: 10px;
                font-size: 13px;
                font-weight: 500;
                font-family: 'Alibaba PuHuiTi', 'Alibaba PuHuiTi 2.0', 'Microsoft YaHei UI', 'Segoe UI', Arial;
            }}
            QPushButton:hover {{ background: {S['btn_hover']}; }}
        """)
        confirm_btn.clicked.connect(self._confirm)
        pl.addWidget(confirm_btn)

        hint = QLabel("还没有 Key？前往 platform.openai.com 注册获取")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color: {S['text_sub']}; font-size: 10px; background: transparent;"
        )
        pl.addWidget(hint)

    def _confirm(self):
        key = self._key_input.text().strip()
        if not key:
            self._error_lbl.setText("请输入 API Key")
            self._error_lbl.show()
            return
        if not key.startswith("sk-"):
            self._error_lbl.setText("Key 格式无效（须以 sk- 开头）")
            self._error_lbl.show()
            return
        self.accepted.emit(key)
        self.hide()

    def closeEvent(self, event):
        self.rejected.emit()
        event.accept()


# ── Global stylesheet ─────────────────────────────────────────────────────────

STYLESHEET = f"""
    QWidget {{
        font-family: 'Alibaba PuHuiTi', 'Alibaba PuHuiTi 2.0', 'Microsoft YaHei UI', 'Segoe UI', Arial, sans-serif;
        font-weight: 400;
        background: transparent;
    }}
    QLabel#titleLabel {{
        color: {S['text']};
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 0.3px;
    }}
    QFrame#divider {{
        background: {S['divider']};
        border: none;
    }}
    QLineEdit#inputField {{
        background: {S['input_bg']};
        border: 1px solid {S['input_border']};
        border-radius: 11px;
        padding: 10px 14px;
        color: {S['text']};
        font-size: 13px;
    }}
    QLineEdit#inputField:focus {{
        border: 1.5px solid {S['input_focus']};
    }}
    QLineEdit#inputField[inputError="true"] {{
        border: 1.5px solid rgba(255, 80, 80, 200);
    }}
    QLineEdit#inputField::placeholder {{
        color: {S['text_sub']};
    }}
    QLabel#inlineError {{
        color: rgba(255, 100, 100, 210);
        font-size: 11px;
        background: transparent;
    }}
    QLabel#charCounter {{
        color: {S['text_sub']};
        font-size: 10px;
        background: transparent;
    }}
    QPushButton#lookupBtn {{
        background: {S['btn_bg']};
        color: {S['text']};
        border: 1px solid {S['btn_border']};
        border-radius: 11px;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 3px;
    }}
    QPushButton#lookupBtn:hover {{
        background: {S['btn_hover']};
    }}
    QPushButton#lookupBtn:disabled {{
        background: {S['btn_disabled']};
        color: rgba(255,255,255,80);
        border-color: rgba(255,255,255,20);
    }}
    QPushButton#menuBtn, QPushButton#lockBtn, QPushButton#pinBtn {{
        background: transparent;
        border: none;
        border-radius: 7px;
        font-size: 15px;
        color: {S['icon']};
    }}
    QPushButton#menuBtn:hover, QPushButton#lockBtn:hover, QPushButton#pinBtn:hover {{
        background: {S['icon_hover']};
        color: {S['text']};
    }}
    QPushButton#pinBtn:checked {{
        color: {S['text']};
    }}
    QPushButton#closeBtn {{
        background: transparent;
        border: none;
        border-radius: 7px;
        font-size: 11px;
        color: {S['icon']};
    }}
    QPushButton#closeBtn:hover {{
        background: rgba(255,60,80,200);
        color: white;
    }}
    QScrollArea#scrollArea, QWidget#resultsWidget {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 4px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,60);
        border-radius: 2px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QLabel#hintLabel {{
        color: {S['text_sub']};
        font-size: 12px;
        padding: 20px 8px;
        background: transparent;
    }}
    QLabel#errorLabel {{
        color: rgba(255,120,120,230);
        font-size: 12px;
        padding: 8px;
        background: transparent;
    }}
    QLabel#correctionLabel {{
        color: rgba(255,255,255,140);
        font-size: 11px;
        padding: 4px 2px;
        background: transparent;
    }}
"""


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._config        = cfg.load()
        self._drag_pos      = None
        self._locked        = self._config.get("lock_position", False)
        self._worker        = None
        self._glass_applied = False
        self._settings_panel: "SettingsPanel | None" = None

        self._init_window()
        self._build_ui()
        self.setStyleSheet(STYLESHEET)
        self._show_hint("在上方输入单词或短语，按回车查询")

        if not self._config.get("api_key"):
            QTimer.singleShot(300, self._prompt_api_key)

    # ── Window init ───────────────────────────────────────────────────────────

    def _init_window(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        if self._config.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(280, 320)
        self.setMaximumSize(500, 700)

        w = self._config.get("window_width", 320)
        h = self._config.get("window_height", 460)
        self.resize(w, h)

        x, y = self._config.get("window_x", -1), self._config.get("window_y", -1)
        if x >= 0 and y >= 0:
            self.move(x, y)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.move((geo.width() - w) // 2, (geo.height() - h) // 2)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._glass_applied:
            self._glass_applied = True
            QTimer.singleShot(0, self._apply_glass)

    def _apply_glass(self):
        result = glass.apply(int(self.winId()))
        native = result["native_corners"]
        self._panel.update_blur(result["blur"], native)
        if not native:
            self._update_mask()

    def _update_mask(self):
        bmp = QBitmap(self.size())
        bmp.fill(Qt.GlobalColor.color0)
        p = QPainter(bmp)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.GlobalColor.color1)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), WIN_RADIUS, WIN_RADIUS)
        p.end()
        self.setMask(bmp)

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._panel = Panel(self._config.get("opacity", 0.38), self._config.get("theme", "dark"))
        outer.addWidget(self._panel)

        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        pl.addWidget(self._build_title_bar())

        div = QFrame()
        div.setObjectName("divider")
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        pl.addWidget(div)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(14, 12, 14, 10)
        cl.setSpacing(10)
        pl.addWidget(content, 1)

        self._input = QLineEdit()
        self._input.setObjectName("inputField")
        self._input.setPlaceholderText("输入单词或短语...")
        self._input.setMinimumHeight(42)
        self._input.setMaxLength(200)
        self._input.returnPressed.connect(self._on_lookup)
        self._input.textChanged.connect(self._on_input_changed)
        cl.addWidget(self._input)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(4, 0, 4, 0)
        self._inline_error = QLabel()
        self._inline_error.setObjectName("inlineError")
        self._inline_error.hide()
        meta_row.addWidget(self._inline_error)
        meta_row.addStretch()
        self._char_counter = QLabel("0/200")
        self._char_counter.setObjectName("charCounter")
        meta_row.addWidget(self._char_counter)
        cl.addLayout(meta_row)

        self._btn = QPushButton("查  询")
        self._btn.setObjectName("lookupBtn")
        self._btn.setMinimumHeight(42)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._on_lookup)
        cl.addWidget(self._btn)

        scroll = QScrollArea()
        scroll.setObjectName("scrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cl.addWidget(scroll, 1)

        rw = QWidget()
        rw.setObjectName("resultsWidget")
        scroll.setWidget(rw)

        self._rl = QVBoxLayout(rw)
        self._rl.setContentsMargins(0, 4, 0, 8)
        self._rl.setSpacing(10)
        self._rl.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._loading = LoadingWidget()
        self._loading.hide()
        self._rl.addWidget(self._loading)

        self._hint_label = QLabel()
        self._hint_label.setObjectName("hintLabel")
        self._hint_label.setWordWrap(True)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_label.hide()
        self._rl.addWidget(self._hint_label)

        self._error_label = QLabel()
        self._error_label.setObjectName("errorLabel")
        self._error_label.setWordWrap(True)
        self._error_label.setTextFormat(Qt.TextFormat.RichText)
        self._error_label.setOpenExternalLinks(False)
        self._error_label.linkActivated.connect(self._on_error_link)
        self._error_label.hide()
        self._rl.addWidget(self._error_label)

        self._correction_label = QLabel()
        self._correction_label.setObjectName("correctionLabel")
        self._correction_label.setWordWrap(True)
        self._correction_label.hide()
        self._rl.addWidget(self._correction_label)

        self._zh_sec    = SectionWidget("🌸", "中文翻译")
        self._slang_sec = SectionWidget("💫", "网络 · 俚语")
        self._tone_sec  = SectionWidget("🎭", "语气分析")

        for s in [self._zh_sec, self._slang_sec, self._tone_sec]:
            s.hide()
            self._rl.addWidget(s)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setFixedSize(14, 14)
        grip_row.addWidget(grip)
        pl.addLayout(grip_row)

    def _build_title_bar(self) -> TitleBar:
        bar = TitleBar(self)
        bar.setObjectName("titleBar")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(2)

        self._settings_btn = self._icon_btn("≡", "menuBtn")
        self._settings_btn.setToolTip("设置")
        self._settings_btn.clicked.connect(self._show_settings)
        layout.addWidget(self._settings_btn)

        self._title_label = QLabel("棱镜查词")
        self._title_label.setObjectName("titleLabel")
        layout.addWidget(self._title_label)

        layout.addStretch()

        self._lock_btn = self._icon_btn("🔒" if self._locked else "🔓", "lockBtn")
        self._lock_btn.setToolTip("锁定 / 解锁位置")
        self._lock_btn.clicked.connect(self._toggle_lock)
        layout.addWidget(self._lock_btn)

        self._pin_btn = self._icon_btn("📌", "pinBtn")
        self._pin_btn.setToolTip("窗口置顶")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setChecked(self._config.get("always_on_top", True))
        self._pin_btn.clicked.connect(self._toggle_pin)
        layout.addWidget(self._pin_btn)

        self._close_btn = self._icon_btn("✕", "closeBtn")
        self._close_btn.clicked.connect(self.close)
        layout.addWidget(self._close_btn)

        bar.register_children()
        self._update_close_btn()
        return bar

    def _icon_btn(self, text: str, name: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName(name)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFlat(True)
        return btn

    # ── Controls ──────────────────────────────────────────────────────────────

    def _toggle_lock(self):
        self._locked = not self._locked
        self._lock_btn.setText("🔒" if self._locked else "🔓")
        self._config["lock_position"] = self._locked
        cfg.save(self._config)
        self._update_close_btn()

    def _update_close_btn(self):
        if self._locked:
            self._close_btn.setEnabled(False)
            self._close_btn.setToolTip("请先解锁后再关闭")
            self._close_btn.setCursor(Qt.CursorShape.ForbiddenCursor)
            self._close_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 7px; "
                "font-size: 11px; color: rgba(255,255,255,76); }"
            )
        else:
            self._close_btn.setEnabled(True)
            self._close_btn.setToolTip("关闭")
            self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._close_btn.setStyleSheet("")

    def _toggle_pin(self):
        pinned = self._pin_btn.isChecked()
        self._config["always_on_top"] = pinned
        self._set_always_on_top(pinned)
        cfg.save(self._config)

    def _set_always_on_top(self, on: bool):
        pos   = self.pos()
        flags = self.windowFlags()
        flags = (flags | Qt.WindowType.WindowStaysOnTopHint) if on \
                else (flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlags(flags)
        self.move(pos)
        self.show()

    def _show_settings(self):
        if self._settings_panel is None:
            self._settings_panel = SettingsPanel(self)
        self._settings_panel.show_panel()

    def _prompt_api_key(self):
        QTimer.singleShot(100, self._show_settings)

    # ── Input helpers ─────────────────────────────────────────────────────────

    def _on_input_changed(self, text: str):
        # Strip HTML tags on paste
        clean = re.sub(r'<[^>]+>', '', text)
        if clean != text:
            self._input.blockSignals(True)
            self._input.setText(clean)
            self._input.blockSignals(False)
            text = clean

        # Clear input error state when user types
        if self._input.property("inputError"):
            self._set_input_error(False)
            self._inline_error.hide()

        # Update char counter
        count = len(text)
        self._char_counter.setText(f"{count}/200")
        if count > 180:
            self._char_counter.setStyleSheet(
                "color: rgba(255,100,100,220); font-size: 10px; background: transparent;"
            )
        else:
            self._char_counter.setStyleSheet(
                f"color: {S['text_sub']}; font-size: 10px; background: transparent;"
            )

    def _set_input_error(self, on: bool):
        self._input.setProperty("inputError", on)
        self._input.style().unpolish(self._input)
        self._input.style().polish(self._input)
        self._input.update()

    def _on_error_link(self, link: str):
        if link == "settings":
            self._show_settings()

    @staticmethod
    def _is_non_english(text: str) -> bool:
        for ch in text:
            cp = ord(ch)
            if (0x4E00 <= cp <= 0x9FFF or   # CJK Unified
                    0x3040 <= cp <= 0x30FF or   # Hiragana / Katakana
                    0xAC00 <= cp <= 0xD7AF or   # Korean Hangul
                    0x0600 <= cp <= 0x06FF or   # Arabic
                    0x0400 <= cp <= 0x04FF):    # Cyrillic
                return True
        return False

    # ── Lookup ────────────────────────────────────────────────────────────────

    def _on_lookup(self):
        # Guard: ignore if a request is already in flight
        # (Enter key fires even when button is disabled)
        if self._worker is not None and self._worker.isRunning():
            return

        word = self._input.text().strip()

        # Empty / whitespace
        if not word:
            self._set_input_error(True)
            self._inline_error.setText("请输入内容 / Please enter a word or phrase")
            self._inline_error.show()
            return

        # 200-char limit (belt-and-suspenders behind setMaxLength)
        if len(word) > 200:
            self._set_input_error(True)
            self._inline_error.setText("输入内容过长，请限制在 200 字符以内")
            self._inline_error.show()
            return

        # Non-English detection
        if self._is_non_english(word):
            self._set_input_error(True)
            self._inline_error.setText("⚠️ 本工具目前仅支持英文查询")
            self._inline_error.show()
            return

        api_key = self._config.get("api_key", "")
        if not api_key:
            self._show_error("🔑 未配置 API Key，请打开设置输入")
            return

        self._clear_results()
        self._set_loading(True)

        model = self._config.get("model", "gpt-4o-mini")
        self._worker = LookupWorker(api_key, word, model)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_result(self, data: dict):
        self._set_loading(False)

        corrected = data.get("corrected_spelling")
        original  = self._input.text().strip()
        if corrected and " " not in original:
            self._correction_label.setText(f"✏️ 已自动纠正：{original} → {corrected}")
            self._correction_label.show()

        self._zh_sec.set_text(data.get("chinese_translation", ""))
        self._zh_sec.show()

        slang   = data.get("slang_context")
        culture = data.get("cultural_background")
        if slang or culture:
            parts = []
            if slang:
                parts.append(slang)
            if culture:
                parts.append(f"\n📌 文化背景：{culture}")
            self._slang_sec.set_text("\n".join(parts))
        else:
            self._slang_sec.set_text("暂无网络 / 俚语释义", muted=True)
        self._slang_sec.show()

        tone = data.get("tone", "")
        if tone:
            self._tone_sec.set_text(tone)
            self._tone_sec.show()

    def _on_error(self, message: str):
        self._set_loading(False)
        if "API Key" in message:
            self._show_error(
                f'{message}&nbsp;&nbsp;<a href="settings" '
                f'style="color:rgba(255,200,100,220);text-decoration:none;">→ 打开设置</a>'
            )
        else:
            self._show_error(message)

    def _show_error(self, message: str):
        self._clear_results()
        self._error_label.setText(message)
        self._error_label.show()

    def _show_hint(self, message: str):
        self._clear_results()
        self._hint_label.setText(message)
        self._hint_label.show()

    def _clear_results(self):
        self._hint_label.hide()
        self._error_label.hide()
        self._correction_label.hide()
        self._inline_error.hide()
        self._set_input_error(False)
        for s in [self._zh_sec, self._slang_sec, self._tone_sec]:
            s.hide()

    def _set_loading(self, active: bool):
        self._btn.setEnabled(not active)
        if active:
            self._loading.start()
        else:
            self._loading.stop()

    # ── Geometry ──────────────────────────────────────────────────────────────

    def _save_geometry(self):
        pos  = self.pos()
        size = self.size()
        self._config.update({
            "window_x":      pos.x(),
            "window_y":      pos.y(),
            "window_width":  size.width(),
            "window_height": size.height(),
        })
        cfg.save(self._config)

    def closeEvent(self, event):
        self._save_geometry()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._glass_applied and not self._panel.native_corners:
            self._update_mask()
        self._save_geometry()
