"""Qt UI: floating dictionary popup, wordbook window, tray icon."""
import html as html_mod
import os
import shutil
import subprocess
import sys
import time

from store import APP_DIR

from PySide6.QtCore import QByteArray, QPoint, Qt, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

POPUP_CSS = """
html, body { margin:0; padding:0; background:#ffffff; }
body { font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif; font-size: 13.5px;
       color:#1f2328; padding:10px 12px 12px 12px; line-height:1.5; }
a { color:#2563eb; text-decoration:none; }
img { max-width:100%; }
.C1_word_header_word, .pagetitle, h1, h2 { font-size:20px !important; }
.C1_color_bar, .C1_word_header_star { font-size:13px; }
"""

NOT_FOUND_CSS = """
body { font-family:"Segoe UI","Microsoft YaHei UI"; padding:22px; color:#57606a; }
.w { font-size:19px; font-weight:600; color:#1f2328; }
"""


def register_scheme():
    scheme = QWebEngineUrlScheme(b"dict")
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
    )
    QWebEngineUrlScheme.registerScheme(scheme)


_MIME = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}


class DictSchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.registry = registry

    @staticmethod
    def _reply(job, mime, data):
        from PySide6.QtCore import QBuffer, QIODevice

        buf = QBuffer(job)
        buf.setData(QByteArray(data))
        buf.open(QIODevice.ReadOnly)
        job.reply(mime.encode() if isinstance(mime, str) else mime, buf)

    def requestStarted(self, job):
        url = job.requestUrl()
        key = url.host().lower()
        path = url.path()
        entry = self.registry.get(key)
        if entry is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        if path in ("/entry", "/entry/"):
            word = QUrlQuery(url).queryItemValue("w") or ""
            try:
                body = entry.lookup(word)
            except Exception:
                body = None
            page = build_page(entry, word, body)
            self._reply(job, "text/html; charset=utf-8", page.encode("utf-8"))
            return
        data = None
        try:
            pack = entry.pack
            if pack is not None:
                data = pack.get(path)
        except Exception:
            data = None
        if not data:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        ext = os.path.splitext(path)[1].lower()
        self._reply(job, _MIME.get(ext, "application/octet-stream"), data)


def _strip_body(raw):
    """Collapse an entry's own <head>/<body> wrappers into inner content."""
    low = raw.lower()
    b = low.find("<body")
    if b != -1:
        b = raw.find(">", b)
        if b != -1:
            e = low.rfind("</body>")
            return raw[b + 1 : e if e != -1 else len(raw)]
    h = low.find("<head")
    if h != -1:
        e = low.find("</head>", h)
        if e != -1:
            raw = raw[e + 7 :]
    return raw


def _collect_css(body, entry):
    """Fetch every stylesheet the entry references from its MDD and return CSS text."""
    import re

    out = []
    for href in re.findall(r'<link[^>]+href="([^"]+\.css)"[^>]*>', body, flags=re.I):
        try:
            data = entry.pack.get(href) if entry.pack is not None else None
        except Exception:
            data = None
        if data:
            out.append(data.decode("utf-8", errors="ignore"))
    return "\n".join(out)


def build_page(entry, word, body):
    w = html_mod.escape(word)
    if not body:
        return (
            '<!doctype html><html><head><meta charset="utf-8"><style>'
            + NOT_FOUND_CSS
            + '</style></head><body><div class="w">'
            + w
            + "</div><div>本地词库里没有收录这个词。</div></body></html>"
        )
    inner = _strip_body(body)
    dict_css = _collect_css(body, entry)
    return (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        + dict_css
        + "</style><style>"
        + POPUP_CSS
        + "body::-webkit-scrollbar{width:8px}body::-webkit-scrollbar-thumb{background:#d0d7de;border-radius:4px}"
        + "</style></head><body>"
        + inner
        + "</body></html>"
    )


def install_scheme_handler(registry):
    handler = DictSchemeHandler(registry)
    QWebEngineProfile.defaultProfile().installUrlSchemeHandler(b"dict", handler)
    return handler


def asset_path(name):
    """Locate a bundled file both in dev and inside a PyInstaller build."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        for candidate in (os.path.join(base, "assets", name), os.path.join(base, name)):
            if os.path.exists(candidate):
                return candidate
        return os.path.join(base, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def make_icon():
    ico = asset_path("hoverdict.ico")
    if os.path.exists(ico):
        icon = QIcon(ico)
        if not icon.isNull():
            return icon
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#2563eb"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor("#ffffff"))
    f = QFont("Segoe UI", 30, QFont.Bold)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "H")
    p.end()
    return QIcon(pm)


class Popup(QWidget):
    """Frameless floating dictionary card."""

    opened_wordbook = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            "QWidget#card{background:#ffffff;border:1px solid #d8dee4;border-radius:10px;}"
            "QLabel#title{font:600 15px 'Segoe UI';color:#1f2328;}"
            "QLabel#dict{color:#8b949e;font-size:12px;}"
            "QLabel#status{color:#1a7f37;font-size:12px;}"
            "QPushButton{border:none;background:#f3f4f6;border-radius:6px;padding:4px 10px;color:#1f2328;}"
            "QPushButton:hover{background:#e5e7eb;}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("card")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        self.title = QLabel("word")
        self.title.setObjectName("title")
        self.dict_label = QLabel("")
        self.dict_label.setObjectName("dict")
        head.addWidget(self.title)
        head.addWidget(self.dict_label)
        head.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("status")
        head.addWidget(self.status)
        lay.addLayout(head)

        self.view = QWebEngineView()
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.setMinimumHeight(120)
        lay.addWidget(self.view, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.btn_book = QPushButton("生词本")
        self.btn_book.clicked.connect(self.opened_wordbook.emit)
        foot.addWidget(self.btn_book)
        lay.addLayout(foot)

        self.resize(440, 340)

    def show_word(self, word, dict_label, status_text, page_html, base_url=""):
        self.title.setText(word)
        self.dict_label.setText(dict_label)
        self.status.setText(status_text)
        self.show()
        self.raise_()
        QTimer.singleShot(0, lambda: self.view.setHtml(page_html, QUrl(base_url)))

    def place_near(self, gx, gy):
        from PySide6.QtWidgets import QApplication

        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = gx + 16
        y = gy + 22
        if x + w > geo.right():
            x = gx - w - 16
        if y + h > geo.bottom():
            y = gy - h - 12
        x = max(geo.left(), x)
        y = max(geo.top(), y)
        self.move(x, y)


class WordbookWindow(QWidget):
    def __init__(self, book, config=None, save_config=None, on_toggle=None):
        super().__init__(None, Qt.Window)
        self.book = book
        self.config = config if config is not None else {}
        self.save_config = save_config or (lambda: None)
        self.on_toggle = on_toggle
        self.setWindowTitle("悬停生词本")
        self.resize(560, 660)
        self.setWindowIcon(make_icon())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        # 状态条：一眼看出悬停取词是开着还是关了
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.status = QLabel()
        self.status.setObjectName("statusText")
        bar.addWidget(self.dot)
        bar.addWidget(self.status)
        bar.addStretch(1)
        self.chk = QCheckBox("启用悬停查词")
        self.chk.setToolTip("关掉之后，鼠标停在单词上不会再弹窗、也不会记生词")
        self.chk.toggled.connect(self._toggled)
        bar.addWidget(self.chk)
        lay.addLayout(bar)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索单词…")
        self.search.textChanged.connect(self.reload)
        top.addWidget(self.search, 1)
        lay.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["单词", "加入时间", "次数", "导出"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 60)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("QTableWidget{border:1px solid #d8dee4;border-radius:8px;}"
                                 "QHeaderView::section{background:#f6f8fa;border:none;padding:6px;}")
        lay.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        bottom.addWidget(self.count_label)
        bottom.addStretch(1)
        self.btn_export = QPushButton("合并导出待导出…")
        self.btn_export.setToolTip("把所有还没导出过的单词合成一个 TXT（适合上传到不背单词，≥20 词）")
        self.btn_export.clicked.connect(self.export)
        self.btn_daily = QPushButton("按日导出…")
        self.btn_daily.setToolTip("每个日期一个 TXT（hoverdict-日期.txt），已导出的词不会再写第二次")
        self.btn_daily.clicked.connect(self.export_daily)
        self.btn_delete = QPushButton("删除选中")
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_open = QPushButton("打开文件夹")
        self.btn_open.setToolTip("打开按日导出保存 TXT 的文件夹")
        self.btn_open.clicked.connect(self.open_export_dir)
        bottom.addWidget(self.btn_open)
        bottom.addWidget(self.btn_delete)
        bottom.addWidget(self.btn_daily)
        bottom.addWidget(self.btn_export)
        lay.addLayout(bottom)
        self.sync_enabled(bool(self.config.get("enabled", True)))
        self.reload()

    def sync_enabled(self, enabled):
        """Update the checkbox + status pill without re-emitting the signal."""
        enabled = bool(enabled)
        self.chk.blockSignals(True)
        self.chk.setChecked(enabled)
        self.chk.blockSignals(False)
        if enabled:
            self.status.setText("正在运行 · 鼠标停在单词上就会查词")
            self.dot.setStyleSheet("background:#1a7f37;border-radius:5px;")
            self.status.setStyleSheet("color:#1a7f37;font-weight:600;")
        else:
            self.status.setText("已暂停 · 不会查词，也不记生词")
            self.dot.setStyleSheet("background:#8c959f;border-radius:5px;")
            self.status.setStyleSheet("color:#57606a;font-weight:600;")

    def _toggled(self, checked):
        self.sync_enabled(checked)
        if self.on_toggle is not None:
            self.on_toggle(bool(checked))

    def show_raised(self):
        self.reload()
        self.show()
        self.raise_()
        self.activateWindow()
        hwnd = int(self.winId())
        try:
            import ctypes

            u = ctypes.windll.user32
            SWP_NOMOVE_NOSIZE = 0x0002 | 0x0001
            u.ShowWindow(hwnd, 9)  # SW_RESTORE
            if not u.SetForegroundWindow(hwnd):
                # Windows refuses foreground rights to background processes;
                # flip to topmost and back, which brings the window to the front.
                u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE)  # HWND_TOPMOST
                u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE)  # HWND_NOTOPMOST
                u.SetForegroundWindow(hwnd)
            u.BringWindowToTop(hwnd)
        except Exception:
            pass

    def reload(self):
        rows = self.book.words(self.search.text().strip())
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            word, added, count, brief = row[0], row[1], row[2], row[3]
            exported = row[4] if len(row) > 4 else ""
            self.table.setItem(i, 0, QTableWidgetItem(word))
            self.table.setItem(i, 1, QTableWidgetItem(added.replace("T", " ")))
            self.table.setItem(i, 2, QTableWidgetItem(str(count)))
            self.table.setItem(i, 3, QTableWidgetItem("✓" if exported else ""))
        pending = sum(len(v) for v in self.book.pending_by_day().values())
        self.count_label.setText(f"共 {len(rows)} 个单词 · 待导出 {pending}")

    def delete_selected(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return
        for r in rows:
            word = self.table.item(r, 0).text()
            self.book.remove(word)
        self.reload()

    # ---------- exporting ----------
    def _default_dir(self):
        """Prefer <program>/exports; fall back to <data>/exports."""
        base = os.path.dirname(APP_DIR.rstrip("\\/"))
        for cand in (os.path.join(base, "exports"), os.path.join(APP_DIR, "exports")):
            if self._check_dir(cand):
                return cand
        return os.path.join(APP_DIR, "exports")

    def _check_dir(self, path):
        """Return True when we can actually create files in `path`."""
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".hoverdict_write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return True
        except OSError:
            return False

    def _ask_fallback(self, path, why):
        """The chosen folder is not writable: offer the app's own folder instead."""
        fallback = self._default_dir()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("这个文件夹写不进去")
        box.setText(f"无法向这个位置写入文件：\n{path}\n\n{why}")
        box.setInformativeText(f"要改用程序自带的文件夹吗？\n{fallback}\n\n"
                               "（导完可以点「复制到桌面」，文件会直接放到桌面）")
        yes = box.addButton("用自带文件夹", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return None
        if not self._check_dir(fallback):
            QMessageBox.critical(self, "仍然失败", f"连 {fallback} 也写不进去，请检查磁盘权限。")
            return None
        self.config["export_dir"] = fallback
        self.save_config()
        return fallback

    def open_export_dir(self):
        path = self.config.get("export_dir") or self._default_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "打不开", f"{path}\n\n{exc}")
            return
        # os.startfile() fails with WinError 5 on this machine; Explorer itself is fine.
        try:
            subprocess.Popen(["explorer", os.path.normpath(path)])
            return
        except OSError:
            pass
        try:
            os.startfile(path)
        except OSError as exc:
            QMessageBox.critical(self, "打不开", f"{path}\n\n{exc}")

    def _desktop_dir(self):
        try:
            from PySide6.QtCore import QStandardPaths

            d = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
            if d and os.path.isdir(d):
                return os.path.normpath(d)
        except Exception:
            pass
        return os.path.join(os.path.expanduser("~"), "Desktop")

    def _copy_via_shell(self, src, dest_dir):
        """Copy through the Explorer COM object: the shell itself is allowed to write the desktop."""
        def q(text):
            return "'" + os.path.normpath(text).replace("'", "''") + "'"

        ps = (
            "$sh = New-Object -ComObject Shell.Application; "
            f"$sh.Namespace({q(dest_dir)}).CopyHere({q(src)}, 16)"
        )
        target = os.path.join(dest_dir, os.path.basename(src))
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                timeout=25,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        for _ in range(60):
            if os.path.exists(target):
                return True
            time.sleep(0.1)
        return False

    def copy_to_desktop(self, paths):
        """Copy TXTs to the desktop; fall back to the Explorer COM copy when blocked."""
        dest = self._desktop_dir()
        done, failed = [], []
        for p in paths:
            try:
                shutil.copy2(p, os.path.join(dest, os.path.basename(p)))
                done.append(os.path.basename(p))
                continue
            except OSError:
                pass
            if self._copy_via_shell(p, dest):
                done.append(os.path.basename(p))
            else:
                failed.append(os.path.basename(p))
        if done:
            QMessageBox.information(
                self,
                "已复制到桌面" if not failed else "部分复制成功",
                "已放到桌面：\n" + "\n".join(done)
                + ("\n\n失败：" + "、".join(failed) if failed else ""),
            )
            return
        # Last resort: reveal the file in Explorer so it is one drag away.
        try:
            subprocess.Popen(
                ["explorer", "/select,", os.path.normpath(paths[0] if paths else self._default_dir())]
            )
        except OSError:
            pass
        QMessageBox.warning(
            self,
            "没能复制到桌面",
            "系统禁止程序往桌面写文件。\n\n"
            "已经帮你打开导出文件夹，把 TXT 拖到桌面即可。\n"
            f"文件位置：{self.config.get('export_dir') or self._default_dir()}",
        )

    def export(self):
        """One file with every word that was never exported."""
        pending = self.book.pending_by_day()
        total = sum(len(v) for v in pending.values())
        if total == 0:
            QMessageBox.information(
                self, "没有待导出", "所有单词都已经导出过了。\n悬停新词后这里才会有内容。"
            )
            return
        default = os.path.join(self.config.get("export_dir", self._default_dir()),
                               "hoverdict_pending.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, f"合并导出 {total} 个待导出单词", default, "Text (*.txt)"
        )
        if not path:
            return
        if not self._check_dir(os.path.dirname(path) or "."):
            path = os.path.join(
                self._ask_fallback(os.path.dirname(path) or path, "权限不足（系统不允许写入该位置）。")
                or self._default_dir(),
                "hoverdict_pending.txt",
            )
        try:
            n = self.book.export_pending_all(path)
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", f"写入失败：\n{path}\n\n{exc}")
            return
        self.reload()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("导出完成")
        box.setText(f"已导出 {n} 个单词到：\n{path}")
        box.setInformativeText(
            "导入方法：登录 bbdc.cn → 右上角菜单 → 自定义词书 → 上传该 TXT，"
            "识别后点「保存并同步」，手机 App 里即可看到（每行一个单词，≥20 词）。\n\n"
            "这些词已记为「已导出」，之后不会再重复导出。"
        )
        desk_btn = box.addButton("复制到桌面", QMessageBox.ActionRole)
        box.addButton("好", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is desk_btn:
            self.copy_to_desktop([path])

    def export_daily(self):
        """One TXT per day; already exported words are never written again."""
        pending = self.book.pending_by_day()
        if not pending:
            QMessageBox.information(
                self, "没有待导出", "所有单词都已经导出过了。\n悬停新词后这里才会有内容。"
            )
            return
        start = self.config.get("export_dir") or self._default_dir()
        try:
            os.makedirs(start, exist_ok=True)
        except OSError:
            start = self._default_dir()
        out_dir = QFileDialog.getExistingDirectory(self, "选择按日导出的文件夹", start)
        if not out_dir:
            return
        if not self._check_dir(out_dir):
            out_dir = self._ask_fallback(
                out_dir, "权限不足：系统（或安全软件）不允许程序往这里写文件。"
            )
            if not out_dir:
                return
        self.config["export_dir"] = out_dir
        self.save_config()
        try:
            done = self.book.export_days(out_dir, include_today=True)
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", f"写入失败：\n{out_dir}\n\n{exc}")
            return
        self.reload()
        if not done:
            QMessageBox.information(self, "没有可写的词", "这些词已经导出过了，没有新增内容。")
            return
        lines = "\n".join(f"· {os.path.basename(p)}：{n} 词" for p, n in done)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("按日导出完成")
        box.setText(f"共 {len(done)} 个日期，已导出到：\n{out_dir}\n\n{lines}")
        box.setInformativeText("每天一个文件，已导出的词不会再次写入（同一天有新词会追加到当天文件末尾）。")
        open_btn = box.addButton("打开文件夹", QMessageBox.ActionRole)
        desk_btn = box.addButton("复制到桌面", QMessageBox.ActionRole)
        box.addButton("好", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self.open_export_dir()
        elif box.clickedButton() is desk_btn:
            self.copy_to_desktop([p for p, _ in done])

    def export_daily_quiet(self, include_today=False):
        """Auto export used by the tray timer; returns [(path, n), ...]."""
        out_dir = self.config.get("export_dir")
        if not out_dir:
            return []
        if not self._check_dir(out_dir):
            fallback = self._default_dir()
            if not self._check_dir(fallback):
                raise OSError(f"cannot write export folder: {out_dir}")
            out_dir = fallback
            self.config["export_dir"] = out_dir
            self.save_config()
        done = self.book.export_days(out_dir, include_today=include_today)
        if done:
            self.reload()
        return done


def make_tray(app, on_open_book, on_toggle, on_export, on_quit,
              on_daily_export=None, on_open_export_dir=None):
    tray = QSystemTrayIcon(make_icon(), app)
    tray.setToolTip("悬停查词 · HoverDict")
    menu = QMenu()
    act_book = QAction("打生词本…", menu)
    act_book.triggered.connect(on_open_book)
    act_toggle = QAction("暂停悬停取词", menu)
    act_toggle.setCheckable(True)
    act_toggle.toggled.connect(on_toggle)
    act_export = QAction("合并导出待导出词…", menu)
    act_export.triggered.connect(on_export)
    menu.addAction(act_book)
    menu.addSeparator()
    menu.addAction(act_toggle)
    menu.addAction(act_export)
    if on_daily_export is not None:
        act_daily = QAction("按日导出…", menu)
        act_daily.triggered.connect(on_daily_export)
        menu.addAction(act_daily)
    if on_open_export_dir is not None:
        act_open = QAction("打开导出文件夹", menu)
        act_open.triggered.connect(on_open_export_dir)
        menu.addAction(act_open)
    act_quit = QAction("退出", menu)
    act_quit.triggered.connect(on_quit)
    menu.addSeparator()
    menu.addAction(act_quit)
    tray.setContextMenu(menu)
    tray.show()
    return tray, act_toggle
