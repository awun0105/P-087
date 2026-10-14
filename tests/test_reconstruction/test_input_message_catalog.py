"""Mọi mã lỗi/cảnh báo của luồng nhận diện input phải có câu tiếng Việt trong danh mục giao diện.

Backend thêm mã mới mà quên dịch thì người dùng sẽ thấy câu tiếng Anh của máy chủ; test này chặn điều đó.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "frontend/src/features/studio/inputMessages.ts"
RESOLVER = ROOT / "src/services/reconstruction/inputs/input_resolver.py"
PROBE = ROOT / "src/services/reconstruction/inputs/input_probe.py"

_RESOLVER_CODE = re.compile(r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+")
_PROBE_CODE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def _catalog_codes() -> set[str]:
    text = CATALOG.read_text(encoding="utf-8")
    body = text[text.index("export const INPUT_MESSAGES") : text.index("};", text.index("export const INPUT_MESSAGES"))]
    return set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):", body, flags=re.MULTILINE))


def _emitted_probe_codes() -> set[str]:
    """Mã chẩn đoán của probe: chuỗi thứ nhất trong `_invalid_content(..., "code", ...)` / `_invalid_upload` / tuple."""
    tree = ast.parse(PROBE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in {"_invalid_content", "_invalid_upload"}:
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    if _PROBE_CODE.fullmatch(argument.value) and " " not in argument.value:
                        found.add(argument.value)
    # diagnostic=("code", "severity", "message")
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "diagnostic" and isinstance(node.value, ast.Tuple):
            first = node.value.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def test_every_resolver_code_has_a_vietnamese_message() -> None:
    emitted = {value for value in _string_constants(RESOLVER) if _RESOLVER_CODE.fullmatch(value)}
    # Hằng số trùng mẫu nhưng không phải mã hiển thị cho người dùng.
    emitted -= {"INPUT_ASSEMBLY_RUNNABLE_RECIPE_GROUPS"}
    missing = sorted(emitted - _catalog_codes())
    assert not missing, f"thiếu câu tiếng Việt trong inputMessages.ts cho: {missing}"


def test_every_probe_diagnostic_code_has_a_vietnamese_message() -> None:
    emitted = _emitted_probe_codes()
    assert emitted, "không tìm thấy mã chẩn đoán nào của probe: kiểm lại cách quét"
    missing = sorted(emitted - _catalog_codes())
    assert not missing, f"thiếu câu tiếng Việt trong inputMessages.ts cho: {missing}"


def test_the_catalog_has_no_dead_entries() -> None:
    known = {value for value in _string_constants(RESOLVER) if _RESOLVER_CODE.fullmatch(value)}
    known |= _emitted_probe_codes()
    dead = sorted(_catalog_codes() - known)
    assert not dead, f"mã trong danh mục không còn được backend phát ra: {dead}"
