"""Sinh và kiểm cấu hình production của Studio từ một file gốc (`deploy/studio/production.env.example`).

    python -m scripts.studio.deploy_env check  --source /secure/production.env
    python -m scripts.studio.deploy_env render --source /secure/production.env --out-dir /secure/out
    python -m scripts.studio.deploy_env render --examples          # sinh lại ba file *.env.example trong repo

File gốc chia bốn phần `# [shared]`, `# [api]`, `# [worker]`, `# [web]`. `render` ghi phần shared vào cả api.env lẫn
worker.env nên giá trị dùng chung không thể lệch. `check` báo những cấu hình đã biết là làm deployment không chạy:
lỗi thì thoát mã 1, cảnh báo thì vẫn thoát 0. Lệnh không in giá trị của biến nào.
"""

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "deploy" / "studio" / "production.env.example"
SECTIONS = ("shared", "api", "worker", "web")
#: File sinh ra cho từng nơi triển khai và các phần của file gốc đi vào nó, theo thứ tự.
TARGETS: dict[str, tuple[str, ...]] = {"api": ("shared", "api"), "worker": ("shared", "worker"), "web": ("web",)}
_SECTION = re.compile(r"^# \[(\w+)\]\s*$")
_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")

#: Biến bắt buộc có giá trị, theo phần của file gốc.
REQUIRED: dict[str, tuple[str, ...]] = {
    "shared": (
        "APP_ENV",
        "DATABASE_URL",
        "ARTIFACT_S3_BUCKET",
        "ARTIFACT_S3_ENDPOINT",
        "ARTIFACT_S3_ACCESS_KEY_ID",
        "ARTIFACT_S3_SECRET_ACCESS_KEY",
        "PRODUCT_PRIVACY_MODE",
        "LLM_PROVIDER",
    ),
    "api": ("ARTIFACT_ROOT", "PRODUCT_PROCESSING_CONFIG"),
    "worker": (
        "ARTIFACT_ROOT",
        "PRODUCT_WORKER_ROOT",
        "PRODUCT_PROCESSING_CONFIG",
        "PRODUCT_RUNTIME_MANIFEST",
        "PRODUCT_SCENE_RUNTIME_PYTHON",
        "STUDIO_WORKERS",
    ),
    "web": ("REAL2SIM_API_URL",),
}
_LLM_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


@dataclass(frozen=True)
class Source:
    """File gốc đã tách: dòng nguyên văn và biến của từng phần."""

    lines: dict[str, list[str]]
    values: dict[str, dict[str, str]]


@dataclass(frozen=True)
class Finding:
    """Một điều `check` phát hiện. `level` là "error" hoặc "warning"."""

    level: str
    message: str


def parse(text: str) -> Source:
    """Tách file gốc theo dòng đánh dấu phần; dòng trước phần đầu tiên là lời dẫn và bị bỏ."""
    lines: dict[str, list[str]] = {name: [] for name in SECTIONS}
    values: dict[str, dict[str, str]] = {name: {} for name in SECTIONS}
    current: str | None = None
    for line in text.splitlines():
        marker = _SECTION.match(line)
        if marker:
            current = marker[1]
            if current not in lines:
                raise ValueError(f"phần không hợp lệ trong file gốc: [{current}]")
            continue
        if current is None:
            continue
        lines[current].append(line)
        assignment = _ASSIGNMENT.match(line)
        if assignment:
            if assignment[1] in values[current]:
                raise ValueError(f"biến {assignment[1]} khai báo hai lần trong phần [{current}]")
            values[current][assignment[1]] = assignment[2].strip()
    duplicated = (set(values["shared"]) & set(values["api"])) | (set(values["shared"]) & set(values["worker"]))
    if duplicated:
        raise ValueError(f"biến vừa ở [shared] vừa ở phần riêng: {sorted(duplicated)}")
    return Source(lines, values)


def render(source: Source, target: str) -> str:
    """Nội dung file môi trường của một nơi triển khai."""
    header = f"# Sinh từ file cấu hình gốc bằng scripts/studio/deploy_env.py — không sửa tay. Nơi dùng: {target}.\n"
    body = "\n\n".join("\n".join(source.lines[section]).strip("\n") for section in TARGETS[target])
    return header + "\n" + body.strip("\n") + "\n"


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def check(source: Source) -> list[Finding]:
    """Các cấu hình đã biết là làm production không chạy hoặc chạy sai."""
    shared, api, worker, web = (source.values[name] for name in SECTIONS)
    found: list[Finding] = []

    def error(message: str) -> None:
        found.append(Finding("error", message))

    def warning(message: str) -> None:
        found.append(Finding("warning", message))

    if _is_true(api.get("GPU_AUTOPROVISION_ENABLED")):
        for key in (
            "GPU_DEPLOYMENT_ID",
            "RUNPOD_API_KEY",
            "GPU_RELEASE_CATALOG",
            "PRODUCT_GPU_RELEASE_CATALOG",
            "GPU_WORKER_ENV_FILE",
            "GPU_MAX_HOURLY_USD",
            "GPU_PROJECT_BUDGET_USD",
        ):
            if not api.get(key):
                error(f"[api] {key} required for GPU provisioning")
        if api.get("GPU_MAX_PODS", "1") != "1" or worker.get("STUDIO_WORKERS") != "1":
            error("GPU deployment requires GPU_MAX_PODS=1 and STUDIO_WORKERS=1")
        if api.get("GPU_RELEASE_CATALOG") != api.get("PRODUCT_GPU_RELEASE_CATALOG"):
            error("API and controller must use the same pinned GPU release catalog")
        if not _is_true(api.get("GPU_AUTOPROVISION_DRY_RUN")):
            if api.get("GPU_OUTAGE_POLICY", "blocked") == "blocked" or not api.get("GPU_OUTAGE_POLICY_REFERENCE"):
                error("Live GPU provisioning requires an accepted outage policy reference")
    if _is_true(api.get("GPU_CPU_LANE_ENABLED")) and not api.get("GPU_CPU_LANE_QUALIFICATION_REFERENCE"):
        error("CPU lane requires GPU_CPU_LANE_QUALIFICATION_REFERENCE")

    for section, names in REQUIRED.items():
        for name in names:
            if not source.values[section].get(name):
                error(f"[{section}] {name} chưa có giá trị")

    if shared.get("APP_ENV") != "production":
        warning("[shared] APP_ENV không phải production")
    archive_key = shared.get("PRODUCT_DEMO_ARCHIVE_KEY")
    archive_checksum = shared.get("PRODUCT_DEMO_ARCHIVE_CHECKSUM")
    if bool(archive_key) != bool(archive_checksum):
        error("[shared] PRODUCT_DEMO_ARCHIVE_KEY và PRODUCT_DEMO_ARCHIVE_CHECKSUM phải khai báo cùng nhau")
    if archive_checksum and re.fullmatch(r"sha256:[a-f0-9]{64}", archive_checksum) is None:
        error("[shared] PRODUCT_DEMO_ARCHIVE_CHECKSUM phải là sha256:<64 hex>")
    if not archive_key:
        warning("[shared] chưa ghim demo archive: deployment cần provision PRODUCT_DEMO_DIR trước khi mở demo")
    if shared.get("PRODUCT_PRIVACY_MODE") == "qa_verified":
        # Chế độ này che mọi video và chờ người upload chấp nhận: thiếu bộ che thì không tạo được scene nào.
        if not source.values["worker"].get("PRODUCT_EGOBLUR_WEIGHTS"):
            error("[worker] PRODUCT_PRIVACY_MODE=qa_verified cần PRODUCT_EGOBLUR_WEIGHTS (bộ che khuôn mặt/biển số)")
        if source.values["api"].get("PRODUCT_ANONYMIZE_REMOTE_WORKER") != "true":
            error("[api] PRODUCT_PRIVACY_MODE=qa_verified cần PRODUCT_ANONYMIZE_REMOTE_WORKER=true")
    elif shared.get("PRODUCT_PRIVACY_MODE") not in {None, "", "self_attested"}:
        error("[shared] PRODUCT_PRIVACY_MODE phải là self_attested hoặc qa_verified")
    if (shared.get("DATABASE_URL") or "").startswith("sqlite"):
        error("[shared] DATABASE_URL là SQLite: API và worker ở hai máy khác nhau không dùng chung được file SQLite")
    key = _LLM_KEYS.get(shared.get("LLM_PROVIDER", ""))
    if key is None:
        error("[shared] LLM_PROVIDER không thuộc các provider được hỗ trợ")
    elif not shared.get(key):
        error(f"[shared] {key} trống: Settings từ chối khởi động khi provider đã chọn không có khóa")
    if not _is_true(shared.get("AUTH_REQUIRED")):
        error("[shared] AUTH_REQUIRED không bật: production sẽ mở cho mọi người không cần đăng nhập")
    if (shared.get("AUTH_COOKIE_SECURE") or "").strip().lower() == "false":
        error("[shared] AUTH_COOKIE_SECURE=false: cookie phiên đi qua kết nối không mã hóa")

    for section, values in (("api", api), ("worker", worker)):
        root = values.get("ARTIFACT_ROOT")
        if root and not root.startswith("/"):
            error(f"[{section}] ARTIFACT_ROOT phải là đường dẫn tuyệt đối ngoài development/test")
        # T-040: API lấy runtime từ GPU worker đã công bố, không cần chép manifest của worker lên volume.
        from_workers = section == "api" and _is_true(values.get("PRODUCT_RUNTIME_FROM_WORKERS"))
        if section == "api" and not from_workers and not values.get("PRODUCT_RUNTIME_MANIFEST"):
            error("[api] cần PRODUCT_RUNTIME_MANIFEST (ghim tay) hoặc PRODUCT_RUNTIME_FROM_WORKERS=true")
        if not from_workers and bool(values.get("PRODUCT_PROCESSING_CONFIG")) != bool(
            values.get("PRODUCT_RUNTIME_MANIFEST")
        ):
            error(f"[{section}] PRODUCT_PROCESSING_CONFIG và PRODUCT_RUNTIME_MANIFEST phải khai báo cùng nhau")

    if _is_true(shared.get("PRODUCT_OBJECTIFY")) and not _is_true(api.get("PRODUCT_OBJECTIFY_REMOTE_WORKER")):
        warning("[api] PRODUCT_OBJECTIFY_REMOTE_WORKER chưa bật: API sẽ coi như không có runtime tách vật")

    weights = bool(worker.get("PRODUCT_EGOBLUR_WEIGHTS"))
    offered = _is_true(api.get("PRODUCT_ANONYMIZE_REMOTE_WORKER"))
    if offered and not weights:
        error(
            "[api] PRODUCT_ANONYMIZE_REMOTE_WORKER=true nhưng [worker] PRODUCT_EGOBLUR_WEIGHTS trống: job chọn che sẽ "
            "lỗi ở bước tách frame"
        )
    if weights and not offered:
        warning(
            "[worker] có PRODUCT_EGOBLUR_WEIGHTS nhưng [api] chưa bật PRODUCT_ANONYMIZE_REMOTE_WORKER: UI không hiện ô chọn che"
        )
    if _is_true(shared.get("PRODUCT_ANONYMIZE_INPUT")) and not (weights and offered):
        error(
            "[shared] PRODUCT_ANONYMIZE_INPUT=true cần worker có trọng số EgoBlur và API bật PRODUCT_ANONYMIZE_REMOTE_WORKER"
        )

    workers = worker.get("STUDIO_WORKERS", "")
    if workers == "auto":
        warning(
            "[worker] STUDIO_WORKERS=auto: chế độ tự chia chỉ tính theo VRAM, cho nhiều worker hơn CPU của pod chịu được"
        )
    elif workers and not (workers.isdigit() and int(workers) >= 1):
        error("[worker] STUDIO_WORKERS phải là số nguyên dương hoặc auto")

    url = web.get("REAL2SIM_API_URL", "")
    if url:
        if not url.startswith("https://"):
            error("[web] REAL2SIM_API_URL phải là origin https công khai của API")
        if url.rstrip("/").endswith("/api/v1") or url.endswith("/"):
            error("[web] REAL2SIM_API_URL chỉ là origin: không kèm /api/v1 và không có dấu / ở cuối")
    return found


def manifest_findings(api_manifest: Path, worker_manifest: Path) -> list[Finding]:
    """Runtime manifest trên API phải là đúng file pod worker đã sinh, nếu không worker bỏ qua mọi job."""
    try:
        digests = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (api_manifest, worker_manifest)]
    except OSError as error:
        return [Finding("error", f"không đọc được runtime manifest: {type(error).__name__}")]
    if digests[0] != digests[1]:
        return [
            Finding(
                "error",
                "runtime manifest của API khác của worker: job tạo ra sẽ không được worker này nhận; chép manifest "
                "của pod lên volume API rồi khởi động lại API",
            )
        ]
    return []


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check", help="kiểm file cấu hình gốc trước khi deploy")
    check_parser.add_argument("--source", type=Path, required=True)
    check_parser.add_argument("--api-manifest", type=Path, help="runtime manifest đang nằm trên volume của API")
    check_parser.add_argument("--worker-manifest", type=Path, help="runtime manifest do pod worker sinh ra")
    render_parser = commands.add_parser("render", help="sinh api.env, worker.env, web.env")
    render_parser.add_argument("--source", type=Path)
    render_parser.add_argument("--out-dir", type=Path)
    render_parser.add_argument("--examples", action="store_true", help="sinh lại ba file *.env.example trong repo")
    args = parser.parse_args(argv)

    if args.command == "render" and args.examples:
        source = parse(EXAMPLE.read_text(encoding="utf-8"))
        for target in TARGETS:
            _write(EXAMPLE.parent / f"{target}.env.example", render(source, target))
        print(f"đã sinh {len(TARGETS)} file mẫu trong {EXAMPLE.parent.relative_to(ROOT)}")
        return 0
    if args.source is None:
        parser.error("cần --source")
    try:
        source = parse(args.source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"LỖI: {error}", file=sys.stderr)
        return 1
    findings = check(source)
    if args.command == "check" and (args.api_manifest or args.worker_manifest):
        if not (args.api_manifest and args.worker_manifest):
            parser.error("--api-manifest và --worker-manifest phải đi cùng nhau")
        findings += manifest_findings(args.api_manifest, args.worker_manifest)
    for finding in findings:
        print(("LỖI: " if finding.level == "error" else "CẢNH BÁO: ") + finding.message)
    errors = sum(finding.level == "error" for finding in findings)
    if args.command == "check":
        print(f"{errors} lỗi, {len(findings) - errors} cảnh báo")
        return 1 if errors else 0
    if errors:
        print("Không sinh file: sửa các lỗi trên trước.", file=sys.stderr)
        return 1
    if args.out_dir is None:
        parser.error("cần --out-dir")
    if ROOT in args.out_dir.resolve().parents or args.out_dir.resolve() == ROOT:
        print("LỖI: --out-dir nằm trong repo; file sinh ra chứa secret, hãy ghi ra ngoài repo", file=sys.stderr)
        return 1
    for target in TARGETS:
        _write(args.out_dir / f"{target}.env", render(source, target))
    print(f"đã sinh {', '.join(f'{target}.env' for target in TARGETS)} trong {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
