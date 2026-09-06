"""圖片資產取得。

Roblox UI 大半是 ImageLabel,沒有圖就只剩一堆空框,預覽價值大減。
三條來源,由近而遠:
  1. `rbxasset://…` -> 本機 Roblox 安裝目錄(免登入)
  2. 磁碟快取
  3. assetdelivery API + `.ROBLOSECURITY` cookie + **`Roblox-Place-Id` header**

第 3 條的重點是那個 header:資產權限綁在 universe 上,而這支 API 是看 place,
所以帶上該 universe 底下任一個 place id 就能下載別人的資產。
寫成 query 參數(serverplaceid=)無效,一定要是 header。
"""

import gzip
import io
import os
import re
import urllib.error
import urllib.request

CACHE_DIR = os.path.join(
    os.path.expandvars(r"%LOCALAPPDATA%"), "roblox-ui-preview", "assets"
)

_ASSET_RE = re.compile(r"(?:rbxassetid://|assetid://|/asset/?\?id=|\bid=)(\d+)", re.I)

_memory = {}
_stats = {"hit": 0, "downloaded": 0, "failed": 0, "local": 0}


def asset_id(url):
    if not url:
        return None
    m = _ASSET_RE.search(url)
    return m.group(1) if m else None


def _local_content_path(url):
    """rbxasset://textures/ui/foo.png -> <Roblox版本>/content/textures/ui/foo.png"""
    if not url.startswith("rbxasset://"):
        return None
    rel = url[len("rbxasset://") :].split("?")[0]
    from . import fonts

    for d in fonts._discover():
        content = d
        while content and os.path.basename(content) != "content":
            parent = os.path.dirname(content)
            if parent == content:
                content = None
                break
            content = parent
        if not content:
            continue
        cand = os.path.join(content, *rel.split("/"))
        if os.path.isfile(cand):
            return cand
    return None


class AssetFetcher:
    def __init__(self, cookie=None, place_id=None, enabled=True, timeout=20):
        self.cookie = cookie
        self.place_id = str(place_id) if place_id else None
        self.enabled = enabled
        self.timeout = timeout
        os.makedirs(CACHE_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    def image(self, url):
        """回傳 PIL Image(RGBA)或 None。"""
        if not url:
            return None
        if url in _memory:
            return _memory[url]

        img = None
        local = _local_content_path(url)
        if local:
            img = _open(_read_file(local))
            if img is not None:
                _stats["local"] += 1

        if img is None:
            aid = asset_id(url)
            if aid:
                data = self._bytes_for_id(aid)
                if data:
                    img = _open(data)

        _memory[url] = img
        return img

    # ------------------------------------------------------------------
    def _cache_path(self, aid):
        return os.path.join(CACHE_DIR, aid + ".bin")

    def _bytes_for_id(self, aid, depth=0):
        if depth > 2:
            return None
        path = self._cache_path(aid)
        if os.path.isfile(path):
            data = _read_file(path)
            if depth == 0:
                _stats["hit"] += 1
        else:
            if not self.enabled:
                return None
            data = self._download(aid)
            if data is None:
                _stats["failed"] += 1
                return None
            _stats["downloaded"] += 1
            try:
                with open(path, "wb") as fh:
                    fh.write(data)
            except OSError:
                pass

        # Decal / 舊式 Image 資產包了一層 rbxm,裡面才指向真正的圖
        inner = _unwrap(data)
        if inner and inner != aid:
            return self._bytes_for_id(inner, depth + 1)
        return data

    def _download(self, aid):
        req = urllib.request.Request(
            f"https://assetdelivery.roblox.com/v1/asset?id={aid}",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return _maybe_gunzip(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return None

    def _headers(self):
        h = {"User-Agent": "Roblox/WinInet"}
        if self.cookie:
            h["Cookie"] = ".ROBLOSECURITY=" + self.cookie
        if self.place_id:
            h["Roblox-Place-Id"] = self.place_id
        return h


def _maybe_gunzip(data):
    """assetdelivery 有時回 gzip 但不帶 Content-Encoding,urllib 不會自己解。"""
    if data and data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except (OSError, EOFError):
            return data
    return data


def _read_file(path):
    try:
        with open(path, "rb") as fh:
            return _maybe_gunzip(fh.read())
    except OSError:
        return None


def _open(data):
    if not data:
        return None
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.load()
        return img.convert("RGBA")
    except Exception:
        return None


def _unwrap(data):
    """資產包成 rbxm/rbxmx(Decal 之類)時,挖出裡面真正的圖片 id。"""
    if not data or len(data) < 8:
        return None
    head = data[:200]
    if not (head.startswith(b"<roblox") or head.startswith(b"<?xml") or head.startswith(b"<roblox!")):
        return None
    try:
        text = data.decode("utf-8", "ignore")
    except Exception:
        return None
    for m in re.finditer(r"rbxassetid://(\d+)", text):
        return m.group(1)
    return None


def stats():
    return dict(_stats)


COOKIE_FILES = [
    os.path.join(os.path.expanduser("~"), ".roblosecurity"),
    r"D:\Download\Ase\cookie.txt",
]

# cookie 檔常常連 Roblox 的警告字串一起貼進去,只取真正的值
_COOKIE_RE = re.compile(r"_\|WARNING[^\s\"';]*")


def _extract(raw):
    if not raw:
        return None
    m = _COOKIE_RE.search(raw)
    return m.group(0) if m else raw.strip() or None


def load_cookie(explicit=None):
    """cookie 來源:參數 > ROBLOSECURITY 環境變數 > 已知的 cookie 檔"""
    if explicit:
        if os.path.isfile(explicit):
            with open(explicit, "r", encoding="utf-8", errors="ignore") as fh:
                return _extract(fh.read())
        return _extract(explicit)
    env = os.environ.get("ROBLOSECURITY") or os.environ.get("ROBLOX_COOKIE")
    if env:
        return _extract(env)
    for path in COOKIE_FILES:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                got = _extract(fh.read())
            if got:
                return got
    return None
