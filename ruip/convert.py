r"""二進位 .rbxl/.rbxm 與 XML 之間的轉檔,外加一層快取。

借 rbxl-to-folder 的 `rbxl-engine`(rbx-dom)。實測數字(2026-08-29,本機):

    QTE_Trainer.rbxlx  30 MB  --to-rbxm-->  2.4 MB      4 秒
    同一個 2.4 MB rbxl --to-xml -->  50 MB XML       1 分 41 秒
    nightbound.rbxl    38 MB  --to-xml -->  200 MB+   超過 13 分鐘、吃掉 6 GB RAM

**寫 XML 是慢的那一邊,而且慢得不成比例。** 沒有快取的話,對同一個 .rbxl 每跑一次
preview 或 sculpt 就要重付一次這個代價 —— 在 agent 的「看→改→再看」迴圈裡完全不能用。
所以轉出來的 XML 存到 `%LOCALAPPDATA%\roblox-ui-preview\xml\`,以
(絕對路徑, 大小, mtime) 當鍵;原檔一改快取自然失效。

保真度已驗:35600 instances / 6 ScreenGui / 82 UICorner / 150 腳本進出一趟完全一致。
唯一的差別是 rbx_xml **不做差異序列化** —— 它把每個屬性都寫出來(所以 30 MB 的 XML
繞一圈會變 50 MB)。語意相同,只是變胖。
"""

import hashlib
import os
import shutil
import subprocess
import sys

ENGINE_CANDIDATES = [
    r"C:\Users\CL\rbxl-to-folder\rust\target\release\rbxl-engine.exe",
    r"C:\Users\CL\rbxl-to-ai\rust\target\release\rbxl-engine.exe",
]

BINARY_EXTS = (".rbxl", ".rbxm")
XML_EXTS = (".rbxlx", ".rbxmx")


def cache_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "roblox-ui-preview", "xml")


class ConvertError(RuntimeError):
    pass


def find_engine():
    for p in ENGINE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return shutil.which("rbxl-engine")


def _require_engine(path):
    engine = find_engine()
    if not engine:
        raise ConvertError(
            "%s 是二進位格式,需要 rbxl-engine 轉檔。\n"
            "找不到它 —— 預期在 %s\n"
            "(到 rbxl-to-folder/rust 跑 `cargo build --release` 就會有)"
            % (path, ENGINE_CANDIDATES[0])
        )
    return engine


def is_binary(path):
    return path.lower().endswith(BINARY_EXTS)


def _key(path):
    st = os.stat(path)
    raw = "%s|%d|%d" % (os.path.abspath(path).lower(), st.st_size, int(st.st_mtime))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def to_xml(path, use_cache=True, verbose=True):
    """二進位 -> XML 檔路徑。輸入本來就是 XML 就原樣回傳(不複製)。

    回 (xml_path, from_cache)。xml_path 在快取目錄裡,**呼叫端不要刪它**。
    """
    if not is_binary(path):
        return path, False

    engine = _require_engine(path)
    cached = os.path.join(cache_dir(), _key(path) + ".rbxlx")
    if use_cache and os.path.isfile(cached) and os.path.getsize(cached) > 0:
        return cached, True

    os.makedirs(cache_dir(), exist_ok=True)
    tmp = cached + ".part"
    if verbose:
        mb = os.path.getsize(path) / 1e6
        print("[convert] %s (%.1f MB) 轉 XML 中 —— 大檔可能要好幾分鐘,"
              "結果會快取起來,下次就免了。" % (os.path.basename(path), mb),
              file=sys.stderr)
    proc = subprocess.run([engine, "--to-xml", path, tmp],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(tmp):
        if os.path.isfile(tmp):
            os.unlink(tmp)
        raise ConvertError("rbxl-engine --to-xml 失敗:\n" + (proc.stderr or proc.stdout))
    os.replace(tmp, cached)
    return cached, False


def to_binary(xml_path, out_path, verbose=True):
    """XML -> 二進位。out_path 的副檔名不影響格式,一律寫 binary。"""
    engine = _require_engine(out_path)
    proc = subprocess.run([engine, "--to-rbxm", xml_path, out_path],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise ConvertError("rbxl-engine --to-rbxm 失敗:\n" + (proc.stderr or proc.stdout))
    if verbose:
        print("[convert] 寫出二進位 %s" % out_path, file=sys.stderr)
    return out_path


def instance_count(path):
    """粗略但夠用的完整性檢查:數 <Item class=。二進位會先轉 XML(走快取)。"""
    xml_path, _ = to_xml(path, verbose=False)
    n = 0
    with open(xml_path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            n += chunk.count(b"<Item class=")
    return n


def clear_cache():
    d = cache_dir()
    if os.path.isdir(d):
        shutil.rmtree(d)
    return d
