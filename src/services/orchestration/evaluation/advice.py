"""Sinh tóm tắt và khuyến nghị theo quy tắc từ các chỉ số đánh giá."""

from src.services.orchestration.evaluation.models import Metric, StageEvaluation, Verdict

_RULES: dict[tuple[str, Verdict], str] = {
    (
        "input.warnings",
        "warn",
    ): "Video có cảnh báo chuyển động: {display}. Lần quay sau hãy di chuyển đều tay, tránh đứng yên lâu hoặc lia máy nhanh.",
    (
        "pose.registered_ratio",
        "fail",
    ): "COLMAP chỉ dựng được vị trí cho {display} ảnh, dưới ngưỡng {threshold}. Quay chậm hơn và để các khung hình liên tiếp chồng lấn nhiều hơn.",
    (
        "pose.registered_ratio",
        "warn",
    ): "COLMAP chỉ dựng được vị trí cho {display} ảnh sau khi tự thử lại: vùng thiếu ảnh có thể bị mờ hoặc thủng. Lần quay sau hãy đi chậm hơn và quay lại các chỗ đã bỏ sót.",
    (
        "visual.nonfinite_values",
        "fail",
    ): "File 3DGS có giá trị hỏng. Chạy lại bước dựng hình; không duyệt scene này.",
    (
        "metric.check_error",
        "fail",
    ): "Đoạn kiểm C–D lệch {display}, ngoài ngưỡng {threshold}. Đo lại hai đoạn A–B và C–D rồi xác nhận lại tỉ lệ.",
    (
        "metric.check_error",
        "warn",
    ): "Đoạn kiểm C–D lệch {display}, ngoài ngưỡng {threshold}. Đo lại hai đoạn A–B và C–D rồi xác nhận lại tỉ lệ.",
}


def _format_advice(metric: Metric) -> str:
    template = _RULES.get((metric.key, metric.verdict)) if metric.verdict else None
    if template is not None:
        return template.format(display=metric.display, threshold=metric.threshold or "chưa ghi ngưỡng")
    return f"{metric.label}: {metric.display} (ngưỡng: {metric.threshold or 'chưa ghi ngưỡng'})"


def summarize(groups: list[StageEvaluation]) -> list[str]:
    """Sinh danh sách khuyến nghị từ các chỉ số có verdict warn hoặc fail.

    Fail đứng trước, rồi đến warn, giữ thứ tự nhóm. Nếu không có chỉ số nào warn/fail,
    trả về đúng một câu thông báo tỷ lệ chỉ số có ngưỡng.
    """
    measured_groups = [g for g in groups if g.status == "measured"]
    total = sum(len(g.metrics) for g in measured_groups)
    n = sum(1 for g in measured_groups for m in g.metrics if m.verdict is not None)

    failed: list[str] = []
    warned: list[str] = []

    for group in groups:
        for metric in group.metrics:
            if metric.verdict == "fail":
                failed.append(_format_advice(metric))
            elif metric.verdict == "warn":
                warned.append(_format_advice(metric))

    advice = [*failed, *warned]
    if advice:
        return advice
    if n == 0:
        # Chưa chỉ số nào được so với ngưỡng (job chưa chạy xong bước nào): không có gì để kết luận.
        return []

    return [
        f"Không có chỉ số tự kiểm nào dưới ngưỡng. {n} trên {total} chỉ số có ngưỡng; các chỉ số còn lại chỉ để tham khảo."
    ]
