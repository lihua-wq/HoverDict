"""HoverDict - hover a word, see its dictionary entry, collect it automatically.

Run:  .venv\\Scripts\\pythonw.exe main.py
"""
import json
import os
import sys
import time
from urllib.parse import quote

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import ocr as ocr_mod
import store
import ui
from dicts import find_dicts

APP_DIR = store.APP_DIR
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
SHOW_REQUEST = os.path.join(APP_DIR, "show.request")
DEFAULT_CONFIG = {
    "enabled": True,
    "dwell_ms": 450,
    # Folder with .mdx files. Empty means "auto-detect" (see dicts.DEFAULT_DIRS).
    "dict_dir": "",
    # Optional priority order, by MDX file name without extension.
    "dicts": [],
    "start_with_popup": False,
    "show_tip_on_start": True,
    "show_wordbook_on_start": True,
    "export_dir": os.path.join(os.path.dirname(APP_DIR), "exports"),
    "auto_export": True,
    # How long the popup survives after the cursor leaves the word (ms).
    "hide_delay_ms": 250,
    "debug": False,
}


class Registry:
    def __init__(self, dict_dir=None, order=None, labels=None):
        self.order = find_dicts(dict_dir, order)
        for d in self.order:
            if labels and d.key in labels:
                d.label = labels[d.key]
        self._by_key = {d.key: d for d in self.order}

    def get(self, key):
        return self._by_key.get(key)

    def lookup(self, word):
        for d in self.order:
            try:
                html = d.lookup(word)
            except Exception:
                html = None
            if html:
                return d, html
        return None, None


class App:
    def __init__(self, argv):
        self.qt = QApplication(argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.config = self._load_config()
        self.book = store.Wordbook()
        self.registry = Registry(
            self.config.get("dict_dir"),
            self.config.get("dicts"),
            self.config.get("dict_labels"),
        )
        self.ocr = ocr_mod.ScreenOcr()

        self._popup = None  # created on first hover: keeps startup fast
        self.bookwin = ui.WordbookWindow(self.book, self.config, self._save_config, self.set_enabled)

        self.tray, self.toggle_action = ui.make_tray(
            self.qt,
            self.open_book,
            self.set_enabled,
            self.export,
            self.quit,
            self.daily_export,
            self.bookwin.open_export_dir,
        )
        self.toggle_action.blockSignals(True)
        self.toggle_action.setChecked(not self.config["enabled"])
        self.toggle_action.blockSignals(False)

        self.anchor = None
        self.anchor_time = 0.0
        self.last_handled = None
        self.current_word = None
        self.current_rect = None  # screen rect (physical px) of the word being shown
        self._hide_at = None      # deadline set when the cursor leaves the word
        self._hotkey_latch = False

        self.timer = QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self._warm_up()
        self._greet()
        if self.config.get("show_wordbook_on_start", True):
            QTimer.singleShot(400, self.open_book)
        QTimer.singleShot(6000, self._warm_popup)

        # daily export: catch up on startup, then check every half hour
        self.export_timer = QTimer()
        self.export_timer.setInterval(30 * 60 * 1000)
        self.export_timer.timeout.connect(self._auto_export)
        self.export_timer.start()
        QTimer.singleShot(3000, self._auto_export)

    def _auto_export(self):
        """Export finished days once a day folder is configured (never today's)."""
        if not self.config.get("auto_export"):
            return
        if not self.config.get("export_dir"):
            return
        try:
            done = self.bookwin.export_daily_quiet(include_today=False)
        except Exception as exc:
            self._log("error", where="auto-export", error=repr(exc))
            try:
                self.tray.showMessage(
                    "自动导出失败",
                    f"写不进 {self.config.get('export_dir')}，已改用程序自带文件夹或需要你手动导出。",
                    QSystemTrayIcon.Warning,
                    6000,
                )
            except Exception:
                pass
            return
        if done:
            total = sum(n for _, n in done)
            try:
                self.tray.showMessage(
                    "生词本已按日导出",
                    f"{len(done)} 个日期的文件已更新，共新增 {total} 词。\n"
                    f"目录：{self.config['export_dir']}",
                    QSystemTrayIcon.Information,
                    6000,
                )
            except Exception:
                pass
            self._log("export", files=[p for p, _ in done], words=total)

    def daily_export(self):
        self.open_book()
        self.bookwin.export_daily()

    def _greet(self):
        """One toast at start-up so the (often hidden) tray icon is discoverable."""
        if not self.registry.order:
            try:
                self.tray.showMessage(
                    "找不到词库",
                    "没有找到 .mdx 词库。请在 data\\config.json 里把 dict_dir 指到放 MDX 的文件夹。",
                    QSystemTrayIcon.Warning,
                    10000,
                )
            except Exception:
                pass
            return
        if not self.config.get("show_tip_on_start", True):
            return
        try:
            self.tray.showMessage(
                "悬停查词已启动",
                "把鼠标停在一个英文单词上约 0.5 秒，就会弹出释义并自动收进生词本。\n"
                "托盘图标（可能收在 ^ 里）可以打开生词本、导出不背单词 TXT、暂停或退出。",
                QSystemTrayIcon.Information,
                8000,
            )
        except Exception:
            pass

    # ---------- helpers ----------
    def _load_config(self):
        cfg = dict(DEFAULT_CONFIG)
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
        if not os.path.exists(CONFIG_PATH):
            # First run: leave an editable file next to the data so the user can
            # point dict_dir at their own .mdx folder.
            try:
                os.makedirs(APP_DIR, exist_ok=True)
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
            except OSError:
                pass
        return cfg

    def _save_config(self):
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _dpr(self):
        scr = QApplication.screenAt(QCursor.pos()) or self.qt.primaryScreen()
        return scr.devicePixelRatio() or 1.0

    def _to_logical(self, x, y):
        d = self._dpr()
        return QPoint(int(x / d), int(y / d))

    @property
    def popup(self):
        """Lazily built: importing/creating QtWebEngine costs ~4s at startup."""
        if self._popup is None:
            self._popup = ui.Popup()
            self._popup.opened_wordbook.connect(self.open_book)
        return self._popup

    def _in_own_window(self, gx, gy):
        d = self._dpr()
        for w in (self._popup, self.bookwin):
            if w is None or not w.isVisible():
                continue
            g = w.geometry()
            if g.left() * d <= gx <= (g.left() + g.width()) * d and g.top() * d <= gy <= (g.top() + g.height()) * d:
                return True
        return False

    def _warm_up(self):
        """Touch the primary dictionary so the first hover is instant."""
        try:
            self.registry.order[0].lookup("hello") if self.registry.order else None
        except Exception:
            pass

    # ---------- hover detection ----------
    def tick(self):
        self._check_hotkey()
        self._check_show_request()
        if not self.config["enabled"]:
            return
        if ocr_mod.left_button_down():
            self.anchor = None
            return
        gx, gy = ocr_mod.cursor_pos()
        now = time.monotonic()
        self._auto_hide_tick(gx, gy, now)
        if self.last_handled and (
            abs(gx - self.last_handled[0]) > 50 or abs(gy - self.last_handled[1]) > 50
        ):
            self.last_handled = None  # came back to roughly the same spot later
        if self._in_own_window(gx, gy):
            self.anchor = None
            return

        if self.anchor is None or abs(gx - self.anchor[0]) > 6 or abs(gy - self.anchor[1]) > 6:
            self.anchor = (gx, gy)
            self.anchor_time = now
            return

        if now - self.anchor_time < self.config["dwell_ms"] / 1000.0:
            return
        if self.last_handled and abs(gx - self.last_handled[0]) < 6 and abs(gy - self.last_handled[1]) < 6:
            return
        self.last_handled = (gx, gy)
        self.handle_word(gx, gy)

    def _check_hotkey(self):
        """Ctrl+Alt+H opens the wordbook even when the tray icon is hidden."""
        held = bool(ocr_mod.keys_down((0x11, 0x12, 0x48)))
        if held and not self._hotkey_latch:
            self._hotkey_latch = True
            self.open_book()
        elif not held:
            self._hotkey_latch = False

    def _check_show_request(self):
        """A second launch drops this file, so the shortcut always shows a window."""
        try:
            if os.path.exists(SHOW_REQUEST):
                os.remove(SHOW_REQUEST)
                self.open_book()
        except OSError:
            pass

    def _auto_hide_tick(self, gx, gy, now):
        """Hide the popup soon after the cursor leaves the word it belongs to.

        Moving the cursor onto the popup itself keeps it open (so the entry can be
        read or scrolled); moving anywhere else starts a short countdown.
        """
        if self._popup is None or not self._popup.isVisible():
            self._hide_at = None
            return
        if self._cursor_on_word(gx, gy) or self._inside_popup(gx, gy):
            self._hide_at = None
            return
        delay = self.config.get("hide_delay_ms", 250) / 1000.0
        if self._hide_at is None:
            self._hide_at = now + delay
        elif now >= self._hide_at:
            self._hide_at = None
            self._maybe_hide()

    def _cursor_on_word(self, gx, gy):
        """Is the cursor still over the word whose entry is on screen?"""
        r = self.current_rect
        if not r:
            return False
        x, y, w, h = r
        pad = 8
        return (x - pad) <= gx <= (x + w + pad) and (y - pad) <= gy <= (y + h + pad)

    def _inside_popup(self, gx, gy):
        if self._popup is None or not self._popup.isVisible():
            return False
        d = self._dpr()
        g = self._popup.geometry()
        return (
            g.left() * d <= gx <= (g.left() + g.width()) * d
            and g.top() * d <= gy <= (g.top() + g.height()) * d
        )

    def _warm_popup(self):
        """Build the WebEngine popup in the background so the first hover is instant."""
        try:
            _ = self.popup
        except Exception as exc:
            self._log("error", where="warm-popup", error=repr(exc))

    def _maybe_hide(self):
        if self._popup is not None and self._popup.isVisible():
            self._popup.hide()
        self.current_word = None
        self.current_rect = None
        self._hide_at = None

    def _log(self, kind, **kw):
        """Append a JSON line to data/hover.log (misses always, hits when debug)."""
        if kind != "miss" and not self.config.get("debug"):
            return
        path = os.path.join(APP_DIR, "hover.log")
        try:
            if os.path.exists(path) and os.path.getsize(path) > 512 * 1024:
                os.replace(path, path + ".1")
            rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind}
            rec.update(kw)
            dbg = getattr(self.ocr, "last_debug", None)
            if dbg and (kind == "miss" or self.config.get("debug")):
                rec["ocr"] = dbg
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def handle_word(self, gx, gy):
        try:
            word = self.ocr.word_at(gx, gy)
        except Exception as exc:
            self._log("error", cursor=(gx, gy), error=repr(exc))
            word = None
        if not word:
            self._maybe_hide()
            self._log("miss", cursor=(gx, gy), reason="no-word")
            return
        d, html = self.registry.lookup(word)
        if not html:
            self._maybe_hide()  # word exists on screen but no local entry
            self._log("miss", cursor=(gx, gy), reason="no-entry", word=word)
            return
        if word == self.current_word and self.popup.isVisible():
            return
        rect = getattr(self.ocr, "last_rect", None)
        is_new = self.book.add(word.lower(), d.label if d else "")
        total = self.book.count()
        status = "✓ 新收录" if is_new else "已在生词本"
        self.current_word = word
        self.current_rect = rect
        self._hide_at = None
        page = ui.build_page(d, word, html)
        self.popup.show_word(word, (d.label if d else ""), status, page, f"dict://{d.key}/")
        self.popup.place_near(*self._to_logical(gx, gy).toTuple())
        if self.tray:
            self.tray.setToolTip(f"悬停查词 · 生词本 {total} 词")
        self._log("hit", cursor=(gx, gy), word=word, dict=d.key if d else "")

    # ---------- actions ----------
    def open_book(self):
        self.bookwin.show_raised()

    def set_enabled(self, enabled):
        self.config["enabled"] = bool(enabled)
        self._save_config()
        self.toggle_action.setText("暂停悬停取词" if enabled else "继续悬停取词")
        try:
            self.bookwin.sync_enabled(enabled)
        except Exception:
            pass
        if not enabled:
            self._maybe_hide()

    def export(self):
        self.open_book()
        self.bookwin.export()

    def quit(self):
        self._save_config()
        self.timer.stop()
        self.export_timer.stop()
        if self._popup is not None:
            self._popup.close()
        self.qt.quit()


def _acquire_single_instance():
    """Named mutex: released by the OS when the process dies, so no stale lock file."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\HoverDict_SingleInstance")
    if not handle:
        return True  # cannot tell; let it run rather than block the user
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def _ask_running_instance():
    """Tell the already-running copy to pop its wordbook window."""
    try:
        with open(SHOW_REQUEST, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def main():
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-gpu-compositing"
    )
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    os.makedirs(APP_DIR, exist_ok=True)
    global _MUTEX
    _MUTEX = _acquire_single_instance()
    if _MUTEX is None:
        # Already running: instead of doing nothing, ask it to show the wordbook.
        _ask_running_instance()
        print("HoverDict is already running; asked it to show the wordbook.", file=sys.stderr)
        return 0
    try:
        os.remove(SHOW_REQUEST)
    except OSError:
        pass
    ui.register_scheme()
    app = App(sys.argv)
    sys.exit(app.qt.exec())


if __name__ == "__main__":
    main()

