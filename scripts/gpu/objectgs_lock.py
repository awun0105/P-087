"""Sinh khoá hash của runtime ObjectGS cho CPython 3.8 trên Linux x86_64 (T-038, review T-037).

    python -m scripts.gpu.objectgs_lock     # ghi lại configs/runtime/objectgs/requirements.lock.txt và torch.lock.txt

Mỗi gói ghim phiên bản và liệt kê sha256 của MỌI file pip có thể chọn trên máy đó (mọi wheel tương thích và sdist),
nên cài online không cần khớp đúng file trên laptop. Gói PyPI lấy danh sách file từ JSON của PyPI; torch, torchvision,
torchaudio lấy từ index cu118 của PyTorch; torch-scatter lấy từ index PyG. Khoá torch cài với --no-deps, phụ thuộc của
torch nằm trong requirements.lock.txt.
"""

import hashlib
import html
import json
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LISTS = REPO / "configs/runtime/objectgs"
PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
TORCH_INDEX = "https://download.pytorch.org/whl/cu118/{project}/"
PYG_INDEX = "https://data.pyg.org/whl/torch-2.1.2+cu118.html"
TORCH_PACKAGES = {
    "torch": "2.1.2+cu118",
    "torchaudio": "2.1.2+cu118",
    "torchvision": "0.16.2+cu118",
}
TORCH_SCATTER = ("torch-scatter", "2.1.2+pt21cu118")
# Ubuntu 24.04 có glibc 2.39: pip ở đó chấp nhận mọi manylinux_2_x với x ≤ 39.
MAX_GLIBC_MINOR = 39
SDIST_SUFFIXES = (".tar.gz", ".zip", ".tar.bz2")
WHEEL_NAME = re.compile(
    r"^(?P<dist>[^-]+)-(?P<version>[^-]+)(?:-(?P<build>\d[^-]*))?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$"
)


def python_tag_ok(py: str, abi: str) -> bool:
    """Wheel dùng được cho CPython 3.8 (py3/py38 thuần, cp38, hoặc abi3 từ cp3x với x ≤ 8)."""
    for tag in py.split("."):
        if tag in ("py3", "py38", "cp38") and abi in ("none", "cp38"):
            return True
        if tag.startswith("cp3") and tag[3:].isdigit() and abi == "abi3" and int(tag[3:]) <= 8:
            return True
    return False


def platform_tag_ok(plat: str) -> bool:
    """Nền tảng pip trên Linux x86_64 glibc chấp nhận (không gồm musllinux, macOS, Windows)."""
    for tag in plat.split("."):
        if tag in ("any", "linux_x86_64", "manylinux1_x86_64", "manylinux2010_x86_64", "manylinux2014_x86_64"):
            return True
        match = re.fullmatch(r"manylinux_2_(\d+)_x86_64", tag)
        if match and int(match.group(1)) <= MAX_GLIBC_MINOR:
            return True
    return False


def compatible(filename: str) -> bool:
    if filename.endswith(SDIST_SUFFIXES):
        return True
    match = WHEEL_NAME.match(filename)
    return bool(match) and python_tag_ok(match["py"], match["abi"]) and platform_tag_ok(match["plat"])


def pypi_files(name: str, version: str) -> dict[str, str]:
    """Tên file → sha256 của mọi file PyPI cho đúng phiên bản."""
    with urllib.request.urlopen(PYPI_JSON.format(name=name, version=version), timeout=120) as response:
        data = json.load(response)
    return {item["filename"]: item["digests"]["sha256"] for item in data["urls"]}


def index_files(page_url: str) -> dict[str, tuple[str, str | None]]:
    """Tên file → (url tuyệt đối, sha256 hoặc None) từ một trang index kiểu simple."""
    with urllib.request.urlopen(page_url, timeout=120) as response:
        page = response.read().decode("utf-8")
    files: dict[str, tuple[str, str | None]] = {}
    for href in re.findall(r'href="([^"]+)"', page):
        target = html.unescape(href)
        digest = re.search(r"#sha256=([0-9a-f]{64})", target)
        url = urllib.parse.urljoin(page_url, target.split("#", 1)[0])
        filename = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        if filename.endswith((".whl", ".tar.gz")):
            files[filename] = (url, digest.group(1) if digest else None)
    return files


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _download_sha256(url: str, directory: Path) -> str:
    target = directory / urllib.parse.unquote(url.rsplit("/", 1)[-1])
    urllib.request.urlretrieve(url, target)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def torch_hashes(dist: str, version: str) -> list[str]:
    """sha256 của mọi wheel tương thích của torch/torchvision/torchaudio (index cu118)."""
    digests = []
    with tempfile.TemporaryDirectory() as scratch:
        for filename, (url, digest) in index_files(TORCH_INDEX.format(project=dist)).items():
            match = WHEEL_NAME.match(filename)
            if not match or _normal(match["dist"]) != _normal(dist) or match["version"] != version:
                continue
            if compatible(filename):
                digests.append(digest or _download_sha256(url, Path(scratch)))
    return sorted(set(digests))


def scatter_hashes() -> list[str]:
    """Các wheel torch-scatter tương thích từ index PyG; trang không ghi sha256 thì tải về rồi tự băm."""
    dist, version = TORCH_SCATTER
    digests = []
    with tempfile.TemporaryDirectory() as scratch:
        for filename, (url, digest) in index_files(PYG_INDEX).items():
            match = WHEEL_NAME.match(filename)
            if not match or _normal(match["dist"]) != _normal(dist) or match["version"] != version:
                continue
            if compatible(filename):
                digests.append(digest or _download_sha256(url, Path(scratch)))
    return sorted(set(digests))


def package_hashes(name: str, version: str) -> list[str]:
    files = pypi_files(name, version)
    digests = sorted({digest for filename, digest in files.items() if compatible(filename)})
    if not digests:
        raise SystemExit(f"{name}=={version}: không có file tương thích cp38 manylinux x86_64")
    return digests


def format_entry(name: str, version: str, digests: list[str]) -> str:
    lines = [f"{name}=={version} \\"]
    lines += [
        f"    --hash=sha256:{digest}" + (" \\" if i < len(digests) - 1 else "") for i, digest in enumerate(digests)
    ]
    return "\n".join(lines)


def read_lock_pins(path: Path) -> list[tuple[str, str]]:
    pins = re.findall(r"^([A-Za-z0-9_.\-]+)==([^=\s\\]+)", path.read_text(encoding="utf-8"), flags=re.M)
    return [(name, version) for name, version in pins]


def regenerate() -> None:
    lock = LISTS / "requirements.lock.txt"
    pins = read_lock_pins(lock)
    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = list(pool.map(lambda pin: package_hashes(*pin), pins))
    entries = [format_entry(name, version, digest) for (name, version), digest in zip(pins, hashes)]
    header = [
        "# Khoá gói pip của runtime ObjectGS (CPython 3.8, Linux x86_64). Mỗi gói ghim phiên bản và sha256 của MỌI file pip",
        "# có thể chọn (wheel tương thích và sdist), nên cài online và cài offline đều khớp. Sinh bởi",
        "# `python -m scripts.gpu.objectgs_lock`. Cài: pip install --require-hashes -r requirements.lock.txt",
        "# (online) hoặc thêm --no-index --find-links <thư_mục_wheel> (offline). Torch nằm ở torch.lock.txt.",
    ]
    lock.write_text("\n".join(header + entries) + "\n", encoding="utf-8")
    print(f"requirements.lock.txt: {len(entries)} gói, {sum(len(h) for h in hashes)} hash")

    torch_entries = []
    for dist, version in TORCH_PACKAGES.items():
        torch_entries.append(format_entry(dist, version, torch_hashes(dist, version)))
    torch_entries.append(format_entry(*TORCH_SCATTER, scatter_hashes()))
    torch_header = [
        "# Torch cho ObjectGS, cài trước khoá chính với --no-deps: mỗi gói có sha256 của mọi wheel tương thích CPython 3.8",
        "# Linux x86_64 trên index cu118 của PyTorch và PyG. Sinh bởi `python -m scripts.gpu.objectgs_lock`.",
    ]
    (LISTS / "torch.lock.txt").write_text("\n".join(torch_header + torch_entries) + "\n", encoding="utf-8")
    print(f"torch.lock.txt: {len(torch_entries)} gói")


if __name__ == "__main__":
    sys.exit(regenerate() or 0)
