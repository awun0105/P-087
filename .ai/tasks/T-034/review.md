# Review T-034

Verdict (vòng 1): CHANGES REQUESTED (1 sửa) · Vòng 2: ACCEPTED

Audit: đọc trọn `lib/api/value.ts` (phần T-034), `value/ValueCard.tsx`, `value/BenchmarkPage.tsx`, `value/BenchmarkTable.tsx`,
route `app/(studio)/benchmark/page.tsx`, diff `ReviewTab.tsx`, `AppShell.tsx`, `Breadcrumbs.tsx`; đối chiếu kiểu TS với model
Pydantic `ValueScorecard`/`BenchmarkSummary` (`scorecard.py:58–150`), `compute_p2`, `level_from_checks`, `csv_document`,
`scorecard_markdown`. Chạy value-card + benchmark-page + evaluation-card: 20 PASS; `npm run typecheck` sạch.

Đã kiểm, đúng:
- Kiểu TS khớp model máy chủ (thiếu `distance_results` ở `ScorecardP2` nhưng UI không dùng, không sao).
- `p4.reasons` đúng nghĩa "điều kiện còn thiếu của bậc kế tiếp" (`level_from_checks`), thẻ chỉ liệt kê khi bậc < 4.
- Nút "Mở Benchmark" tới `/scenes/{id}?tab=studio` **có tác dụng**: `ScenePage` đọc `params.get("tab")` (dòng 271–272).
  Lệch plan (không mở thẳng panel) chấp nhận; mở thẳng panel để sau khi T-033 accepted.
- Link tải đi qua rewrite `/api/v1/:path*` của Next, cùng origin nên mang cookie phiên; máy chủ trả `Content-Disposition`.
- Bọc `EvaluationCard` trong `<details>` ở `ReviewTab` thay vì sửa `EvaluationCard`: chấp nhận.
- `ReviewTab` chỉ mount khi đang ở tab đánh giá, nên lưu ground truth ở Studio rồi sang tab này sẽ tải lại thẻ.

## Required changes

### 1. P2 hiện "khe khớp 0/0 · bỏ sót 0 · giả 0" khi chưa đo khe nào (số 0 giả, vi phạm tinh thần AC1)
Khi ground truth đã có (version > 0) nhưng **chưa có khe nào được đo**, `compute_p2` (`scorecard.py:291–322`) trả
`gaps_checked = 0` và `unavailable_reason = None`. Hai ca thật hay gặp:
- người dùng nhập đoạn thước trước, chưa thêm khe;
- đã thêm khe nhưng layout của khe chưa được gắn revision (`compute_p2` bỏ qua khe đó, dòng 307–308).

Khi đó thẻ hiện `khe khớp 0/0 · bỏ sót 0 · giả 0` với nhãn "đo, so với số thước", bảng /benchmark hiện `0/0` và `0 / 0`.
"Bỏ sót 0" đọc như "đã kiểm, không bỏ sót", trong khi chưa kiểm gì; đây đúng là tiêu chí L2. Ô tổng hợp đã xử lý đúng
(`gaps_total === 0` → "chưa đo được"), chỉ thẻ và dòng bảng sai. CSV/Markdown của máy chủ cũng ghi `0/0` nên phải sửa cả hai phía.

**Frontend `frontend/src/features/studio/value/ValueCard.tsx`:**

`p2Label` (dòng 25–27) thay bằng:
```tsx
/** P2 luôn là "đo, so với số thước": phần mô phỏng do máy đo, chỉ mốc so sánh do người nhập (không gọi là "khai báo"). */
export function p2Label(p2: ValueScorecard["p2"]): string {
  if (p2.unavailable_reason) return "chưa có";
  if (p2.gaps_checked === 0 && p2.max_distance_error_cm.value === null) return "chưa có";
  return "đo, so với số thước";
}

/** Phần khe của P2. Chưa đo khe nào thì không có số để hiện (không phải 0). */
export function p2GapText(p2: ValueScorecard["p2"]): string | null {
  if (p2.unavailable_reason || p2.gaps_checked === 0) return null;
  return `khe khớp ${p2.gaps_agree}/${p2.gaps_checked} · bỏ sót ${p2.missed_obstacles} · giả ${p2.false_obstacles}`;
}
```
Trong `P2Cell`, dòng 89–91 thay bằng:
```tsx
      <p className="text-sm font-semibold text-ink">
        {p2GapText(p2) ?? "chưa có khe kiểm nào được đo"}
      </p>
      {p2GapText(p2) === null && (
        <p className="mt-0.5 text-xs text-ink-muted">Thêm khe và gắn layout trong panel Benchmark của scene.</p>
      )}
```
(giữ nguyên dòng "sai số kích thước tối đa…" bên dưới).

**Frontend `frontend/src/features/studio/value/BenchmarkTable.tsx`:** trong `BenchmarkRow`, thêm sau dòng 50
(`const p2Unknown = …`):
```tsx
  const noGaps = p2Unknown || row.p2.gaps_checked === 0;
  const gapTitle = p2Unknown ? row.p2.unavailable_reason ?? "" : noGaps ? "chưa có khe kiểm nào được đo" : p2Label(row.p2);
```
và hai ô khe (dòng 70–75) đổi `p2Unknown` → `noGaps`, `title` ô đầu dùng `gapTitle`.

**Backend `src/services/orchestration/value/scorecard.py`** (không đụng file của T-033):
- `_agree_text` (746) và `_missed_text` (750): điều kiện `card.p2.unavailable_reason` đổi thành
  `card.p2.unavailable_reason or card.p2.gaps_checked == 0`.
- `_csv_row` (~840–841): hai ô khe dùng cùng điều kiện đó, ra `""`.
- Kèm theo (cùng commit, một dòng): `scorecard_markdown` dòng 782 cột Nguồn của P4 đang luôn ghi `đo`; đổi thành
  `{'khai báo' if card.p4.level == 4 else 'đo'}` cho khớp thẻ (report nói Markdown đã như vậy nhưng thực tế chưa).

**Test (phải đỏ trên code hiện tại):**

`frontend/tests/value-card.test.tsx`:
```tsx
  it("chưa đo khe nào thì không hiện 0/0 và bỏ sót 0", async () => {
    const card = scorecard({
      p2: { ...scorecard().p2, gaps_checked: 0, gaps_agree: 0, missed_obstacles: 0, false_obstacles: 0 },
    });
    vi.stubGlobal("fetch", vi.fn(async () => reply(card)));
    render(<ValueCard jobId="job-1" revision="rev-004" />);

    expect(await screen.findByText("chưa có khe kiểm nào được đo")).toBeInTheDocument();
    expect(screen.queryByText(/khe khớp 0\/0/)).not.toBeInTheDocument();
    expect(screen.queryByText(/bỏ sót 0/)).not.toBeInTheDocument();
    expect(p2Label({ ...card.p2, max_distance_error_cm: MISSING("chưa có đoạn đo thước") })).toBe("chưa có");
    expect(p2Label(card.p2)).toBe("đo, so với số thước"); // còn sai số kích thước đo được
  });
```
`frontend/tests/benchmark-page.test.tsx`:
```tsx
  it("scene chưa đo khe nào hiện 'chưa có' ở hai ô khe, không hiện 0/0", async () => {
    const base = row({ job_id: "job-1", scene_name: "Kho A" });
    const response: BenchmarkResponse = {
      rows: [{ ...base, p2: { ...base.p2, gaps_checked: 0, gaps_agree: 0, missed_obstacles: 0, false_obstacles: 0 } }],
      summary: SUMMARY,
    };
    vi.stubGlobal("fetch", vi.fn(async () => reply(response)));
    render(<BenchmarkPage />);

    await screen.findByRole("table");
    const cells = within(bodyRows()[0]).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells).not.toContain("0/0");
    expect(cells).not.toContain("0 / 0");
    expect(cells.filter((text) => text === "chưa có")).toHaveLength(2);
  });
```
`tests/test_orchestration/test_value_scorecard.py`:
```python
def test_no_gap_measured_yet_gives_empty_gap_cells_not_zero() -> None:
    no_gaps = P2(
        gaps_checked=0,
        gaps_agree=0,
        missed_obstacles=0,
        false_obstacles=0,
        gap_results=[],
        max_distance_error_cm=Figure(value=1.0, unit="cm", provenance="declared"),
        distance_results=[],
        key_obstacles_with_collider="1/1",
    )
    card = _card(p2=no_gaps)
    row = dict(zip(CSV_HEADER, list(csv.reader(io.StringIO(csv_document([card]).removeprefix("﻿"))))[1], strict=True))
    assert row["Khe khớp"] == "" and row["Bỏ sót / Giả"] == ""
    assert "0/0" not in scorecard_markdown(card)


def test_markdown_marks_l4_as_declared() -> None:
    card = _card()
    l4 = card.model_copy(update={"p4": P4(level=4, reasons=[])})
    line = next(item for item in scorecard_markdown(l4).splitlines() if item.startswith("| P4"))
    assert line.rstrip().endswith("| khai báo |")
```
(Nếu `P4` chưa được import trong file test thì thêm vào import từ `scorecard`.)

Lệnh kiểm:
```
cd frontend && ./node_modules/.bin/vitest run tests/value-card.test.tsx tests/benchmark-page.test.tsx tests/evaluation-card.test.tsx && npm run typecheck
cd .. && .venv/bin/pytest tests/test_orchestration/test_value_scorecard.py -q
```

## Suggestions (không bắt buộc)
- Link tải dùng `<a download>`: nếu máy chủ trả 401/404, trình duyệt vẫn lưu body lỗi JSON thành file `.csv`. Chấp nhận cho MVP;
  nếu làm thì kiểm bằng `fetch` HEAD trước, hoặc để T-035 ghi vào hướng dẫn.
- Ô "Máy" khi thiếu số đang đọc "chưa đo được (chưa có) trên GPU chưa rõ". Có thể bỏ phần "trên …" khi `value === null`.
- `ValueCard` không tự tải lại sau phiên Walk hay lô thời gian thao tác trong cùng lần mở tab; đủ cho MVP.

## Ghi chú cho T-035
- "Mở Benchmark" chưa mở thẳng panel; sau khi T-033 accepted có thể thêm `?panel=benchmark` mà `ObjectReviewView` đọc.

## Round 2 — ACCEPTED

Audit commit `b0925b96` (backend), `84a5acff` (frontend). Chạy `test_value_scorecard.py`: 34 PASS; value-card + benchmark-page +
evaluation-card: 22 PASS.

- Backend: `_no_gap_measured` dùng chung cho `_agree_text`, `_missed_text`, `_csv_row`; dòng P2 Markdown ghi "chưa có khe kiểm nào
  được đo", cột nguồn P2 là "—" khi không có cả khe lẫn sai số; cột nguồn P4 ghi "khai báo" khi L4. Bảng benchmark Markdown cũng
  ra "—" vì đi qua `_agree_text`/`_missed_text`.
- Frontend: `p2GapText`, `p2Label` và dòng bảng đúng như hướng dẫn; sai số kích thước vẫn hiện khi có đoạn thước.

Còn nhỏ, không chặn (chuyển T-035): dòng tổng hợp đầu `benchmark_markdown` (scorecard.py ~869) vẫn ghi "Khe khớp: 0/0" khi cả bộ
chưa đo khe nào; ô tổng hợp trên trang /benchmark đã ghi "chưa đo được".
