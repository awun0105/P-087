# Execution Plan: Đồng bộ baseline viewer và geometry

Date: 2026-09-25

## Status

Completed — documentation synchronization

## Outcome

Đồng bộ các conflict docs đã audit thành diff đã kiểm tra, sẵn sàng commit/push
`develop` và merge vào `feat/ex-rec` theo yêu cầu user. Git publication/merge
được xác nhận bằng remote refs và final handoff sau commit này. Giữ nguyên
implementation/evidence riêng của feature; không đưa code REC-03 lên develop.

## Context

- [PRD](../../PRD.md), [Architecture](../../../ARCHITECTURE.md).
- [Integration Playbook](../../execution/INTEGRATION_PLAYBOOK.md),
  [Track Guide](../../execution/TRACK_IMPLEMENTATION_GUIDE.md).
- REC-04/05/06, PRODUCT-06; audits 00, 04a, 08, 09.
- Source `supersplat-viewer` 1.35.2, commit
  `c52f5258df424635323f26aaeebe51361dc0f8e6`.

## Scope

- Docs: PlayCanvas viewer, geometry primary/fallback, metric ordering và API sample.
- Không đổi source code, shared schema, task ID/status triển khai, dữ liệu hoặc CI.
- Không push feature branch; user yêu cầu push `develop` và merge vào feature local.

## Approach

1. Fetch, kiểm tra sạch và fast-forward `develop` từ remote.
2. Đồng bộ normative sources rồi task projections/audits/onboarding liên quan.
3. Kiểm tra diff, links, các rule cũ còn sót và API source; không claim runtime mới.
4. Commit/push develop, xác nhận remote; merge vào feature và kiểm tra giữ nguyên code.

## Risks And Recovery

- REC-06 có hai thời điểm: xác nhận anchor/transform trước voxelization;
  kiểm tra đủ pose/visual/geometry sau REC-05. Không tạo dependency cycle theo task completion.
- Engine checkout beta không thay pin 2.22.4; audit splat-transform 3.6.4
  không tự chứng minh runtime target 3.6.6 đã qualification.
- Không reset/rebase/force-push; merge conflict phải inspect từng hunk.

## Progress

- [x] Bootstrap: develop = origin/develop `e9874ba`, feature `aef92ea`, worktree sạch.
- [x] Đồng bộ docs và kiểm tra.
- [x] Xác nhận remote develop vẫn ở `e9874ba`, không có thay đổi đồng thời trước commit.

## Decisions

- 2026-09-25: User yêu cầu sửa các conflict đã báo; đồng bộ theo baseline
  PlayCanvas + splat-transform đã được chọn, giữ qualification và OpenMVS fallback.
- 2026-09-25: Metric anchor thuộc REC-06; REC-05 không coi SfM unit là mét.

## Validation

- Source/API comparison: viewer 1.35.2 browser export, required settings,
  writable cameraMode, async capture, không có public pickSurface/setCameraMode.
- Inline Python kiểm tra 16 Markdown files, 169 relative links: không có broken
  link mới; code fences cân bằng, không có conflict markers.
- Targeted `rg` trên authority sources/projections đã sửa: không còn các rule
  Three.js P0/OpenMVS primary/voxel chỉ fallback được nêu trong audit.
- `git diff --check`: pass sau sửa một trailing whitespace trong audit header.
- Diff chỉ Markdown; `src/`, `tests/`, `scripts/`, `configs/` không đổi.
- `.env`, dataset và `.venv` vẫn ignored; không đưa runtime/private artifacts vào commit.
- Không chạy GPU/browser/Isaac: đây là docs synchronization, không phải runtime acceptance.

## Result

Docs đã thống nhất viewer PlayCanvas, REC-05 voxel primary/OpenMVS fallback và
REC-06 anchor prerequisite/final verification, cùng API sample đúng source.
PRD lên v1.14; không đổi shared schema, task ID hoặc task implementation status.

Smoke 65 ảnh và timeout full 954 ảnh là evidence đã có của REC-03 trên feature,
không phải runtime proof cho viewer/geometry mới. Manifest subset trong temporary
storage vẫn là follow-up của feature. Runtime target splat-transform 3.6.6 cần
qualification riêng; source audit 3.6.4 được giữ đúng provenance.

Git handoff sau commit: push develop, xác nhận remote HEAD, merge vào feat/ex-rec,
kiểm tra feature code/evidence còn nguyên và focused tests. Không push feature branch.
