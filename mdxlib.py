"""MDX/MDD access layer.

* `MdxDict`  - headword -> entry HTML (fast bisect lookup, LRU block cache)
* `MddPack`  - resource pack (CSS/JS/images/fonts next to a dictionary)

Both only record the location of each compressed record block at open time and
decompress on demand, so even a 1 GB resource pack costs almost nothing up
front.
"""
import bisect
import re
import threading

from mdict_utils.base.readmdict import MDD, MDX

_LINK_RE = re.compile(r"^@@@LINK=(.+)$", re.S)


class _Blocks:
    def __init__(self, reader, cache_blocks=8):
        self.mdx = reader
        self._cache = {}
        self._cache_order = []
        self._cache_max = cache_blocks
        self._lock = threading.Lock()
        self._blocks = self._index_blocks()
        self._block_starts = [b[0] for b in self._blocks]

    def _engine_version(self):
        v = self.mdx.header.get(b"GeneratedByEngineVersion", b"2.0")
        try:
            return float(v.decode())
        except Exception:
            return 2.0

    def _index_blocks(self):
        m = self.mdx
        blocks = []
        f = open(m._fname, "rb")
        try:
            f.seek(m._record_block_offset)
            if self._engine_version() >= 3.0:
                num = m._read_int32(f)
                m._read_number(f)
                offset = 0
                for _ in range(num):
                    dsize = m._read_int32(f)
                    csize = m._read_int32(f)
                    blocks.append((offset, f.tell(), csize, dsize))
                    f.seek(csize, 1)
                    offset += dsize
            else:
                num = m._read_number(f)
                m._read_number(f)
                m._read_number(f)
                m._read_number(f)
                infos = [(m._read_number(f), m._read_number(f)) for _ in range(num)]
                offset = 0
                for csize, dsize in infos:
                    blocks.append((offset, f.tell(), csize, dsize))
                    f.seek(csize, 1)
                    offset += dsize
        finally:
            f.close()
        return blocks

    def _block_data(self, j):
        with self._lock:
            if j in self._cache:
                return self._cache[j]
        _off, pos, csize, dsize = self._blocks[j]
        with open(self.mdx._fname, "rb") as f:
            f.seek(pos)
            raw = f.read(csize)
        data = self.mdx._decode_block(raw, dsize)
        with self._lock:
            self._cache[j] = data
            self._cache_order.append(j)
            while len(self._cache_order) > self._cache_max:
                old = self._cache_order.pop(0)
                self._cache.pop(old, None)
        return data

    def _raw_at(self, i):
        kl = self.mdx._key_list
        if i < 0 or i >= len(kl):
            return None
        start = kl[i][0]
        j = bisect.bisect_right(self._block_starts, start) - 1
        if j < 0:
            return None
        try:
            bdata = self._block_data(j)
        except Exception:
            return None
        boff = self._blocks[j][0]
        pos = start - boff
        end = len(bdata)
        if i + 1 < len(kl):
            nxt = kl[i + 1][0]
            if boff <= nxt <= boff + end:
                end = nxt - boff
        return bdata[pos:end]


def _decode_key(k):
    if isinstance(k, bytes):
        return k.decode("utf-8", errors="ignore")
    return k


class MdxDict(_Blocks):
    def __init__(self, path, name, cache_blocks=8):
        super().__init__(MDX(path), cache_blocks)
        self.path = path
        self.name = name
        self.keys = [_decode_key(k) for k in self.mdx.keys()]
        self._low = {}
        for i, k in enumerate(self.keys):
            kl = k.strip().lower()
            if kl and kl not in self._low:
                self._low[kl] = i

    def __len__(self):
        return len(self.keys)

    def index_of(self, word):
        return self._low.get(word.strip().lower())

    def html_at(self, i, _depth=0):
        raw = self._raw_at(i)
        if raw is None:
            return None
        try:
            text = self.mdx._treat_record_data(raw).decode("utf-8", errors="ignore")
        except Exception:
            return None
        text = text.strip("\x00 \r\n\t")
        m = _LINK_RE.match(text)
        if m and _depth < 3:
            tgt = self.index_of(m.group(1).strip())
            if tgt is not None and tgt != i:
                return self.html_at(tgt, _depth + 1)
        return text

    def lookup(self, word):
        i = self.index_of(word)
        if i is None:
            return None
        return self.html_at(i)


class MddPack(_Blocks):
    def __init__(self, path, cache_blocks=4):
        super().__init__(MDD(path), cache_blocks)
        self.path = path
        self._idx = {}
        for i, k in enumerate(self.mdx.keys()):
            key = _decode_key(k).replace("/", "\\").lstrip("\\").lower()
            if key not in self._idx:
                self._idx[key] = i

    def get(self, name):
        key = name.replace("/", "\\").lstrip("\\").lower()
        i = self._idx.get(key)
        if i is None:
            return None
        return self._raw_at(i)
