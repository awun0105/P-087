# 0008 Dùng lại code nghiên cứu có giấy phép phi thương mại

Date: 2026-09-30

## Status

Accepted — owner (Quân) chốt ngày 2026-09-30.

## Context

- Nhiều repo phục vụ pipeline v2 (ADR 0007) dùng giấy phép chỉ cho phi thương mại: SuGaR và
  Frosting (Inria, non-commercial), Re3Sim (CC BY-NC 4.0), bộ rasterizer 3DGS gốc của Inria.
  Trước đây nhóm chỉ chép phương pháp, không chép code (vd. `eval/visual` không chép code SuGaR).
- AGENTS.md §8: không copy cả reference repository; chỉ `REUSE`/`ADAPT` phần task cho phép và
  giữ license/provenance.

## Decision

1. Real2Sim Studio (AI20K P-087) là **đồ án học tập, không thương mại**. Được `REUSE`/`ADAPT`
   code có giấy phép phi thương mại dùng cho nghiên cứu/giáo dục.
2. Quy tắc AGENTS.md vẫn giữ: chỉ lấy phần cần, ghi nguồn (repo, commit, đường dẫn), giấy phép
   và phần đã sửa vào `THIRD_PARTY_NOTICES.md` (hoặc notice của frontend) ngay khi đưa vào repo.
3. Nếu dự án chuyển sang dùng thương mại, mọi phần mang giấy phép phi thương mại phải được liệt
   kê lại và thay thế trước khi phát hành.

## Alternatives Considered

1. Chỉ dùng code MIT/Apache/BSD — an toàn nhất nhưng loại bỏ các phương pháp mạnh (SuGaR,
   Frosting, rasterizer Inria) và làm chậm pha chạy thử.

## Consequences

Positive:

- Pha A của ADR 0007 được dùng thẳng code Gaussian Grouping (Apache-2.0), SuGaR/Frosting,
  rasterizer Inria mà không phải viết lại.

Tradeoffs:

- Phải giữ provenance chặt; sản phẩm không dùng thương mại được khi còn phần phi thương mại.

## Follow-Up

- Mỗi lần đưa code bên thứ ba vào: cập nhật `THIRD_PARTY_NOTICES.md` trong cùng commit.
