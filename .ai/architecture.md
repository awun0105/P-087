# Kiến trúc: Duyệt tách vật bằng Box + vỏ phát sáng, collider từ vỏ Gaussian

Branch: `mvp-pipeline-v2`. Không tạo branch mới, không push/merge/PR.

## 1. Bối cảnh: vì sao đổi

Pipeline hiện tại (stage `OBJECT_EXTRACT`, hàm `objectify()` trong
`src/services/orchestration/scene/objectify.py`) chạy liền một mạch:

```
SAM2 + multiview → membership Gaussian → train ObjectGS (hàng giờ GPU) → TSDF mesh
→ cleanup/repair/QA → CoACD → collision môi trường → publish SceneIR
```

Người dùng chỉ thấy kết quả tách **sau khi** đã train xong. Sửa membership phải train lại
(`membership_regeneration.py`). Ngoài ra mesh TSDF từ ObjectGS hay bị **hở** ở mặt camera không
thấy (đáy, mặt sát tường): Room 8.000 vòng có 275 cạnh biên nên quality gate chặn, vật không có collider.

## 2. Mục tiêu

1. Tách bước rẻ (tách vật) khỏi bước đắt (tạo hình học). Giữa hai bước là **điểm dừng duyệt**.
2. Người dùng chỉnh vùng vật bằng **box chữ nhật** (cộng/trừ), thấy ngay **vỏ phát sáng** ôm sát
   Gaussian thuộc vật. Mỗi lần chỉnh chỉ tốn vài giây, không dùng GPU nặng.
3. Collider mặc định dựng từ **vỏ Gaussian kín** (luôn watertight theo cấu tạo) → QA → CoACD.
   ObjectGS trở thành tùy chọn nâng cấp theo từng vật, có quy tắc chọn rõ ràng.
4. Visual Gaussian, collider vật, collision môi trường, SceneIR, Walk và USD luôn cùng một revision.

## 3. Non-goals

- Không viết lại COLMAP, Brush, SAM2, ObjectGS, CoACD, physics engine.
- Không làm mesh editor tự do (kéo từng đỉnh vỏ). Box là công cụ duy nhất để chỉnh vùng.
- Không bỏ quality gate; không fallback âm thầm sang OBB/hull rồi báo thành công.
- Không hardcode theo scene Room. Không chạy train scene mới trong sprint này.
- Không làm chế độ hai camera cho COLMAP.

## 4. Thuật ngữ

| Từ | Nghĩa |
| --- | --- |
| Source row | Một hàng Gaussian trong PLY nguồn bất biến (`membership.source_visual_ref`). Ownership luôn tính trên source row, **không** trên pose đã Move. |
| Membership | Mảng nhãn int32 mỗi source row → nhãn vật (`-1` = nền). `ObjectMembershipArtifact`. |
| Region box | Hộp chữ nhật có hướng (OBB, chỉ xoay quanh trục Z), `op = add | subtract`, toạ độ **object-local**. |
| Vỏ (shell) | Mesh kín dựng từ occupancy voxel của Gaussian thuộc vật. Bản thô (preview, 0.05 m) và bản mịn (collider, 0.02 m). |
| Draft scene | SceneIR sau tách vật, `provenance.object_geometry = "awaiting_review"`, vật chưa có collider. |
| Geometry build | Bước tạo hình học chạy một lần khi người dùng bấm "Tạo mesh". |

## 5. Luồng mới

```
REC: COLMAP + Brush → xác nhận mét → bundle
OBJECT_EXTRACT (rẻ): SAM2 + multiview_v1 → membership → Gaussian từng vật → vỏ thô
   → publish Draft SceneIR (object_geometry = awaiting_review, collider = null)
⏸ Studio: duyệt. Box cộng/trừ → preview (vỏ phát sáng + Gaussian thêm/bớt) → Apply
   Apply = revision mới, đồng bộ, vài giây, KHÔNG train
"Tạo mesh" → hàng đợi objectify mode "geometry" (có lease/cancel/revision fence):
   vỏ mịn → QA → CoACD → (tuỳ chọn ObjectGS: dùng surface nếu QA pass, ngược lại giữ vỏ + ghi lý do)
   → collision môi trường object-aware → publish SceneIR (object_geometry = ready)
Studio: Confirm/Ignore/Hide/Move/Rotate/Delete/Restore → Walk → USD
Sửa vùng sau khi đã ready → rebuild chỉ các vật bị ảnh hưởng (không retrain cả scene)
```

`scene.geometry_review` (preset param): `required` (mặc định) dừng ở Draft; `auto` chạy build
ngay sau tách vật (cho batch). Người dùng chọn ở màn tạo job (T-020). Job cũ không có khóa này → hành vi cũ (`legacy`).

## 6. Mô-đun và trách nhiệm

| Mô-đun | Vai trò | Trạng thái |
| --- | --- | --- |
| `src/services/scene/object_aware_geometry.py` | Occupancy → mesh mặt voxel lộ ra; collision nền | Có. T-001 tách hàm `occupancy_surface()` dùng chung |
| `src/services/scene/gaussian_shell.py` | Dựng vỏ kín từ Gaussian của một vật | **Mới** (T-002) |
| `src/services/scene/surface_mesh.py` | `assess_surface` QA | Có, tái dùng |
| `src/services/scene/editing/region_box.py` | Box → mask source row; preview diff | **Mới** (T-004) |
| `src/models/contracts/object_geometry.py` | `ObjectSurfaceManifest`, thêm `ObjectShellManifest` | Sửa (T-003) |
| `src/models/contracts/object_membership.py` | Thêm `ObjectRegionCommand` | Sửa (T-004) |
| `src/services/orchestration/scene/objectify.py` | Tách vật; thêm nhánh Draft; tách helper dùng chung | Sửa (T-005, T-006) |
| `src/services/orchestration/scene/object_geometry_build.py` | Build hình học từ Draft / rebuild vật bị ảnh hưởng | **Mới** (T-007, T-008, T-011) |
| `src/services/orchestration/scene/objectify_queue.py` | Thêm mode `geometry` | Sửa (T-009) |
| `src/services/orchestration/scene/object_region.py` | Preview/apply region trên Draft | **Mới** (T-010) |
| `src/api/product/scene.py` | Route region/geometry | Sửa (T-009, T-010) |
| `src/services/simulation/colliders/convex_runner.py` | CoACD, nhận `surface_mesh` | Có, tái dùng |
| `frontend/src/features/studio/region/*` | Box model, overlay, panel, vỏ phát sáng | **Mới** (T-014..T-017) |
| `frontend/src/features/viewer/scene-overlay.ts` | Thêm lớp region box + shell | Sửa (T-015, T-017) |

## 7. Data model và contract

### 7.1 SceneIR

- `provenance.object_geometry`: `"awaiting_review" | "ready"`. Thiếu khóa = scene cũ, coi như `ready`.
- `provenance.geometry_method`: `"legacy" | "shell" | "objectgs"`.
- Draft: mỗi vật có `visual_ref` (Gaussian của vật), `geometry_ref` = vỏ thô (`ObjectShellMesh`),
  `collider = null`, `provenance.source_transform` = Transform lúc tách (world ← object).
  **Quy tắc khung:** PLY Gaussian của vật (`visual_ref`) và mọi mesh vỏ/collider ở object-local **theo `source_transform`**.
  `source_transform` không bao giờ đổi sau khi tách, kể cả khi chỉnh vùng làm tâm nhóm Gaussian thay đổi: hàng mới được đổi
  sang local bằng `Rᵀ(p_world − t)` của `source_transform`, không căn tâm lại. (`gaussian_split.split()` đã trả hàng local
  theo tâm AABB lúc tách, trùng `source_transform` của Draft.)
  `environment.membership` có; `environment.object_aware_collision_ref = null`.
  Môi trường Draft = `visual_ref` 3DGS đầy đủ của bundle (chưa vá nền). Vì Move bị khoá trong Draft,
  Studio **không** vẽ thêm Gaussian của vật (tránh vẽ chồng hai lần), chỉ vẽ vỏ. Vá nền (inpaint) + nén SOG
  nền chạy ở bước build vì phụ thuộc membership cuối cùng.
- Ready: `geometry_ref` = GLB collider CoACD, `surface_mesh_ref` = vỏ mịn hoặc surface ObjectGS,
  `collider.type = CONVEX_DECOMPOSITION`, môi trường có `object_aware_collision_ref`.

### 7.2 Artifact mới

- `ObjectShellMesh` (GLB, object-local, mét).
- `ObjectShellManifest`: object_id, `shell_mesh_ref`, `source_membership`, `voxel_m`,
  `params` (opacity_min, outlier_k, outlier_std, close_iterations), `statistics`, `quality` (kết quả
  `assess_surface`), `provenance.surface_origin = "gaussian_shell_v1"`,
  `inferred_regions = "unobserved faces closed by occupancy fill"`.

### 7.3 Region command (API)

```jsonc
// POST /api/v1/jobs/{job_id}/scene/objects/{object_id}/region/preview  (không đổi gì)
// POST /api/v1/jobs/{job_id}/scene/objects/{object_id}/region/apply    (Draft: revision mới đồng bộ;
//                                                                        Ready: 202 + enqueue rebuild)
{
  "expected_scene_revision": "rev-007",
  "membership_checksum": "sha256:…",
  "boxes": [
    {"op": "add", "center_m": [0.0, 0.0, 0.45], "half_extents_m": [0.3, 0.3, 0.45], "yaw_rad": 0.0},
    {"op": "subtract", "center_m": [0.0, 0.0, 0.2], "half_extents_m": [0.25, 0.25, 0.2], "yaw_rad": 0.0}
  ],
  "claim_from": []          // id vật khác được phép lấy Gaussian; mặc định không lấy
}
```

Quy tắc tính (server, toạ độ source world):
`inside = ∪(add) \ ∪(subtract)`.
`eligible = nền không thuộc sàn ∪ hàng của chính vật ∪ hàng của vật trong claim_from`.
`mới = inside ∩ eligible`. Hàng cũ của vật nằm ngoài `inside` → về nền (`-1`).
Yaw là góc quay phải quanh +Z: trục x của box = (cos yaw, sin yaw, 0), trục y = (−sin yaw, cos yaw, 0).
Điểm trên mặt box (dung sai 1e-6 m) tính là bên trong. Client và server dùng chung file ca kiểm
`tests/fixtures/region_box_cases.json` (T-004 tạo) để chắc hai phía cho cùng kết quả.
Toạ độ box là object-local; server đổi sang source world bằng `provenance.source_transform` của vật
(**không** dùng `transform` hiện tại, vì vật có thể đã Move).

Preview trả: `added_count`, `removed_count`, `object_gaussian_count`, `protected_floor_count`,
`overlaps: {object_id: count}`, `added_sample_m`, `removed_sample_m` (tối đa 20.000 điểm mỗi loại,
toạ độ object-local), `shell_glb_base64` (vỏ thô của kết quả).

Ràng buộc: tối thiểu 1 box `add`, tối đa 16 box, `half_extents_m` trong khoảng đóng [0.005, 20] m, kết quả ≥ 50
Gaussian (dưới mức đó → 422, gợi ý dùng Delete).

### 7.4 Geometry build

- `POST /api/v1/jobs/{job_id}/scene/geometry/build` body `{expected_scene_revision}` → 202 `ObjectifyState`
  (`mode = "geometry"`). Hủy: route `objectify/cancel` có sẵn kèm `operation_id`.
- Phase tiến độ: `shell` → `quality` → `objectgs` (nếu có) → `collider` → `environment` → `publish`. ObjectGS chạy trước
  collider vì surface được chọn theo vật quyết định đầu vào CoACD.
- Dựng lại một phần (`object_ids`, sửa vùng sau Ready) **không** chạy ObjectGS kể cả khi `geometry_method=objectgs`; vật bị
  ảnh hưởng dùng vỏ với `reason = "partial_rebuild_uses_shell"` (review T-008).

## 8. Quy tắc hình học (bắt buộc)

1. Vỏ: lọc opacity (sigmoid(logit) ≥ 0.1), lọc điểm lẻ (k=8 láng giềng, loại > mean + 2·std),
   voxel hoá (voxel thích ứng: `max(voxel_m, cạnh dài nhất / 96)`), giãn 1 voxel, `binary_closing`, `binary_fill_holes`, vá tiếp xúc chéo để mesh
   2-manifold, phát mặt voxel lộ ra bằng `occupancy_surface()`, rồi Taubin smoothing (giữ topology).
   Mặt camera không thấy (đáy sát sàn, mặt sát tường) **không** được lấp tự động: vỏ khi đó rỗng phía mặt đó nhưng vẫn kín,
   và tương đương khối đặc về va chạm vì không vật nào đi vào được. Luật lấp tự động đã thử ở T-002 và bị loại (lấp nhầm hoặc
   rò). Ghi `solidity = V(vỏ)/V(bao lồi)` để truy vết, không chặn.
   Vỏ rỗng làm thể tích vỏ nhỏ hơn thật và tỉ lệ phụ thuộc kích thước (đo ở T-002: hộp 0,4×0,6×0,8 m còn ~58%,
   vật 2 m chỉ ~29%). **Không** suy khối lượng/quán tính từ thể tích vỏ; khối lượng lấy theo nhãn vật như hiện tại.
2. Vỏ phải qua `assess_surface`. Không qua → lỗi rõ ràng, **không** thay bằng OBB.
3. Vỏ nhiều thành phần rời: giữ tất cả thành phần ≥ 5% tổng voxel, ghi số thành phần vào report.
   CoACD chạy riêng từng thành phần (hành vi hiện có của convex runner).
4. ObjectGS (khi `geometry_method = objectgs`): mỗi vật, nếu surface ObjectGS qua QA → dùng nó;
   không qua → dùng vỏ và ghi `surface_selection = {"chosen": "gaussian_shell", "reason": …}`.
   Đây là quy tắc được công bố, hiển thị trong Studio, không phải fallback âm thầm.
5. Collision môi trường: `build_background_collision` loại toàn bộ nhãn vật trước khi dựng mesh,
   kèm support sàn suy ra dưới dấu chân vật (đã có). Không carve tam giác sau.

## 9. UI/UX

### Màn duyệt (Draft)

- Banner trên viewport: "Đang duyệt tách vật · N vật · chưa có collider" và nút chính **Tạo mesh**.
  Walk, xuất USD, Move/Rotate bị khoá, kèm tooltip "Cần tạo mesh trước".
- Chọn vật → nút **Chỉnh vùng** → mở Region Editor ngay trong viewport Studio (không mở iframe).

### Region Editor

- Box chính tự khớp theo kích thước nhóm Gaussian hiện tại. Không kẹp sàn phía client: server luôn bảo vệ hàng sàn và báo
  `protected_floor_count`, nên box chìm dưới sàn không lấy thêm gì (review T-016).
- Tay nắm: 6 mặt (kéo một mặt, mặt đối diện đứng yên), vòng xoay quanh Z, kéo tâm (translate).
- Nút: `+ Box cộng`, `− Box trừ`, `Xoá box`, góc nhìn `Trên / Trước / Cạnh`, `Đặt lại`.
- Vỏ phát sáng (emissive, hơi trong suốt) cập nhật sau mỗi lần thả tay nắm (debounce 250 ms).
  Điểm xanh = Gaussian thêm, điểm đỏ = bị loại. Bộ đếm `+a / −b · tổng n`.
- Chồng lấn: "Box chồng lên Bàn 2 (1.204 Gaussian) — giữ nguyên chủ cũ" + checkbox "Lấy luôn".
- **Apply** (bị vô hiệu khi preview đang chạy, đã lỗi, hoặc preview không khớp box hiện tại), **Huỷ**.
- Trạng thái: đang tính preview (spinner nhỏ ở bộ đếm), lỗi (thông báo đỏ, giữ box), xung đột
  revision (409 → "Scene đã đổi, tải lại").

### Build

- `ObjectifyNotice` hiện phase build, nút Huỷ. Lỗi → "Scene duyệt vẫn được giữ, sửa rồi thử lại".
- Ready: panel vật hiện nguồn collider ("Vỏ Gaussian" / "ObjectGS") và lý do chọn.

## 10. Bảo mật

- Route mới dùng `require_contributor` + `authorize_job_mutation`, khai báo trong
  `tests/test_api/test_role_matrix.py`.
- Validate box bằng Pydantic (số hữu hạn, giới hạn kích thước/số lượng) trước khi tính.
- Preview không ghi artifact. Apply/Build kiểm `expected_scene_revision` và `membership_checksum`.

## 11. Hiệu năng

- Preview mục tiêu < 1,5 s với 2 triệu Gaussian: cache `positions` + `labels` theo
  `(job_id, membership_checksum)` trong process (LRU 2 mục), box test vector hoá numpy, vỏ thô 0,05 m.
- Vỏ mịn 0,02 m; giới hạn lưới 32M ô (cùng ngân sách với `build_background_collision`).

## 12. Chiến lược kiểm thử

- Unit backend: pytest cho từng hàm thuần (shell, region box, contract).
- Integration backend: luồng Draft → apply → build → SceneIR, CoACD thật nếu runtime có (skip rõ ràng nếu không).
- Frontend: vitest cho box math, panel, overlay (mock PlayCanvas như test hiện có).
- **Mỗi task chỉ chạy test liên quan + ruff/eslint file đã sửa + typecheck nếu sửa TS.
  Không chạy full suite trong task.** Full regression chỉ ở T-018.

## 13. Quy ước làm việc cho coding agent

- Commit sau **mỗi** thay đổi nhỏ đã qua test liên quan. Stage đúng đường dẫn (cây có agent khác cùng sửa).
- Commit message tiếng Anh, mô tả hành vi. **Không** thêm `Co-Authored-By` hay "Generated with".
- Sau khi sửa code chạy `graphify update .`.
- Dọn file tạm ngay sau khi dùng.

## 14. Câu hỏi mở cho chủ dự án

1. Ngưỡng opacity 0.1 và voxel 0.02 m cho vỏ mịn: giá trị khởi đầu, cần chỉnh trên scene thật.
2. ~~Chế độ `auto` trong UI tạo job?~~ Đã chốt: **có**, radio riêng ngoài mục nâng cao (T-020).

## 15. Hệ thống ghi và xuất metric giá trị (Sprint 6)

### 15.1 Mục tiêu
Sản phẩm tự ghi đủ dữ liệu để xuất **bảng 5 metric** của Benchmark Playbook (https://claude.ai/artifact/HxAyREwmuoxmXFXdTcsNuN),
cho từng scene và cho cả bộ benchmark, không cần bấm giờ hay ghi tay ngoài các số đo thước (ground truth):

| Metric | Nguồn dữ liệu |
| --- | --- |
| **Chính:** phút công người · phút máy trên [GPU, VRAM, CPU, RAM] · chi phí | `operator_time` (trình duyệt) · `ResourceUsage` của job **và** của hàng đợi tách vật · `MachineCapability` · `Settings.benchmark_gpu_hourly_usd` |
| Số lần can thiệp | `scene_edit` (mỗi `publish_next`, phân loại người/hệ thống) |
| **P2:** khớp khe hẹp, bỏ sót / giả, sai số kích thước, vật cản chính có collider | Ground truth + máy đo khe trên collision tổng hợp |
| **P3:** phút đổi bố trí → thử lại, nhất quán sau khi dời | `scene_edit` + `walk_session` + layout A/B trong ground truth + kiểm nhất quán |
| **P4:** bậc sẵn sàng L1–L4 | Trạng thái scene, xác nhận mét, gói mô phỏng, lần chạy validation Isaac, khai báo L4 |

Non-goals: không theo dõi người dùng ngoài Studio của job; không gửi dữ liệu ra ngoài; không chấm điểm cá nhân.

### 15.2 Thành phần
- **Nhật ký sự kiện** `r2s_value_events` (append-only): `event_id, job_id, at, kind, actor_id, payload`.
  `kind ∈ {scene_edit, operator_time, walk_session}`. Ghi lỗi nhật ký **không bao giờ** làm hỏng thao tác chính (log + bỏ qua).
- **Đo máy cho hàng đợi tách vật**: mọi mode của `objectify_queue` chạy trong `sampled_section` và ghi `ResourceUsage` với tool
  `scene.<mode>` (vd. `scene.geometry`), cùng `attempt_id` = `operation_id`. `processing_seconds` cộng cả các bản ghi này.
- **Ground truth** `r2s_benchmark_truth` (một tài liệu có phiên bản mỗi job, CAS theo `version`): hồ sơ robot, đoạn đo thước,
  khe kiểm, vật cản chính, layout A/B → revision, mốc làm tay, khai báo L4, cờ đưa vào benchmark.
- **Máy đo** `value_measure.py`: sai số đoạn đo; bề rộng khe trên collision tổng hợp của một revision (môi trường hiệu lực +
  collider vật theo transform); nhất quán sau khi dời. Thuần tính toán, có test số học.
- **Bảng metric** `value_scorecard.py`: gom mọi nguồn thành `ValueScorecard` + xuất JSON / CSV / Markdown, cho một job và cho
  bộ benchmark (mọi job có `include_in_benchmark`).
- **Frontend**: bộ đếm phút công người, sự kiện Walk, panel "Benchmark" trong Studio để nhập ground truth, thẻ "Giá trị" ở đầu
  tab đánh giá, trang `/benchmark` liệt kê và xuất bảng.

### 15.3 Quy tắc đo (bắt buộc)
1. **Phút công người**: chỉ tính khi trang scene của job đang mở, tab hiển thị, và có thao tác (pointer/keyboard/wheel) trong
   60 s gần nhất. Gửi theo lô ≤ 300 s mỗi lần; máy chủ từ chối lô có `active_seconds > ended_at − started_at`, thời điểm tương
   lai, hoặc chồng lô trước của cùng phiên trình duyệt (`session_key`). Tách theo `surface ∈ {studio, progress, evaluation, other}`
   và theo giai đoạn: trước/sau lần đầu scene đạt `object_geometry = ready`.
2. **Can thiệp**: `scene_edit` có `origin = human` khi `operation` thuộc bảng thao tác người dùng (`HUMAN_OPERATIONS`), `system`
   khi thuộc `SYSTEM_OPERATIONS`; operation lạ → `unknown` và có test bắt buộc mọi chuỗi operation trong `src/` đã được phân loại.
3. **Khe kiểm**: điểm `a`, `b` ở khung canonical (mét, Z-up, sàn z = 0). Bề rộng mô phỏng = nhỏ nhất theo các độ cao
   `z ∈ [h_min, h_max]` bước 0,05 m của tổng khoảng cách tia ngang từ trung điểm `a–b` theo hai hướng `±(b−a)` tới va chạm đầu
   tiên, chặn trên ở `|b−a|/2` mỗi phía. Qua được ⇔ bề rộng ≥ `robot.width + 2·robot.safety_margin`.
   Bỏ sót vật cản = thật không qua mà mô phỏng qua; vật cản giả = thật qua mà mô phỏng không qua.
4. **Nhất quán sau khi dời** (layout B so với A): với mỗi vật có transform khác nhau giữa hai revision: (a) trong hộp bao của vật
   tại pose A (thu 2 cm mỗi mặt, z trong dải robot) collision tổng hợp của B **không còn** tam giác; (b) tại pose B collider của
   vật có mặt. Đạt khi mọi vật dời đều đạt.
5. **Bậc sẵn sàng**: L1 = đã xác nhận mét và `object_geometry` ready (hoặc scene cũ không có khoá); L2 = L1 + mọi vật cản chính
   có collider + có ≥ 1 `walk_session` hoàn tất trên revision + khe kiểm của layout A không có bỏ sót; L3 = L2 + có gói mô phỏng
   cho revision hiện tại + có lần validation Isaac `COMPLETED` cho gói đó; L4 = L3 + khai báo tay bài thử robot A và B (ghi rõ
   "khai báo", kèm ghi chú bằng chứng).
6. Mọi số trong bảng ghi rõ nguồn: `measured` (máy đo), `declared` (người nhập), `unavailable` (thiếu dữ liệu, không đoán).
