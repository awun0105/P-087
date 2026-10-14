"""Production phải sinh và dùng registry năng lực input từ bản ghi kiểm định, không từ lời khai dev-local."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = "PRODUCT_INPUT_RUNTIME_REGISTRY"


def test_the_gpu_entrypoint_qualifies_from_the_record_and_never_uses_the_dev_declaration() -> None:
    lines = (ROOT / "scripts/gpu/docker_entrypoint.sh").read_text(encoding="utf-8").splitlines()
    script = "\n".join(line for line in lines if not line.lstrip().startswith("#"))  # bỏ chú thích
    assert "scripts.gpu.qualify_input_runtimes" in script
    assert "make_input_runtime_registry" not in script
    # Sinh lỗi thì bỏ biến để luồng nhập báo thiếu bộ xử lý, không chạy với registry hỏng.
    assert f"unset {REGISTRY}" in script


def test_api_init_and_worker_share_one_registry_file_on_the_shared_volume() -> None:
    services = yaml.safe_load((ROOT / "docker-compose.gpu.yml").read_text(encoding="utf-8"))["services"]
    paths = {name: services[name]["environment"][REGISTRY] for name in ("api", "gpu-runtime-init", "gpu-worker")}
    # api thấy volume ở /app/data, worker/init ở /data: cùng một đường dẫn tương đối trên volume.
    assert {path.split("/data/", 1)[1] for path in paths.values()} == {"studio_local/input_runtime_registry.json"}
    init_command = " ".join(services["gpu-runtime-init"]["command"])
    assert "scripts.gpu.qualify_input_runtimes" in init_command
    # Registry phải có trước khi preflight và trước khi API/worker nhận job.
    assert init_command.index("qualify_input_runtimes") < init_command.index("scripts.kaggle.preflight")
    assert "gpu-runtime-init" in services["api"]["depends_on"]


def test_the_deploy_examples_enable_the_registry_for_api_and_worker() -> None:
    for name in ("api", "worker"):
        text = (ROOT / f"deploy/studio/{name}.env.example").read_text(encoding="utf-8")
        assert any(line.startswith(f"{REGISTRY}=") for line in text.splitlines()), name


def test_the_qualification_record_ships_inside_the_gpu_image() -> None:
    record = ROOT / "configs/product/input_runtime_qualification_v1.json"
    assert record.is_file()
    dockerfile = (ROOT / "Dockerfile.gpu").read_text(encoding="utf-8")
    copied = any(
        line.startswith("COPY") and ("configs" in line or ". " in line or line.rstrip().endswith(" ."))
        for line in dockerfile.splitlines()
    )
    assert copied, "Dockerfile.gpu không chép configs/ vào image nên entrypoint không tìm thấy bản ghi kiểm định"
