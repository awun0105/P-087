# 0025 Imported 3DGS continuation thành editable SceneIR và simulation candidate

Date: 2026-10-07

## Status

Deferred — owner hoãn AUD-25 ngày 2026-10-07 vì độ phức tạp. Không triển khai hoặc
enable continuation trong kế hoạch hiện tại; chỉ mở lại khi owner yêu cầu.
Thiết kế bên dưới giữ làm tham khảo, không là active policy/dependency. Import/view
PLY/SOG của AUD-06/24 vẫn nằm trong scope riêng; chưa có continuation implementation.

## Context

ImportService chỉ publish SOG cho viewer, chưa nhận SOG làm input. AUD-06 mở durable
PLY/SOG view import, AUD-24 thống nhất upload/routing; AUD-25 thêm downstream
processing job từ imported visual.
Finalize/VisualResolver/objectify hiện giả định Brush preview, real camera poses/
frames và camera-derived seed/ROI. Bare Gaussian PLY/SOG không chứa toàn bộ dữ liệu này.
3DGS already represents 3D appearance; cần bổ sung metric geometry/object/physics
preparation để dùng shared editable SceneIR và simulation/export workflow.

## Decision đề xuất

1. Giữ luồng import 3DGS riêng hiện tại cho PLY/SOG. Sau READY, user chọn Xem scene
   hoặc Xử lý tiếp; không tự chạy processing sau import. Xử lý tiếp tạo durable
   job/intent linked to exact import/source/saved snapshot, có thể bấm từ card
   hoặc workspace. Không bắt mở viewer trước hoặc chạy lại frame extraction/
   COLMAP/Brush khi đã có Gaussian source. Worker verify/decode rồi vào metric/
   floor/geometry/object preparation. Preserve import và original upload lineage. Failure
   leaves original import viewer usable; do not mutate import into a fake RGB job.
2. Supported capabilities G1 bare Gaussian PLY hoặc bundled SOG, G2 verified camera/COLMAP/images,
   G3 same-scene LiDAR-assisted source; combinations use shared adapters/stages.
   Six R1–R6 video input groups remain scoped to video; these are additional import modes.
3. Publish typed import source/provenance/capability và source-aware preparation
   contract. Keep strict legacy Brush resolver; no dummy camera/frame/training refs,
   renamed artifact types, changed job IDs or bypassed checksum validators.
4. Units/scale/up/floor/ROI confirmed from declarations, measured reference or
   qualified alignment. Declared assumptions differ measured verification; unknown
   accuracy stays unknown. Apply similarity consistently to visual/Gaussian covariance/
   appearance, geometry and applicable cameras; original bytes remain immutable.
5. Reuse coarse voxel/cleanup/floor ports; geometry QA and coverage/source provenance
   required. Bare Gaussian occupancy is estimated; no universal metric/watertight/
   collision-fidelity promise. Qualified LiDAR may supply collision separately.
6. G1 geometric/manual extraction; G2 image-assisted extraction only when real
   images/poses bind correctly. Camera metadata without images is insufficient for
   existing SAM2 path. No mandatory new mesh model/retraining or fake observed views.
7. Publish editable SceneIR DRAFT using same source ownership/membership/CAS/editor
   rules, then existing supported export/validation/review/release gates. Import
   READY, processing complete and validated release remain distinct evidence states.
8. One accepted continuation counts one actor-charged manual run under AUD-22;
   child stages/retries follow same intent. Shared ownership/admission/lease/fencing
   applies source and derived targets, no implicit source ownership transfer.
   Import/view-only không spend Guest processing quota; source decode và metric/
   floor confirmation trong same waiting run không là Retry hoặc new intent.
9. UI source snapshot choice, missing capability/metric facts and truthful progress;
   COLMAP/Brush stages not executed are labeled reused/external/not-required with
   compatible DTOs, never invented success/timing. Unsupported runtime stays explicit.
10. Forward/read compatibility and all affected bundle/seed/ROI/view/export/API/UI
    consumers updated before enable. Old import/RGB checksums and lineage retained.
11. SOG-only input uses exact uploaded SOG as source of record. A qualified pinned
    decoder publishes internal Gaussian data/derived PLY with input/output hashes,
    version/field/SH/quantization provenance. Decoding does not recover precision,
    deleted splats, reduced SH or absent cameras/images. Reuse verified SOG for
    view without mandatory re-encoding; transformed delivery uses explicit profile.
    Shared format registry/typed enums and safe bounded ZIP/texture/field validators
    updated across import/resolution/worker/UI. Source index reorder requires bound
    membership identity/mapping; unqualified unbundled/LOD/model dialects stay explicit.

## Alternatives Considered

- Only add a button calling current FinalizeWorker: required Brush/camera/frame lineage absent.
- Fabricate source-camera/preview receipts: violates provenance and downstream geometry assumptions.
- Force original video/PLY for every source: unnecessarily excludes geometric/manual
  continuation and SOG-only exports.
- Run COLMAP/Brush again by default: imported visual already exists; missing original observations remain missing.
- Guarantee physical mesh from any Gaussian centers: appearance representation is insufficient evidence for universal fidelity.

## Consequences

Need source-aware contracts/adapters across reconstruction/scene/worker/Studio,
but core correction/export/validation ports reused. With bare PLY/SOG, initial automation
is geometric and requires metric/floor setup; richer real observations enable more.
Source QA limitations remain visible; this feature does not solve unobserved geometry.
SOG is supported input with lossy provenance; viewer compatibility alone does not
qualify geometry decoding or physics accuracy.
Separate import adds packaging/readability latency and retained artifact storage;
reuse source/delivery receipts and measure those costs. It gives a stable viewer
while derived processing waits/fails. Bare source may need metric/floor setup and
manual correction; missing observations and lossy export limit downstream quality.

## Follow-Up

- [AUD-25](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-25-imported-3dgs-continuation.md).
- [AUD-06 durable import](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-06-durable-import.md).
- [0024 unified upload](0024-unified-upload-and-input-resolution.md).
- [Integration map](../plans/active/2026-10-07-codegraph-audit/INTEGRATION_MAP.md).
- [SuperSplat import/export](https://developer.playcanvas.com/user-manual/supersplat/editor/import-export/)
  and [SOG specification](https://developer.playcanvas.com/user-manual/gaussian-splatting/formats/sog/).
