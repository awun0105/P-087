# PR-05 — Object-Aware Geometry & Collision Pipeline + ObjectGS Integration

## 0. Nhiệm vụ

Triển khai PR-05 trực tiếp trên repository Real2Sim Studio (P-087).

**Yêu cầu bắt buộc:**

1. Tích hợp ObjectGS thực sự vào pipeline để tạo surface mesh riêng cho từng vật thể.
2. Thay đổi cách tạo collision môi trường để không còn phụ thuộc hoàn toàn vào việc voxelize toàn bộ scene rồi xóa tam giác theo ownership.
3. Đồng bộ các geometry/collider mới với SceneIR, Studio, Browser Walk và USD export.
4. Tái sử dụng tối đa codebase hiện tại và những gì đã hoàn thành trong PR-01 đến PR-04.
5. Không thực hiện benchmark so sánh ObjectGS với SuGaR, Frosting hoặc các phương án khác. Công nghệ đã được lựa chọn: **ObjectGS + object-aware environment collision + CoACD**.

Đây là implementation task, không phải research proposal. Tuy nhiên, vẫn phải thực hiện functional tests, validation và E2E smoke tests để chứng minh code hoạt động.

**QUY TẮC GIT: Chỉ commit local sau mỗi phần triển khai nhỏ đã được kiểm thử. KHÔNG push, KHÔNG tạo GitHub PR, KHÔNG merge.**

---

## 1. Đọc bối cảnh trước khi code

Repository: `https://github.com/awun0105/P-087`

Baseline dự kiến:

- Branch: `codex/pr04-browser-physics`
- HEAD: `be1973edf9002d9011f0b7d31eb211d6259ed34e`
- PR-04 đã có 9 commit local, working tree sạch, chưa push.

Phải kiểm tra lại Git thực tế. Nếu baseline khác, xác định nguyên nhân trước khi thao tác. Không reset hoặc ghi đè thay đổi chưa commit.

Đọc bắt buộc:

- `AGENTS.md`, các hướng dẫn repository liên quan.
- Handoff PR-01/02/03/04.
- `docs/plans/active/2026-10-14-pr03-effective-collision/HANDOFF.md`
- `docs/plans/active/2026-10-14-pr04-browser-physics/HANDOFF.md`
- `docs/decisions/0007-object-centric-hybrid-usd-pipeline.md`
- `docs/execution/audits/10_pipeline_v2_methods.md`

Kiểm tra ít nhất các khu vực:

| Khu vực | File cần truy vết |
|---|---|
| Objectify | `src/services/orchestration/scene/objectify.py` |
| Membership correction | `src/services/orchestration/scene/object_correction.py` |
| Gaussian split | `src/services/scene/decomposition/gaussian_split.py` |
| Ownership | `src/services/scene/collision_ownership.py` |
| Effective collision | `src/services/scene/effective_collision.py` và orchestration resolver |
| CoACD | `src/services/simulation/colliders/convex_runner.py` |
| Scene contracts | `src/models/contracts/scene.py` |
| USD | `src/services/simulation/usd/hybrid_runner.py` |
| Studio | `frontend/src/features/studio/MetricSceneView.tsx`, `ObjectReviewView.tsx` |
| Browser physics | `scene-physics.ts`, `camera-collision.ts`, `usePhysicsPlay.ts` |

Đối chiếu tên và đường dẫn thực tế, không tạo bản sao service chỉ vì chưa tìm thấy ngay.

Kiểm tra Git diff và call graph trước khi sửa. Ưu tiên thay đổi producer và artifact flow, không viết lại UI hoặc physics engine.

---

## 2. Vấn đề hiện tại — Root Problem

Hiện tại hệ thống có hai nhánh collider:

### Nhánh A: Environment collision

```text
Global Brush 3DGS
      ↓
splat-transform
      ↓
Voxelization
      ↓
--voxel-external-fill / --voxel-carve
      ↓
Global collision mesh GLB
      ↓
Màu xanh trong Studio
```

Global collision mesh không mang thông tin semantic object ownership trực tiếp.

Khi một chiếc bàn tiếp xúc với mặt sàn, voxelization có thể khiến bề mặt bàn, chân bàn và sàn hợp thành một mạng mesh liên thông.

PR-03 đã bổ sung triangle ownership và effective collision composition. Nhưng loại tam giác theo ownership không tương đương với việc tạo lại geometry sạch sau khi đã phân tách đối tượng.

Nếu ownership thiếu hoặc ambiguous, mesh xanh có thể vẫn chứa collision thuộc bàn ở extraction pose.

### Nhánh B: Object collision

```text
Global Brush 3DGS
      ↓
SAM2 / Gaussian segmentation
      ↓
Gaussian splitting
      ↓
Gaussian PLY từng vật thể
      ↓
Existing convex_runner / CoACD
      ↓
ObjectCollider GLB
      ↓
Khung màu cam
```

PR-04 đã cho phép Browser Walk sử dụng multipart CoACD collider thực sự.

Tuy nhiên, object-specific surface mesh hiện vẫn chưa được tạo bằng pipeline ObjectGS.

### Vấn đề cần PR-05 giải quyết

**Global environment collider và object collider phải được tạo từ những tập hình học đã phân định rõ, thay vì phụ thuộc vào một global collision mesh vốn không phân biệt vật thể.**

---

## 3. Kiến trúc kết quả mong muốn

```text
                RGB VIDEO
                    |
                    v
              COLMAP + Brush
                    |
                    v
             Global 3DGS PLY
                    |
                    v
           SAM2 / Object Identity
                    |
                    v
       Gaussian Membership / SceneIR
                    |
        +-----------+------------+
        |                        |
        v                        v
 BACKGROUND                  OBJECTS
        |                        |
        v                        v
 Background-only        ObjectGS integration
 Gaussian source        (object-aware runtime)
        |                        |
        v                        v
 Object-aware           Object surface meshes
 voxel geometry                  |
        |                        v
        v                      CoACD
 Background collision             |
        |                        v
        v                  ObjectCollider GLB
 BLUE ENV MESH                    |
                                 v
                          ORANGE OUTLINES

        +------------------------+
        |
        v
  Shared SceneIR revision
        |
        +---- Real2Sim Studio
        +---- Browser Walk / Ammo
        +---- USD Export / Isaac Sim
```

**Yêu cầu cốt lõi:** không được để environment collision và per-object collision đại diện trùng cùng một vật ở hai vị trí.

Ví dụ chiếc bàn:

- Bàn có Gaussian riêng để hiển thị.
- ObjectGS tạo surface mesh riêng cho bàn.
- CoACD tạo collider riêng từ surface mesh của bàn.
- Background collision không giữ lại phần hình học bàn sau khi bàn được tách và Confirm.
- Khi Move, Gaussian và object collider chuyển đến pose mới.
- Mặt sàn và tường vẫn tồn tại ở extraction pose.

---

## 4. Milestone A — Tích hợp ObjectGS thực tế

### A1. Audit tương thích kỹ thuật để triển khai, không benchmark

Upstream:

`https://github.com/RuijieZhu94/ObjectGS`

Các entrypoints:

- `train.py`
- `export_object_mesh.py`
- `export_mesh.py`
- `ply_preprocessing.py`
- `utils/mesh_utils.py`

ObjectGS sử dụng checkpoint, Gaussian labels, camera views và bản `gsplat` tùy chỉnh.

**Không được giả định rằng có thể đưa trực tiếp Brush PLY vào `export_object_mesh.py` rồi nhận surface mesh hợp lệ.**

Trước khi implement adapter:

1. Đọc code ObjectGS và định dạng dữ liệu đầu vào thật.
2. Xác định chính xác format images, masks, cameras, poses, labels, checkpoints.
3. Xác định dữ liệu đã có trong COLMAP/Brush/SAM2 pipeline có thể tái sử dụng.
4. Xác định phần nào cần chuyển đổi để đưa vào ObjectGS.
5. Kiểm tra giấy phép của mã nguồn và các dependency/submodule liên quan.
6. Chọn một revision/commit ObjectGS cố định để bảo đảm tái lập.

Đây chỉ là compatibility audit phục vụ implementation. Không xây bảng benchmark công nghệ.

### A2. Runtime riêng cho ObjectGS

**Không cài đè `gsplat-object` lên môi trường hiện tại của Brush.**

ObjectGS phải chạy trong Python environment hoặc container tách biệt.

Tạo adapter/runner phù hợp với kiến trúc subprocess hiện tại của dự án.

Runner phải hỗ trợ:

- Job ID.
- Input directory và output directory.
- Camera/pose metadata.
- Instance mask/object label mapping.
- GPU device.
- Config được validate.
- Checkpoint/resume nếu upstream hỗ trợ thực tế.
- Timeout và cancellation.
- Progress/error reporting.
- Artifact checksums.
- Provenance gồm upstream commit/config/runtime version.

Không viết lại thuật toán training của ObjectGS nếu upstream đã có implementation.

Không thêm package GPU nặng vào app `.venv` nếu có nguy cơ phá các pipeline hiện có.

### A3. Adapter dữ liệu

Chuẩn bị dữ liệu ObjectGS từ các artifact đã có:

```text
RGB frames
COLMAP calibrated cameras / poses
SAM2 instance masks / IDs
Scene object IDs
Metric alignment / canonical transform
```

Phải giữ mapping rõ ràng:

```text
ObjectGS label ID ↔ SceneIR object ID
```

Không được giả định hai hệ thống sử dụng cùng quy ước label. Kiểm tra giới hạn label IDs của ObjectGS và xử lý theo giới hạn thực của upstream.

Nếu ObjectGS huấn luyện trong hệ tọa độ khác, lưu và áp dụng phép biến đổi về canonical world một cách tường minh.

Metric scale phải giữ theo SceneIR hiện tại. Không tự scale lại thành mét lần thứ hai.

### A4. Train và export object meshes

Triển khai đường chạy ObjectGS thực sự để tạo checkpoint phù hợp, sau đó xuất mesh từng object.

Sử dụng API/export logic có thật từ upstream. Kiểm tra `--query_label_id` và hành vi xuất từng object, không giả định truyền `-1` sẽ tự tạo tất cả kết quả chính xác.

Đầu ra mỗi vật cần có:

```text
object_id
objectgs_label_id
surface_mesh_ref
source_checkpoint_ref
source_membership_checksum
mesh_checksum
coordinate_frame
scale provenance
quality/validity metadata
```

Mesh phải:

- Chứa các vertices và triangles hữu hạn.
- Có hình học thực, không rỗng.
- Có transform đúng.
- Có đơn vị mét khi đưa vào SceneIR.
- Có thể kiểm tra, load và xuất sang định dạng GLB hoặc định dạng chuẩn mà pipeline hiện tại hỗ trợ.

Nếu mesh còn lỗ hoặc non-manifold, dùng geometry cleanup có kiểm soát trước khi đưa sang CoACD.

Không lấp lỗ một cách tùy tiện làm biến mất khoảng trống quan trọng như gầm bàn.

**Không được báo ObjectGS integrated chỉ vì có wrapper hoặc import upstream nhưng chưa chạy được train/checkpoint → mesh export.**

---

## 5. Milestone B — Tạo collider từng vật từ ObjectGS mesh

Hiện nay `objectify.py` tạo collider trực tiếp từ Gaussian PLY thông qua `convex_runner`.

PR-05 cần bổ sung đường:

```text
ObjectGS surface mesh
        ↓
Geometry validation
        ↓
Cleanup / connected components
        ↓
CoACD
        ↓
Multipart convex collider
        ↓
ObjectCollider GLB
```

### Yêu cầu

- Giữ từng convex part.
- Không gộp tất cả thành một convex hull.
- Không thay bằng một OBB âm thầm khi đường ObjectGS/CoACD lỗi.
- Giữ khoảng trống giữa chân bàn nếu hình học nguồn thể hiện khoảng trống ấy.
- Đồng bộ geometry và collider transforms.
- Collider GLB tương thích với PR-04 Ammo compound physics.
- USD tiếp tục sử dụng collider hợp lệ.

Cần phân biệt hai artifact:

**Object surface mesh:** hình học mô tả bề mặt vật thể.

**Object collider mesh:** hình học va chạm đơn giản hóa/phân rã lồi phục vụ physics.

Không dùng hai tên đó thay thế cho nhau.

Nếu SceneIR hiện dùng chung `geometry_ref` cho cả mesh và collider, sửa contract/producer/consumers theo cách tương thích ngược để hai nguồn dữ liệu độc lập.

Không phá existing ObjectGaussians visual rendering.

---

## 6. Milestone C — Object-aware environment collision

Đây là phần trực tiếp xử lý vấn đề collision xanh vẫn là một khối chứa vật thể.

### C1. Phân chia dữ liệu trước khi tạo collision

Đầu vào cần lấy từ Gaussian membership đã lưu, không phải bounding box dựa trên pose hiện tại.

Tách:

- Source Gaussian thuộc background.
- Source Gaussian thuộc từng object.
- Vùng unknown hoặc ambiguous.

Dùng **source/extraction pose bất biến** cho ownership.

Không sử dụng current moved pose để tìm vùng phải loại khỏi collision môi trường.

### C2. Tạo background collision riêng

Đường tạo mới:

```text
Background-only Gaussian source
            ↓
Voxelization / geometry processing
            ↓
Environment occupancy
            ↓
Floor/wall preservation
            ↓
Environment collision mesh GLB
```

Có thể tái sử dụng `splat-transform` cho voxelization nếu phù hợp.

Nhưng **không được chỉ lọc Gaussian thuộc vật rồi chạy lại `--voxel-external-fill` và mặc định coi là đã giải quyết**.

Lý do: external fill/carve có thể làm đầy lại những vùng đã loại bỏ, hoặc lấp khoảng trống và làm biến mất hình học sàn/tường.

Phải xử lý rõ:

- Background occupancy.
- Object-owned occupancy.
- Shared/ambiguous occupancy.
- Free space.
- Floor/support region.
- Collision mesh extraction.

Nếu external fill làm xuất hiện ghost collision, phải triển khai exclusion/ownership ở cấp voxel **trước bước meshing**, thay vì quay lại cắt một khối mesh không có semantics.

### C3. Bảo vệ sàn và tường

Không xóa phần sàn chỉ vì chân bàn chạm vào sàn.

Yêu cầu tối thiểu:

- Giữ mặt sàn dưới vị trí chiếc bàn cũ.
- Giữ tường và vật cản không thuộc object.
- Không tạo lỗ lớn tại vùng tiếp xúc.
- Không giữ lại phần hình học đáng kể của chiếc bàn tại pose cũ.
- Không tạo vật cản ảo tại khoảng trống đã được giải phóng.

Không voxelize Gaussian được inpaint để làm collider vật lý nếu chúng chỉ là hình ảnh suy đoán và chưa có nguồn hình học được chấp nhận.

Nếu background geometry thiếu vì vật từng che khuất, phải có quy tắc phục hồi support geometry rõ ràng, đánh dấu vùng suy đoán và tránh khẳng định đó là đo đạc thật.

### C4. Giữ provenance của mesh nguồn

Không xóa global collision artifact cũ.

Giữ nó làm nguồn gốc/đối chứng chẩn đoán, nhưng tạo một artifact riêng đại diện cho collision môi trường đã tách vật.

Ví dụ về mặt logic:

```text
OriginalGlobalCollision
    → immutable source / provenance

ObjectAwareEnvironmentCollision
    → active environment physics geometry
```

Tên field cụ thể phải quyết định dựa trên SceneIR contract thực tế.

Không được ghi đè `geometry_ref`, `collision_source_ref` hoặc checksum khi chưa kiểm tra tất cả consumers.

---

## 7. Milestone D — Tương thích PR-03 và PR-04

### D1. Effective collision

PR-03 hiện có thuật toán source triangle ownership và removal mask.

Khi nguồn collision mới đã được tạo từ background-only/object-aware geometry, **không được tiếp tục carve lần thứ hai theo ownership của global mesh cũ**.

Cần bổ sung phân biệt hai chế độ có provenance:

- Legacy source collision + triangle ownership composition.
- Object-aware authored environment collision.

Chế độ mới phải lấy đúng artifact theo SceneIR revision/checksum.

Không sử dụng stale collision từ revision trước.

### D2. Browser Studio

- Collision xanh hiển thị đúng environment collider mới.
- Khung cam hiển thị object collider.
- Gaussian vẫn là visual.
- Move/Rotate không rerun ObjectGS hoặc CoACD.
- Hide viewport không xóa physics.
- Confirm/Delete/Restore dùng đúng lifecycle đã triển khai.

Nếu việc đổi collider artifact làm reload toàn bộ 3DGS, đó là regression và phải sửa.

### D3. Browser Walk

Reuse implementation PR-04:

- `btCompoundShape` cho multipart CoACD.
- Static và dynamic bodies.
- Combined camera collision queries.
- Correct world transforms.
- Revision-bound artifact loading.

Không viết một physics engine mới.

### D4. USD export

- Environment collision là mesh tĩnh riêng.
- Object collider đi theo SceneObject.
- Object visual và collider không bị double transform.
- Không có object collider trùng trong environment.
- USD vẫn giữ Z-up, mét và provenance/checksum.

Không coi việc file USD mở được là bằng chứng physics đúng; phải kiểm tra các collision geometry refs và transforms trong stage.

---

## 8. Milestone E — Membership correction và regenerate

Codebase đã có:

- Merge candidate objects.
- Reassign Gaussian membership bằng ROI.
- Tạo lại object artifacts/collider trong một số đường correction.

PR-05 phải tích hợp pipeline ObjectGS với những chức năng này.

Khi ownership của một object thay đổi:

1. Tạo SceneIR revision/correction operation hợp lệ.
2. Xác định các object và background bị ảnh hưởng.
3. Invalidate surface mesh/collider tương ứng theo checksum.
4. Chạy lại các stage thực sự cần thiết.
5. Đối với ObjectGS, nếu label correction đòi hỏi retraining để cập nhật mô hình, phải thực hiện retraining/rebuild có kiểm soát hoặc báo trạng thái cần xử lý, không tái sử dụng checkpoint cũ như thể nó phản ánh membership mới.
6. Cập nhật artifact refs và effective environment collision.
7. Chỉ cho phép dùng revision mới khi validation hoàn thành.

Không để artifact cũ vẫn hiển thị hoặc được export như kết quả mới.

Chưa cần implement Brush/Lasso UI trong PR-05. UI correction trực quan có thể làm sau; backend producer mới phải hoạt động trước.

---

## 9. Milestone F — Chẩn đoán collision trong Studio

Bổ sung tối thiểu các thông tin cần thiết để kiểm tra scene Room, tái sử dụng giao diện hiện có:

- Environment collision source: Legacy hay Object-aware.
- Số tam giác của environment collision.
- Số object colliders.
- Số convex parts của object đang chọn.
- Artifact/revision hiện hành.
- Cảnh báo khi collider đang stale hoặc producer chưa hoàn thành.

Nếu có thể triển khai nhỏ, thêm chế độ xem **Collision Wireframe**, dùng cơ chế wireframe hiện có của PlayCanvas.

Không xây một full mesh editor trong PR này.

---

## 10. Tests và nghiệm thu bắt buộc

### Test A — ObjectGS adapter

Dùng fixture hoặc output thật hợp lệ của upstream để xác minh:

- Object label mapping.
- Training/checkpoint contract.
- Mesh export.
- Coordinate conversion.
- Checksum/provenance.
- Missing/invalid inputs phải fail rõ ràng.

Nếu chưa có GPU/CUDA, các bài test mock không được thay thế cho bằng chứng ObjectGS chạy thật. Ghi GPU E2E `UNVERIFIED` và hướng dẫn lệnh chạy chính xác.

### Test B — Object surface mesh

Một object fixture có hình dạng lõm, gồm hai chân cách nhau.

Kiểm tra:

- Output surface mesh chứa geometry hợp lệ.
- Transform đúng.
- Không bị đổi kích thước.
- CoACD output giữ các convex parts.
- Không tạo khối đặc bịt khoảng trống giữa các chân chỉ vì gộp hull.

### Test C — Environment separation

Tạo fixture có:

```text
Một mặt sàn
Một chiếc bàn tiếp xúc với sàn
Một bức tường
Một vật không được chọn
```

Nguồn collision ban đầu có thể là mesh liên thông.

Sau object-aware generation:

- Sàn vẫn có collision.
- Tường vẫn có collision.
- Vật không chọn vẫn được giữ theo policy.
- Bàn đã được tách không còn trong environment collision.
- Bàn có object collider riêng.
- Không có ghost collision tại vị trí bàn cũ sau Confirm → Move.

### Test D — Source ownership và revision

- Immutable source pose được giữ nguyên.
- Move không thay extraction ownership.
- Reassign/merge đúng revision invalidation.
- Không double carve.
- Không double collision.
- Stale async result không được publish.
- Restore đúng revision và artifact checksum.

### Test E — Browser physics regression

Chạy lại các test PR-01/02/03/04.

Đặc biệt:

```text
Confirm Table
     ↓
Move Table
     ↓
Enter Walk
     ↓
Hit table at NEW pose
     ↓
No object ghost at OLD pose
     ↓
Floor still blocks
```

### Test F — USD smoke

Import hoặc parse stage bằng OpenUSD runtime hiện có.

Kiểm tra:

- Environment collider tồn tại.
- Object collider tồn tại.
- Object có đúng local/world transform.
- Không ghi geometry trùng.
- Stage references/chksums hợp lệ.

Isaac Sim chạy thật chỉ đánh dấu PASS nếu thực sự được chạy.

### Test G — Functional smoke trên Room

**Không bắt buộc benchmark so sánh các thuật toán.**

Nhưng bắt buộc chuẩn bị lệnh chạy một job Room qua pipeline mới:

```text
RGB / existing prepared input
→ COLMAP / Brush
→ Objectify
→ ObjectGS
→ Object surface mesh
→ CoACD
→ Object-aware environment collision
→ SceneIR
→ Studio / Walk / USD
```

Bắt buộc ghi rõ bước nào đã chạy thật và bước nào chưa có môi trường xác minh.

Nếu chỉ chạy fixture, không được tuyên bố end-to-end production PASS.

---

## 11. Acceptance Criteria

| ID | Điều kiện |
|---|---|
| AC-01 | Có ObjectGS runner thực sự, không phải placeholder |
| AC-02 | Input preprocessing và label mapping phù hợp upstream |
| AC-03 | ObjectGS tạo được surface mesh từng vật từ output hợp lệ |
| AC-04 | CoACD sử dụng surface mesh mới để tạo multipart collider |
| AC-05 | Background collision không còn mặc định voxelize cả scene có object |
| AC-06 | Sàn/tường được bảo toàn sau object separation |
| AC-07 | Không còn ghost collision của object Confirmed đã Move |
| AC-08 | SceneIR quản lý riêng object surface mesh, object collider và environment collider |
| AC-09 | Studio, Browser Walk và USD dùng cùng effective geometry revision |
| AC-10 | Membership correction invalidates/rebuilds artifacts đúng |
| AC-11 | Không regression PR-01 đến PR-04 |
| AC-12 | Automated tests/typecheck/lint PASS |
| AC-13 | Có executable Room E2E smoke và trạng thái nghiệm thu trung thực |
| AC-14 | Không có silent fallback khiến pipeline báo thành công giả |

**Không đánh dấu AC-01–AC-04 PASS chỉ vì source code biên dịch thành công.**

Nếu thiếu CUDA/GPU để chạy ObjectGS thật, cần ghi blocker thực tế, không thay đường ObjectGS bằng CoACD từ PLY cũ rồi gọi đó là hoàn thành.

Các scene legacy có thể tiếp tục sử dụng đường cũ để bảo đảm backward compatibility. Nhưng đối với job được cấu hình chạy pipeline ObjectGS, việc stage ObjectGS bị thiếu không được âm thầm rơi về đường cũ và báo thành công.

---

## 12. Cách chia implementation và commit

Tạo branch mới:

`codex/pr05-object-aware-geometry`

Base trên local PR-04 sạch, không base trên GitHub `master` cũ.

Triển khai theo thứ tự:

**Commit 1 — Contracts & pipeline interfaces**
- Artifact types/refs.
- Pipeline boundaries.
- Source vs active environment geometry provenance.
- Tests validation.

**Commit 2 — ObjectGS runtime adapter**
- Dependency isolation.
- Input prep.
- Runner + error/cancel/progress.
- Config and upstream license notices.
- Tests.

**Commit 3 — ObjectGS surface mesh producer**
- Per-object export.
- Coordinate/frame mapping.
- GLB validation.
- Artifact publication.

**Commit 4 — Mesh → CoACD integration**
- Surface mesh input to CoACD.
- Multipart collider output.
- SceneIR links.
- Negative tests.

**Commit 5 — Object-aware environment collider**
- Background-only source.
- Voxel ownership/exclusion.
- Floor/wall preservation.
- Mesh generation.
- Fixture tests.

**Commit 6 — Effective collision + consumers**
- PR-03 compatibility.
- Studio/Walk/USD updates.
- Revision/cache correctness.
- Regression tests.

**Commit 7 — Correction/invalidation**
- Merge/reassign impacts.
- Rebuild/retraining invalidation.
- Artifact freshness.

**Commit 8 — E2E smoke + handoff**
- Full related suites.
- Executable pipeline command.
- Room acceptance evidence or explicit unverified gates.
- Final documentation.

Đây là thứ tự logic đề xuất. Có thể tách thêm commit nhỏ hơn nếu hợp lý. **Mỗi commit phải chứa thay đổi hoàn chỉnh đã được kiểm thử phù hợp.**

Không gom toàn bộ code vào một commit cuối.

---

## 13. Giới hạn phạm vi

Không làm:

- Benchmark công nghệ cạnh tranh.
- Tích hợp thêm SuGaR hoặc Frosting.
- Thay thế COLMAP/Brush.
- Viết lại SAM2.
- Full SuperSplat selection editor.
- Brush/Lasso UI mới.
- Full 3D mesh editing UI.
- Viết lại browser physics.
- Tính năng robot navigation ngoài scope.
- Chỉnh sửa dữ liệu bằng hardcoded Room coordinates.

Mọi thuật toán phải dùng dữ liệu đầu vào và transform chung, không hardcode cho dataset Room.

ObjectGS và object-aware collision phải được tích hợp bằng những stage rõ ràng, có khả năng tái sử dụng cho scene khác.

---

## 14. Handoff cuối cùng

Tạo handoff tại:

`docs/plans/active/2026-10-15-pr05-object-aware-geometry/HANDOFF.md`

Nội dung bắt buộc:

1. Root causes đã xác minh.
2. ObjectGS upstream commit và cách cài.
3. Dependency/license compatibility.
4. Input/output schema của ObjectGS adapter.
5. Object surface mesh production flow.
6. Object-aware environment collision algorithm.
7. Artifacts và SceneIR contract changes.
8. Mối quan hệ với PR-03/PR-04.
9. Các tests chạy và kết quả thực.
10. E2E Room status.
11. Bảng AC-01 đến AC-14.
12. Những giới hạn còn tồn tại.
13. Commit SHAs.
14. Branch, HEAD, working tree và xác nhận chưa push.

Nếu gặp blocker kỹ thuật thực sự, cần:

- Ghi rõ lỗi và bằng chứng.
- Xác định component bị chặn.
- Giữ các phần đã hoàn thành và tests ở trạng thái nhất quán.
- Tiếp tục những milestone độc lập khi có thể.
- Không báo hoàn thành giả.
- Không tự ý thay đổi hướng công nghệ đã lựa chọn.

**Definition of Done:**

Real2Sim Studio có đường pipeline ObjectGS thật tạo mesh theo vật, CoACD tạo collider riêng từ hình học đó, environment collision được xây dựng theo phân chia object/background, và các artifact mới được sử dụng nhất quán trong SceneIR, Studio, Browser Walk và USD.

Chiếc bàn đã Confirm và Move phải có collision tại vị trí mới, trong khi collision môi trường tại vị trí cũ không còn giữ phần hình học bàn nhưng vẫn bảo toàn sàn và tường.

**Chỉ commit local. Tuyệt đối không push, không tạo GitHub PR, không merge.**