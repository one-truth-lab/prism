import os
import sys
import traceback
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

import config as cfg
from ui import MainWindow, WelcomeDialog


def _icon_path() -> str:
    """Return the absolute path to the app icon."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "icon", "prism_icon_256.png")


def _install_exception_hook():
    """Log unhandled exceptions to stderr instead of silently dying."""
    def hook(exc_type, exc_value, exc_tb):
        print("Unhandled exception:", file=sys.stderr)
        traceback.print_exception(exc_type, exc_value, exc_tb)
    sys.excepthook = hook


def main():
    _install_exception_hook()

    app = QApplication(sys.argv)
    app.setApplicationName("Prism")
    app.setWindowIcon(QIcon(_icon_path()))

    config = cfg.load()

    # Keep a module-level reference so the window is never GC'd
    windows = []

    if not config.get("api_key"):
        welcome = WelcomeDialog()

        def on_accepted(key: str):
            config["api_key"] = key
            cfg.save(config)
            window = MainWindow()
            windows.append(window)   # prevent garbage collection
            window.show()
            welcome.deleteLater()

        def on_rejected():
            app.quit()

        welcome.accepted.connect(on_accepted)
        welcome.rejected.connect(on_rejected)
        welcome.show()
    else:
        window = MainWindow()
        windows.append(window)
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
