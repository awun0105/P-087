"""Xuất bảng đánh giá thành Markdown để đưa vào báo cáo; nội dung lấy nguyên từ `JobEvaluation`."""

from src.services.orchestration.evaluation.models import JobEvaluation, StageEvaluation

_VERDICT = {"ok": "Đạt", "warn": "Cần xem", "fail": "Không đạt"}
_STATUS = {"pending": "Chưa có kết quả", "unavailable": "Không đọc được"}


def _cell(text: str) -> str:
    """Ô bảng Markdown: ký tự `|` và xuống dòng trong nội dung sẽ làm vỡ bảng."""
    return text.replace("|", "\\|").replace("\n", " ")


def _group_lines(group: StageEvaluation) -> list[str]:
    lines = [f"## {group.title}", ""]
    if group.status != "measured":
        return [*lines, f"_{_STATUS[group.status]}._ {group.note or ''}".strip(), ""]
    if group.note:
        lines += [f"_{group.note}_", ""]
    lines += ["| Chỉ số | Giá trị | Tham chiếu | Kết luận | Ý nghĩa |", "|---|---|---|---|---|"]
    for metric in group.metrics:
        verdict = _VERDICT[metric.verdict] if metric.verdict else "—"
        if metric.threshold and metric.verdict:
            verdict = f"{verdict} ({metric.threshold})"
        ref = _cell(metric.reference) if metric.reference else ""
        lines.append(
            f"| {_cell(metric.label)} | {_cell(metric.display)} | {ref} | {_cell(verdict)} | {_cell(metric.meaning)} |"
        )
    return [*lines, ""]


def evaluation_markdown(evaluation: JobEvaluation) -> str:
    """Báo cáo Markdown của một scene: phần đầu nêu phạm vi của số liệu, rồi mỗi bước một bảng."""
    lines = [
        f"# Đánh giá scene: {evaluation.scene_name}",
        "",
        f"- Job: `{evaluation.job_id}` · trạng thái {evaluation.job_status}"
        + (f" · revision `{evaluation.scene_revision}`" if evaluation.scene_revision else ""),
        f"- Tạo lúc: {evaluation.generated_at:%Y-%m-%d %H:%M} UTC",
        "- Phạm vi: chỉ số tự kiểm, đo từ chính dữ liệu của scene (không so với ground truth). Riêng mục “So với dữ "
        "liệu đối chứng” (nếu có) so với ground truth của dataset. Kết luận chỉ có ở chỉ số đã có ngưỡng trong cấu "
        "hình hoặc tài liệu của dự án; ô “—” nghĩa là chưa có ngưỡng.",
        "",
    ]
    for group in evaluation.groups:
        lines += _group_lines(group)
    return "\n".join(lines).rstrip() + "\n"
