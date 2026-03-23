# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Prism (棱镜查词)** — A floating desktop widget for English word/phrase lookup with Chinese translations, slang/internet context, cultural background, and tone analysis. Powered by OpenAI API with a PyQt6 GUI featuring iOS-style "Liquid Glass" aesthetics and Windows 11 native acrylic blur.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py

# Build standalone .exe (uses Prism.spec which bundles the icon)
pip install pyinstaller
pyinstaller Prism.spec
# Output: dist/Prism.exe

# Build Windows installer (requires Inno Setup 6+)
iscc installer.iss
# Output: installer_output/Prism_Setup_1.0.0.exe
```

There are no tests or linting configured.

## Architecture

The app is a single-window PyQt6 application with 4 source files:

- **main.py** — Entry point. Creates `QApplication`, sets the app icon, loads config, shows `WelcomeDialog` (first-run API key setup) or `MainWindow`. Keeps window references in a list to prevent garbage collection.
- **ui.py** — All UI code (~700 lines). Contains:
  - `MainWindow` — Frameless, always-on-top, translucent main window with custom drag handling, search input, result sections, and settings gear button. Uses `WA_TranslucentBackground` with a custom `Panel` widget for the glass background.
  - `WelcomeDialog` — First-run dialog for API key entry.
  - `SettingsPanel` — Slide-in panel (animates from left) for API key, model selection, theme toggle (dark/light), opacity slider, and position lock toggle.
  - `LookupWorker(QThread)` — Async thread that calls `api.lookup_word()` and emits results/errors via signals.
  - Custom widgets: `Panel` (glass background painter), `SectionWidget` (frosted card), `TitleBar` (drag handling), `ToggleSwitch`, `LoadingWidget`.
- **api.py** — OpenAI API call. Sends word to chat completions with a system prompt that returns structured JSON (definition, slang_context, cultural_background, chinese_translation, tone, corrected_spelling). Uses `gpt-4o-mini` by default.
- **config.py** — Loads/saves `config.json` with defaults. Frozen builds store config in `%APPDATA%/Prism/` (safe for Program Files installs); dev mode uses the script directory. `.env` file's `OPENAI_API_KEY` takes priority over config.json for the API key.
- **installer.iss** — Inno Setup script for building a Windows installer with custom install path, Start Menu/desktop shortcuts, and language selection (English/Chinese). Uninstall cleans up `%APPDATA%/Prism/`.
- **glass.py** — Windows-only DWM helper. Applies acrylic blur via `SetWindowCompositionAttribute` and rounded corners via `DwmSetWindowAttribute`. Returns capability flags that `Panel` uses to decide rendering strategy.

## Key Design Patterns

- **Frameless window with custom chrome**: The app uses `FramelessWindowHint` + `WA_TranslucentBackground`. All window dragging is handled manually via `_DragFilter` and `TitleBar` mouse events. The `Panel` widget paints the semi-transparent background with rounded corners (software) or defers to native DWM corners when available.
- **Config cascade**: `config.py` DEFAULTS → `config.json` → `.env` (API key only). Config is a plain dict passed around; `cfg.save()` writes back to `config.json`.
- **Async lookups**: `LookupWorker` QThread handles API calls off the main thread, emitting `result_ready` or `error_occurred` signals.
- **All UI styling uses inline Qt stylesheets** with color constants defined in the `S` dict at the top of `ui.py`. The Liquid Glass palette uses RGBA alpha values extensively.

## Important Notes

- The UI language is Simplified Chinese throughout (labels, error messages, settings).
- Input is limited to 200 characters and validated as English (Latin script) before sending to the API.
- The app is Windows-focused — `glass.py` uses Win32 APIs. It degrades gracefully on other platforms (solid background fallback).
