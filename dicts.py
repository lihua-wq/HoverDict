"""Dictionary registry: local MDX files + their MDD resource packs.

The app does not ship any dictionary. Point ``dict_dir`` in ``data/config.json``
at a folder full of ``.mdx`` files (and optional ``.mdd`` resources with the
same base name); every ``.mdx`` found there becomes available.
"""
import os

# Looked at when ``dict_dir`` is not configured, in this order.
DEFAULT_DIRS = [
    os.environ.get("HOVERDICT_DICTS", ""),
    r"D:\Dicts\eudic",
]


class Dictionary:
    def __init__(self, key, label, mdx_path, mdd_path=None, lazy_mdd=True):
        self.key = key
        self.label = label
        self.mdx_path = mdx_path
        self.mdd_path = mdd_path
        self.lazy_mdd = lazy_mdd
        self._dict = None
        self._pack = None

    @property
    def available(self):
        return os.path.exists(self.mdx_path)

    @property
    def dict(self):
        if self._dict is None:
            from mdxlib import MdxDict

            self._dict = MdxDict(self.mdx_path, self.label)
        return self._dict

    @property
    def pack(self):
        if self._pack is None and self.mdd_path and os.path.exists(self.mdd_path):
            from mdxlib import MddPack

            self._pack = MddPack(self.mdd_path)
        return self._pack

    def preload_pack(self):
        return self.pack is not None

    def lookup(self, word):
        return self.dict.lookup(word)


def scan_dir(path):
    """Every .mdx in *path* becomes a dictionary, labelled by its file name."""
    found = []
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return found
    for name in names:
        if not name.lower().endswith(".mdx"):
            continue
        mdx = os.path.join(path, name)
        base = mdx[:-4]
        mdd = base + ".mdd"
        key = os.path.basename(base)
        found.append(Dictionary(key, key, mdx, mdd if os.path.exists(mdd) else None))
    return found


def find_dicts(dict_dir=None, order=None):
    """Return the dictionaries to use.

    ``dict_dir`` wins; otherwise the first readable entry of :data:`DEFAULT_DIRS`
    that contains at least one .mdx is used.  ``order`` is a list of keys
    (file base names) that should come first; unknown keys are ignored and
    every remaining dictionary is appended afterwards.
    """
    candidates = [dict_dir] if dict_dir else []
    candidates += [d for d in DEFAULT_DIRS if d]
    found = []
    for path in candidates:
        if path and os.path.isdir(path):
            found = scan_dir(path)
            if found:
                break
    if order:
        by_key = {d.key: d for d in found}
        head = [by_key[k] for k in order if k in by_key]
        head_keys = {d.key for d in head}
        return head + [d for d in found if d.key not in head_keys]
    return found
