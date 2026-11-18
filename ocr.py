"""Screen capture + Windows OCR word extraction at a screen point."""
import asyncio
import ctypes
import re
from ctypes import wintypes

import mss
from PIL import Image
from winsdk.windows.globalization import Language
from winsdk.windows.graphics.imaging import (
    BitmapAlphaMode,
    BitmapPixelFormat,
    SoftwareBitmap,
)
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import DataWriter

WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’\-]*[A-Za-z]$")

STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be because been before being below
between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each
few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself
him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't
my myself no nor not of off on once only or other ought our ours ourselves out over own same shan't she she'd
she'll she's should shouldn't so some such than that that's the their theirs them themselves then there there's
these they they'd they'll they're they've this those through to too under until up very was wasn't we we'd we'll
we're we've were weren't what what's when when's where where's which while who who's whom why why's with won't
would wouldn't you you'd you'll you're you've your yours yourself yourselves also may might must shall will
one two three new use used using make made get got go going went see seen say said know known
""".split())


def cursor_pos():
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def left_button_down():
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)


def keys_down(vks):
    """True while every virtual-key in vks is held down."""
    u = ctypes.windll.user32
    return all(u.GetAsyncKeyState(vk) & 0x8000 for vk in vks)


def is_acceptable(word):
    w = word.strip(".,;:!?\"'()[]{}<>«»—–-*…")
    if len(w) < 3 or not WORD_RE.match(w):
        return None
    if w.lower() in STOPWORDS:
        return None
    if w.isupper() and len(w) <= 3:
        return None
    return w


class ScreenOcr:
    def __init__(self, language="en-US"):
        self.engine = None
        for tag in (language, "en-US"):
            try:
                eng = OcrEngine.try_create_from_language(Language(tag))
            except Exception:
                eng = None
            if eng is not None:
                self.engine = eng
                break
        if self.engine is None:
            self.engine = OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise RuntimeError("no OCR language available")
        self._mss = mss.mss()
        self._max_side = 2600  # keep very wide crops from getting slow
        self.last_debug = None
        self.last_rect = None

    def _grab(self, left, top, width, height):
        width = max(8, min(width, self._max_side))
        height = max(8, min(height, 400))
        shot = self._mss.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGBA", shot.size, shot.bgra, "raw", "BGRA")

    async def _recognize(self, img):
        writer = DataWriter()
        writer.write_bytes(img.tobytes("raw", "BGRA"))
        buf = writer.detach_buffer()
        sb = SoftwareBitmap.create_copy_from_buffer(
            buf, BitmapPixelFormat.BGRA8, img.width, img.height, BitmapAlphaMode.IGNORE
        )
        return await self.engine.recognize_async(sb)

    def words_near(self, x, y, left_pad=200, right_pad=300, up=44, down=44):
        """OCR a strip around (x, y); return (words, box).

        words: list of (text, (x, y, w, h)) in screen coords.
        box:   (left, top, right, bottom) of the captured strip.
        """
        words, box = self._scan(x, y, left_pad, right_pad, up, down)
        return words

    def _scan(self, x, y, left_pad, right_pad, up, down):
        left, top = x - left_pad, y - up
        width, height = left_pad + right_pad, up + down
        # keep the crop inside the virtual desktop, otherwise mss fails
        vs = self._mss.monitors[0]
        if left < vs["left"]:
            width -= vs["left"] - left
            left = vs["left"]
        if top < vs["top"]:
            height -= vs["top"] - top
            top = vs["top"]
        width = min(width, vs["left"] + vs["width"] - left)
        height = min(height, vs["top"] + vs["height"] - top)
        img = self._grab(left, top, max(8, width), max(8, height))
        try:
            res = asyncio.run(self._recognize(img))
        except Exception:
            return [], (left, top, left + width, top + height)
        out = []
        for line in res.lines:
            for w in line.words:
                r = w.bounding_rect
                out.append((w.text, (r.x + left, r.y + top, r.width, r.height)))
        return out, (left, top, left + width, top + height)

    @staticmethod
    def _pick(words, x, y):
        best, best_d, best_rect = None, 1e9, None
        for text, rect in words:
            wx, wy, ww, wh = rect
            dx = max(wx - x, 0, x - (wx + ww))
            dy = max(wy - y, 0, y - (wy + wh))
            d = (dx * dx + dy * dy) ** 0.5
            if d < best_d:
                best_d, best, best_rect = d, text, rect
        return best, best_d, best_rect

    def word_at(self, x, y, tol=14):
        """Return the word under the cursor, or the closest one within tol px."""
        self.last_debug = {"x": x, "y": y, "tries": []}
        self.last_rect = None
        attempts = [
            (200, 300, 44, 44, tol),
            (260, 380, 60, 60, tol + 6),
            (340, 460, 76, 76, tol + 10),
        ]
        for left_pad, right_pad, up, down, t in attempts:
            words, box = self._scan(x, y, left_pad, right_pad, up, down)
            word, dist, rect = self._pick(words, x, y)
            self.last_debug["tries"].append(
                {"crop": box, "words": words, "word": word, "dist": round(dist, 1)}
            )
            if not word:
                continue
            # a word clipped by the crop edge is probably only half read -> widen and retry
            if rect and (rect[0] - box[0] < 2 or box[2] - (rect[0] + rect[2]) < 2):
                if left_pad == attempts[-1][0]:
                    return None
                continue
            if dist <= t:
                word = is_acceptable(word)
                if word:
                    # remember where that word sits on screen (physical px), so the
                    # caller can tell when the cursor has left it
                    self.last_rect = rect
                    self.last_debug["picked"] = word
                return word
        return None
