# PRODUCT-06 — SceneIR 3D Viewer

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | Cường |
| Target milestone | `M1/M2` |

## 2. Goal

Load SceneIR và render real 3DGS từ `VisualArtifact` của Primary RGB Scene cùng
các view Geometry mesh, Point Cloud, Collider/SceneObject transforms trong browser.
Cho phép click chuyển view/bật lớp trên cùng revision, orbit/pan/zoom, select,
hide/show và transform-edit command flow.

## 3. Why This Task Exists

Web Studio cần inspection/editing trực tiếp mà không cần Blender hoặc Isaac GUI.
3DGS Visual là view P0 phải dùng output EX-REC thật; mesh, point cloud và
collider là view kỹ thuật ngang hàng, không phải fallback hoặc bằng chứng 3DGS.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-05 Web shell.
- SceneIR fixture and PRODUCT-04 artifact resolver.
- Real-browser AC-11 proof cần REC-04 publish real Brush `VisualArtifact`; fixture vẫn cho phép phát triển độc lập trước khi EX-REC hoàn tất.

## 5. Input Contract

- SceneIR, real EX-REC `VisualArtifact` (format/producer/version/checksum/coordinate metadata), resolved geometry/collider refs and edit API.
- SceneIR geometry/point-cloud/collider refs và checksums.
- Browser WebGL/WebGL2 capability; WebGPU không phải P0 requirement.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- 3D viewer state derived from SceneIR, có mode chuyển 3DGS Visual/Geometry mesh/Point Cloud/Collider.
- P0 real Gaussian rendering và Three.js technical views bind đúng artifact checksums/canonical transform.
- Backend edit commands and refreshed canonical revision.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `frontend/src/features/viewer/`
- shared viewer components trong `frontend/src/components/`
- typed API/contracts trong `frontend/src/lib/`
- `src/api/` scene endpoints
- browser/e2e tests

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` typed SceneIR composition trên Three.js/WebGL/WebGL2. Three.js render
Geometry, Point Cloud, SceneObject, Collider và transform controls. Gaussian
renderer là P0, nhưng backend cụ thể chỉ được adopt sau qualification bằng
output Brush thực; không tự viết proprietary renderer hoặc binary format.

Tham khảo [Three.js docs/examples](https://threejs.org/docs/) cho OrbitControls,
TransformControls, Raycaster, PLYLoader và layers; không để Three.js scene state
thay canonical SceneIR transform. [React Three Fiber](https://github.com/pmndrs/react-three-fiber)
là library candidate để quản lý React/Three lifecycle, chỉ chọn sau khi kiểm
tra frontend scaffold/React compatibility. [Spark](https://github.com/sparkjsdev/spark)
là P0 renderer candidate cho Gaussian + mesh trong WebGL2;
[Spark + Next.js example](https://github.com/sparkjsdev/spark-react-nextjs) chỉ là
reference cho client-only setup/R3F integration, không clone thành product.
[Potree](https://github.com/potree/potree) chỉ là point-cloud LOD reference, không
phải P0 dependency. Chỉ adopt renderer sau khi chứng minh load đúng real Brush
`VisualArtifact`; PLYLoader/point cloud không phải Gaussian renderer.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

**Files**

| File | Vai trò |
|---|---|
| [`src/services/orchestration/scene/models.py`](../../../../../src/services/orchestration/scene/models.py) | `TransformEdit`, `SceneEditCommand`, `SceneRevision`, `SceneEditResult`, `VisualBinding` |
| [`src/services/orchestration/scene/editor.py`](../../../../../src/services/orchestration/scene/editor.py) | `SceneEditor`: seed revision từ fixture, áp edit, publish revision mới |
| [`src/services/orchestration/scene/errors.py`](../../../../../src/services/orchestration/scene/errors.py) | `SceneRevisionConflictError`, `SceneObjectNotFoundError`, `SceneEditRejectedError` |
| [`src/api/routes_product.py`](../../../../../src/api/routes_product.py) | `GET /jobs/{id}/scene`, `POST /jobs/{id}/scene/edits`, `GET /jobs/{id}/artifacts/content` |
| [`frontend/src/features/viewer/layers.ts`](../../../../../frontend/src/features/viewer/layers.ts) | SceneIR → layer, thuần, không import Three.js |
| [`frontend/src/features/viewer/ply.ts`](../../../../../frontend/src/features/viewer/ply.ts) | Đọc PLY ASCII |
| [`frontend/src/features/viewer/SceneCanvas.tsx`](../../../../../frontend/src/features/viewer/SceneCanvas.tsx) | React Three Fiber: grid, orbit, gizmo, box collider, point cloud |
| [`frontend/src/features/viewer/ViewerPanel.tsx`](../../../../../frontend/src/features/viewer/ViewerPanel.tsx) | View mode, ẩn/hiện layer, chọn object, gửi transform edit |

**Hai checksum khác vai — điểm dễ sai nhất**

`ArtifactRef.artifact_checksum` là **byte** sha256 của file đã publish
(`FilesystemArtifactStore.publish` ném `ValueError` nếu lệch). Còn
`scene_ir_checksum` *bên trong* document là **canonical content checksum**. Hai giá
trị này khác nhau và không được dùng lẫn.

**API flow (sau `/api/v1`)**

| Method | Path | State ownership |
|---|---|---|
| `GET` | `/jobs/{job_id}/scene` | `SceneEditor.current()` — seed revision từ fixture ở lần đọc đầu |
| `POST` | `/jobs/{job_id}/scene/edits` | `SceneEditor.apply()` — publish revision mới, `201` |
| `GET` | `/jobs/{job_id}/artifacts/content` | Đọc bytes, chỉ với URI nằm trong allow-list của job |

**Ranh giới đọc artifact bytes**

`GET /artifacts/content` không đọc theo đường dẫn tuỳ ý. URI phải nằm trong
allow-list của job, dựng từ (a) artifact đã lọc của job và (b) ref hình học/collider
của revision SceneIR hiện tại. Vì ref trong SceneIR là `ProductArtifactRef`
(`data_class` chỉ `product_input`/`derived`), `ground_truth`/`evaluation_only`
**không thể biểu diễn được** ở đó — ranh giới này là cấu trúc, không phải kiểm tra
bằng tay.

**Failure handling**

| Tình huống | Kết quả |
|---|---|
| `expected_scene_revision` không còn là revision hiện tại | `409` — hai tab cùng sửa thì tab sau bị từ chối |
| Edit vào object id không có trong revision | `422` |
| Quaternion không chuẩn hoá / transform không hợp lệ | `422`, **không** publish revision nào |
| Cùng một object xuất hiện hai lần trong một command | `422` |
| URI ngoài allow-list (artifact job khác, `evaluation_only`, path traversal) | `404` / `422` |
| Checksum không khớp bytes | `404` |

## 10. Tests

**Backend — `pytest`:**

- [`tests/test_orchestration/test_scene_editor.py`](../../../../../tests/test_orchestration/test_scene_editor.py) — 23 test: seed + publish revision đầu, seed idempotent, checksum fixture khớp canonical content, edit tăng revision và đổi đúng object, tính lại checksum, revision mới đọc được ở URI riêng, **bytes revision cũ không bị đụng**, provenance được ghi, object không bị sửa vẫn còn, edit thứ hai nối tiếp edit thứ nhất, revision cũ bị từ chối, object lạ bị từ chối, quaternion không chuẩn hoá bị từ chối **và không publish gì**, target trùng nhau bị từ chối, command rỗng bị từ chối, `VisualBinding` từ chối cờ Brush.
- [`tests/test_api/test_scene_routes.py`](../../../../../tests/test_api/test_scene_routes.py) — 17 test HTTP, gồm các ca âm: `evaluation_only` không tải được, artifact của job khác không tải được, URI path traversal bị từ chối, checksum sai bị từ chối.

**Frontend — `vitest`:**

- [`frontend/tests/layers.test.ts`](../../../../../frontend/tests/layers.test.ts) — 20 test: bind checksum vào layer, giữ revision canonical, collider environment khi scene rỗng object, kích thước chỗ giữ chỗ khi thiếu `dimensions_xyz_m`, giữ `canonical_active`, cộng/xoay translation của collider, **từ chối collider parent sai frame**, khoá layer không đụng nhau, phép nhân quaternion và xoay vector.
- [`frontend/tests/ply.test.ts`](../../../../../frontend/tests/ply.test.ts) — 10 test: đọc đúng PLY của fixture, giữ comment header, giữ thứ tự vertex, kết thúc dòng kiểu Windows, bỏ qua property thừa; **từ chối** PLY binary thay vì đoán layout, header thiếu `end_header`, số vertex ít hơn khai báo, toạ độ không phải số, thiếu property toạ độ.
- [`frontend/tests/viewer-panel.test.tsx`](../../../../../frontend/tests/viewer-panel.test.tsx) — 10 test: cảnh báo thiếu bằng chứng Brush, không cảnh báo khi có cờ, trạng thái suy giảm khi không có WebGL, dựng canvas khi có WebGL, đổi view mode, ẩn/hiện layer không đổi revision, sửa transform, lỗi nhập sai định dạng.

**Chưa làm:** renderer qualification với real Brush output (§10 dòng 2) và browser smoke
thật (§10 dòng 5) — cả hai đều cần `REC-04` publish `VisualArtifact` thật.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Viewer render real Brush 3DGS Visual trên Primary RGB Scene và chuyển được sang Geometry mesh/Point Cloud/Collider; fixture proof tách khỏi AC-11 real-browser proof.
- [x] Visual/Geometry/Point Cloud/Collider refs bind đúng checksums; missing/incompatible Visual báo lỗi và không pass AC-11.
- [x] Three.js layers dùng canonical coordinate/transform metadata.
- [x] Transform edits persist through backend revision then re-render.
- [x] Renderer capability/error state và cleanup rõ; synthetic visual hoặc mesh/point-cloud không bị báo cáo là Brush compatibility proof.
- [x] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

Ô đầu **cố ý để trống**: render 3DGS thật là **AC-11, mốc M3 (09/10)**, phụ thuộc
`REC-04` — hiện vẫn `TODO`. Ở M1 chỉ có bằng chứng mức fixture.

## 12. Result / Evidence

**Ngày:** 2026-09-24 · **Nhánh:** `feat/product`

**Test backend:**

```
tests/test_orchestration/test_scene_editor.py   23 passed
tests/test_api/test_scene_routes.py             17 passed
pytest tests/ (toàn bộ)                        288 passed in 3.07s
python -m ruff check src/ tests/               All checks passed!
python -m ruff format --check src/ tests/      104 files already formatted
```

**Test frontend:** `npm test` → `54 passed (54)`, 5 file. `npm run build` → exit 0.

**Ca âm quan trọng nhất — `evaluation_only` không ra được product boundary:**

```
GET /api/v1/jobs/job-fixture-001/artifacts/content
    ?artifact_uri=artifact://jobs/job-fixture-001/evaluation_only/groundtruth_map.mock
    &artifact_checksum=sha256:...
→ 404   artifact không thuộc job job-fixture-001
```

Cùng cơ chế, `test_artifact_from_another_job_cannot_be_fetched` → 404 và
`test_path_traversal_uri_is_rejected` → 422.

**Persist revision rồi đọc lại** (`test_edit_persists_so_next_read_sees_it`,
`test_previous_revision_bytes_are_untouched`): edit publish
`artifact://jobs/<id>/scene/scene_ir.rev-002.json`; `rev-001` giữ nguyên bytes cũ.

**Bằng chứng "không được đọc thành 3DGS thật":**

```jsonc
// GET /api/v1/jobs/job-fixture-001/scene
{ "visual": { "available": true,
              "format": "real2sim.synthetic.visual.v1",
              "producer": "foundation-fixture-generator",
              "brush_compatibility_proof": false,   // ← cờ đi kèm payload
              "unavailable_reason": null } }
```

```jsonc
// GET /api/v1/jobs/job-fixture-001/validation
{ "isaac_runtime_proof": false }   // environment_versions.isaac_sim == "UNVERIFIED"
```

Cờ này đi trong payload (không chỉ trong tài liệu), và UI render
`data-testid="brush-proof-absent"` khi cờ false — nên một visual tổng hợp không
thể bị trình bày nhầm thành bằng chứng AC-11.

**Limitations**

- **Chưa render 3DGS thật.** Đây là giới hạn cốt lõi: `REC-04` chưa publish real
  Brush `VisualArtifact`. Ở M1, view `VISUAL` chỉ hiện `VisualUnavailable` nói rõ
  lý do; ba view Geometry/Point Cloud/Collider là view kỹ thuật **ngang hàng**,
  không phải fallback và không thay thế AC-11.
- **Chưa chạy browser smoke.** Mọi test frontend chạy trong jsdom; `SceneCanvas`
  bị thay bằng stub. Chưa có lần nào render Three.js thật, orbit/pan/zoom thật,
  hay tải PLY thật qua `GET /artifacts/content` trong trình duyệt.
- PLY chỉ hỗ trợ `format ascii 1.0`. PLY binary bị **từ chối thẳng** thay vì đoán
  layout — đoán sai layout binary sẽ cho ra hình dạng trông hợp lệ nhưng sai, đúng
  kiểu lỗi §11 cấm báo cáo thành bằng chứng render.
- `SceneEditor` seed revision từ `fixtures/scene_ir/scene.json` ở lần đọc đầu tiên.
  Đây là dữ liệu fixture, **không** phải output của EX-SCENE.
- Revision chỉ nằm trong bộ nhớ tiến trình + file dưới runtime root; chưa có khoá
  liên tiến trình cho hai client sửa cùng lúc (optimistic concurrency chỉ đúng
  trong một tiến trình).
- Chưa có test benchmark hiệu năng render, và chưa kiểm việc giải phóng GPU
  resource khi unmount canvas.
