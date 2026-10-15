# Report T-018: Tương thích scene cũ + Walk/USD với collider vỏ

## Done

Làm theo 3 bước của plan, mỗi bước một nhóm commit. Không đổi dòng nào trong `src/`: không có reader nào giả định
ObjectGS-only, và test e2e không lộ lỗi thật trong `effective_collision.py` hay `usd/builder.py`.

- **Bước 1** (`47a89ab3`): grep mọi nơi đọc `surface_mesh_ref`, `ObjectSurfaceManifest`, `surface_manifest_ref`,
  `shell_manifest_ref`, `surface_origin`, `surface_selection` (xem bảng "Reader audit" bên dưới). Test khoá việc chấp nhận
  vỏ ở ba chỗ đọc: `_collect_scene_refs` (inventory USD), `SceneEditor.artifact_references` (giữ tham chiếu) và
  `ObjectShellManifest` qua `provenance.shell_manifest_ref`.
- **Bước 2** (`f12ef68a`): e2e với CoACD thật (`data/scene_runtime`). Xác nhận candidate-001 rồi Move +1 m x và xoay 90°
  quanh z (từ (1, 1, 0.2) sang (2, 1, 0.2)). Kiểm:
  - Walk: môi trường không đổi khi Move; không tam giác nào cao hơn 0,1 m trong vùng cũ (không ghost); sàn còn dưới vùng cũ;
    collider đúng pose và đúng hướng xoay.
  - USD (`hybrid_runner` trong runtime có pxr, cùng cách test ObjectGS hiện có): bounds collider đọc lại khớp pose tính từ
    GLB trong 1e-4 m; scale = 1 trên prim và trên stage (mét); số mặt môi trường trong USD bằng số mặt Walk, không khoét
    thêm.
  - Pose-only Move không xếp việc nào mới: `objectify_queue.state` trước và sau chỉ khác `scene_revision`, status `idle`,
    không `operation_id`.
- **Bước 3** (`4070e964`): tương thích.
  - Scene legacy (không có khoá `object_geometry`): `object_geometry_state` = `ready`, `_require_walk_allowed` không chặn,
    Move không đổi môi trường Walk, `build_simulation_package` vẫn PASS và xuất 1 vật xác nhận.
  - Scene kiểu ObjectGS cũ (fixture `case` với `ObjectSurfaceMesh`): không khoá Walk, Move không đổi môi trường,
    surface còn trong inventory USD.

### Số đo khi chạy (không nằm trong assert)

Chạy thử một lần, ngoài test, để kiểm test có phân biệt được hay không:

- Vùng cũ của candidate-001 (footprint + 0,05 m): 0 tam giác cao hơn 0,1 m (không ghost), 354 tam giác sàn (≤ 0,05 m).
- Đối chứng candidate-002 (chưa xác nhận, nằm nền): 862 tam giác cao hơn 0,1 m. Vậy kiểm tra ghost có thấy vật khi vật có mặt.
- Môi trường trước và sau Move: 6104 mặt, 3728 đỉnh, bằng nhau từng bit.
- Collider sau Move: tâm (2,010; 1,000; 0,210); kích thước (0,384; 0,324; 0,464). Vỏ và collider khớp nhau trong 1 mm
  trên min/max. Kích thước nở ~0,06–0,08 m/trục so với hộp nguồn 0,24 × 0,32 × 0,4 m trên lưới 0,02 m.

### Reader audit

| Chỗ đọc / ghi | Kiểu | Kết luận |
| --- | --- | --- |
| `src/models/contracts/scene.py:166-177` (validator `surface_mesh_ref`) | đọc | Nhận `ObjectSurfaceMesh` và `ObjectShellMesh`. Test có sẵn `tests/test_contracts/test_object_geometry.py`. |
| `src/services/simulation/usd/builder.py:98` (`_collect_scene_refs`) | đọc | Không phụ thuộc loại. Có test `test_shell_surfaces_are_accepted_by_every_backend_reader`. |
| `src/services/orchestration/scene/editor.py:274` (`artifact_references`) | đọc | Không phụ thuộc loại. Test cùng tên ở trên. |
| `src/services/orchestration/scene/object_geometry_build.py:293`, `objectify.py:909-943` | ghi/kiểm | Chỉ đường ObjectGS tạo `ObjectSurfaceMesh` và `ObjectSurfaceManifest`. Không phải reader cho vỏ. |
| `ObjectSurfaceManifest`, `surface_manifest_ref`, `objectgs_surface_manifest_ref` | ghi | Không có reader trong `src/`; chỉ test đọc. Không cần đổi. |
| `ObjectShellManifest`, `shell_manifest_ref` | ghi | Không có reader trong `src/`; test đọc để kiểm tham chiếu. Không cần đổi. |
| `src/services/orchestration/scene/surface_evidence.py:34` | ghi | Chỉ ghi tên loại evidence. |
| `frontend/src/lib/contracts/api.ts:349` | kiểu | `ProductArtifactRef | null`, không giới hạn loại. |
| `frontend/src/features/studio/ObjectReviewView.tsx:133-140` (`colliderSourceLine`) | đọc | Nhận `chosen: "gaussian_shell"` không có `reason`. (File của T-013, không sửa.) |

## Files changed

- `tests/test_scene/test_shell_geometry_walk_usd.py` (mới, 6 test): reader audit, e2e Walk, e2e USD, queue, legacy,
  ObjectGS-era.
- `.ai/tasks/T-018/report.md` (mới), `.ai/status.md` (chỉ dòng T-018).

Không đổi `src/` nào: `effective_collision.py`, `usd/builder.py` và các reader trong bảng đều đúng như hiện tại.

## Tests

- `pytest tests/test_scene/test_shell_geometry_walk_usd.py -q`: **6 passed**, 39 s. CoACD thật và pxr chạy qua
  `data/scene_runtime/bin/python` (không skip).
- Bộ Tests required của plan (6 file), trên **HEAD sạch** (export `git archive HEAD` ra thư mục tạm, đã xoá): **48 passed**.
- Bộ Tests required trên **working tree dùng chung**: 47 passed, **1 failed**:
  `tests/test_scene/test_objectgs_objectify_flow.py::test_objectgs_surface_reaches_real_coacd_and_publishes_separate_background[legacy-False-True]`.
  Nguyên nhân nằm ngoài T-018: thay đổi chưa commit trong `membership_regeneration.py` (có khả năng là phần T-011 đang
  in-progress) làm `regenerate_membership` gọi `build_object_geometry`. HEAD không gọi hàm này ở đó. Shell build ném
  `no connected component reaches min_component_fraction` trên fixture này. Chưa commit nào của T-018 sửa `src/`.
- `ruff check` và `ruff format --check` trên file test mới: passed.
- `graphify update .` đã chạy (`graphify-out/` nằm trong `.gitignore`).

## Deviations from plan

1. Không sửa `effective_collision.py` hay `usd/builder.py`: test không lộ lỗi thật, nên plan cho phép nhưng không yêu cầu.
2. Bước 1 không có commit sửa code vì không có reader nào giả định ObjectGS-only. Đổi lại, có commit khoá hành vi.
3. Reader và queue test chạy với CoACD giả (`cpu_providers`) vì chúng không kiểm đầu ra CoACD. Hai e2e (Walk, USD)
   dùng CoACD thật và skip rõ lý do nếu thiếu runtime.
4. Dung sai kích thước collider là 0,12 m (plan không nêu), vì vỏ và CoACD nở tới ~0,09 m tổng mỗi trục trên lưới 0,02 m.
   Kiểm tra xoay là thứ tự cạnh x > y, không phụ thuộc dung sai.
5. Dòng `in-progress` trong `status.md` đã vào commit `99da808f` của agent khác. Tôi không có commit riêng cho bước đó.

## Known issues / TODO

- **Trùng tham chiếu trong inventory USD.** Với vật dựng từ vỏ, `geometry_ref` và `collider.geometry_ref` là cùng một
  `ObjectCollider`. `_collect_scene_refs` nên liệt kê collider hai lần (trong `geometry` và `colliders`), nên
  `artifact_checksums` có phần tử trùng. Manifest vẫn khớp, USD vẫn đúng. Không sửa vì ngoài phạm vi. Đề xuất T-019 kiểm.
- **`membership_regeneration.py:225`** (đã có trong HEAD) gắn cứng `geometry_method="objectgs"` khi regenerate. Nếu scene
  nguồn là vỏ, provenance sẽ sai. Người làm T-011 cần kiểm trước khi commit phần đang sửa file này.
- **`objectify_queue.py:257` (T-009)**: `object_centric` chỉ True khi `geometry_method == "objectgs"`, nên scene vỏ báo
  `object_centric=false`. Cần xác nhận Studio hiển thị đúng ý.
- **Chưa có test `build_simulation_package` trên scene vỏ.** Plan chỉ yêu cầu USD bằng `hybrid_runner`. Đường package đầy đủ
  (preflight, sealed package) với scene vỏ nên kiểm ở T-019.
- Chất lượng ObjectGS thật, Isaac Sim và browser: ngoài phạm vi (plan Out of scope).

Đã dừng chờ review.
