"""Cấu hình production sinh từ một file gốc: ba file mẫu không được lệch, và `check` bắt các cấu hình không chạy."""

from pathlib import Path

import pytest

from scripts.studio.deploy_env import EXAMPLE, TARGETS, check, main, manifest_findings, parse, render

FILLED = {
    "DATABASE_URL=": "DATABASE_URL=postgresql://user:secret@db.example:5432/postgres?sslmode=require",
    "ARTIFACT_S3_BUCKET=": "ARTIFACT_S3_BUCKET=studio",
    "ARTIFACT_S3_ENDPOINT=": "ARTIFACT_S3_ENDPOINT=https://account.r2.cloudflarestorage.com",
    "ARTIFACT_S3_ACCESS_KEY_ID=": "ARTIFACT_S3_ACCESS_KEY_ID=key",
    "ARTIFACT_S3_SECRET_ACCESS_KEY=": "ARTIFACT_S3_SECRET_ACCESS_KEY=secret",
    "REAL2SIM_API_URL=": "REAL2SIM_API_URL=https://api.example.com",
    "OPENAI_API_KEY=": "OPENAI_API_KEY=operator-key",
}


def _filled(**changes: str) -> str:
    text = EXAMPLE.read_text(encoding="utf-8")
    for empty, value in FILLED.items():
        assert f"\n{empty}\n" in text, empty
        text = text.replace(f"\n{empty}\n", f"\n{value}\n")
    for before, after in changes.items():
        assert before in text, before
        text = text.replace(before, after)
    return text


def _messages(text: str, level: str) -> list[str]:
    return [finding.message for finding in check(parse(text)) if finding.level == level]


def test_committed_examples_are_exactly_what_the_source_renders() -> None:
    source = parse(EXAMPLE.read_text(encoding="utf-8"))
    for target in TARGETS:
        committed = (EXAMPLE.parent / f"{target}.env.example").read_text(encoding="utf-8")
        assert committed == render(source, target), (
            f"chạy `deploy_env render --examples` để sinh lại {target}.env.example"
        )


def test_shared_values_reach_api_and_worker_identically_and_never_the_web() -> None:
    source = parse(_filled())
    api, worker, web = (parse("# [shared]\n" + render(source, target)).values["shared"] for target in TARGETS)
    for name, value in source.values["shared"].items():
        assert api[name] == worker[name] == value, name
    assert api["ARTIFACT_ROOT"] != worker["ARTIFACT_ROOT"]
    assert set(web) == {"REAL2SIM_API_URL"}, "frontend không được nhận DATABASE_URL hay khóa R2"


def test_filled_template_passes_and_unfilled_template_lists_what_is_missing() -> None:
    assert _messages(_filled(), "error") == []
    missing = _messages(EXAMPLE.read_text(encoding="utf-8"), "error")
    # Mỗi giá trị để trống trong file mẫu đều bị báo; khóa LLM không có mặc định ngầm.
    assert len(missing) == len(FILLED)
    assert not any("PRODUCT_PRIVACY_MODE" in message for message in missing), "file mẫu đã có chế độ mặc định"
    assert any("OPENAI_API_KEY trống" in message for message in missing)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"PRODUCT_PRIVACY_MODE=self_attested": "PRODUCT_PRIVACY_MODE=qa_verified"}, "qa_verified"),
        (
            {
                "DATABASE_URL=postgresql://user:secret@db.example:5432/postgres?sslmode=require": "DATABASE_URL=sqlite:////data/x.db"
            },
            "SQLite",
        ),
        ({"AUTH_REQUIRED=true": "AUTH_REQUIRED=false"}, "AUTH_REQUIRED"),
        ({"OPENAI_API_KEY=operator-key": "OPENAI_API_KEY="}, "OPENAI_API_KEY trống"),
        ({"ARTIFACT_ROOT=/data/artifacts": "ARTIFACT_ROOT=./data/artifacts"}, "[worker] ARTIFACT_ROOT"),
        (
            {"PRODUCT_RUNTIME_MANIFEST=/app/data/studio_local/runtime_manifest.json": "# no manifest"},
            "[api] PRODUCT_RUNTIME_MANIFEST",
        ),
        (
            {"PRODUCT_ANONYMIZE_REMOTE_WORKER=false": "PRODUCT_ANONYMIZE_REMOTE_WORKER=true"},
            "PRODUCT_EGOBLUR_WEIGHTS trống",
        ),
        ({"PRODUCT_ANONYMIZE_INPUT=false": "PRODUCT_ANONYMIZE_INPUT=true"}, "PRODUCT_ANONYMIZE_INPUT=true cần"),
        ({"STUDIO_WORKERS=3": "STUDIO_WORKERS=many"}, "STUDIO_WORKERS"),
        ({"REAL2SIM_API_URL=https://api.example.com": "REAL2SIM_API_URL=https://api.example.com/api/v1"}, "/api/v1"),
        ({"REAL2SIM_API_URL=https://api.example.com": "REAL2SIM_API_URL=http://api.example.com"}, "https"),
    ],
)
def test_check_rejects_known_broken_configurations(changes: dict[str, str], expected: str) -> None:
    errors = _messages(_filled(**changes), "error")
    assert any(expected in message for message in errors), errors


def test_anonymizer_wiring_between_api_and_worker() -> None:
    weights = {"# PRODUCT_EGOBLUR_WEIGHTS=/data/egoblur": "PRODUCT_EGOBLUR_WEIGHTS=/data/egoblur"}
    assert any("UI không hiện ô chọn che" in m for m in _messages(_filled(**weights), "warning"))
    both = {**weights, "PRODUCT_ANONYMIZE_REMOTE_WORKER=false": "PRODUCT_ANONYMIZE_REMOTE_WORKER=true"}
    assert _messages(_filled(**both), "error") == [] and _messages(_filled(**both), "warning") == []
    enforced = {**both, "PRODUCT_ANONYMIZE_INPUT=false": "PRODUCT_ANONYMIZE_INPUT=true"}
    assert _messages(_filled(**enforced), "error") == []


def test_source_rejects_a_variable_declared_in_shared_and_in_a_target() -> None:
    with pytest.raises(ValueError, match="vừa ở"):
        parse(_filled() + "\n# [worker]\nDATABASE_URL=other\n")
    with pytest.raises(ValueError, match="hai lần"):
        parse("# [api]\nLOG_LEVEL=INFO\nLOG_LEVEL=DEBUG\n")


def test_runtime_manifest_mismatch_is_an_error(tmp_path: Path) -> None:
    api, worker = tmp_path / "api.json", tmp_path / "worker.json"
    api.write_text('{"gpu": "RTX 3090"}')
    worker.write_text('{"gpu": "RTX 3090"}')
    assert manifest_findings(api, worker) == []
    worker.write_text('{"gpu": "RTX 4090"}')
    assert [finding.level for finding in manifest_findings(api, worker)] == ["error"]
    assert [finding.level for finding in manifest_findings(api, tmp_path / "missing.json")] == ["error"]


def test_cli_renders_outside_the_repo_and_refuses_inside_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "production.env"
    source.write_text(_filled(), encoding="utf-8")
    assert main(["check", "--source", str(source)]) == 0
    assert main(["render", "--source", str(source), "--out-dir", str(tmp_path / "out")]) == 0
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == ["api.env", "web.env", "worker.env"]
    assert "secret" not in capsys.readouterr().out, "lệnh không được in giá trị của biến"
    assert main(["render", "--source", str(source), "--out-dir", str(EXAMPLE.parent / "generated")]) == 1
    assert not (EXAMPLE.parent / "generated").exists()
    source.write_text(
        _filled(**{"PRODUCT_PRIVACY_MODE=self_attested": "PRODUCT_PRIVACY_MODE=qa_verified"}), encoding="utf-8"
    )
    assert main(["check", "--source", str(source)]) == 1
    assert main(["render", "--source", str(source), "--out-dir", str(tmp_path / "blocked")]) == 1
    assert not (tmp_path / "blocked").exists()
