# REC-07 — TorWIC LiDAR Prefusion

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `VALIDATING` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Offline transform/merge/filter/downsample TorWIC raw LiDAR thành registered_lidar.ply có dependency provenance.

## 3. Why This Task Exists

Product MVP không nhận raw LiDAR scan sequence; prefusion là controlled dataset preparation.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-01 raw traversal/calibration metadata.
- Declared pose source; `traj_gt` use phải theo Dataset Playbook.

## 5. Input Contract

- `lidar/*.pcd`, calibration và declared poses.
- Optional `traj_gt.txt` chỉ trong declared offline preprocessing.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- `registered_lidar.ply`.
- Preparation manifest nêu pose/GT dependencies, transforms, filters và checksums.
- Nếu dùng `traj_gt`, field bắt buộc là
  `trajectory_gt_used_for_lidar_prefusion: true` và `assistance_class: GT-assisted`; output không được claim độc lập
  với trajectory GT.
- Hai field trên chỉ thuộc TorWIC preparation manifest. Khi REC-08 publish shared
  artifact, map thành dependency generic `role: pose`, `origin: ground_truth`,
  `source_checksum` và `ground_truth_assisted: true`.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `scripts/torwic/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` workflow dùng Open3D primitives; không đưa raw prefusion vào product runtime.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Audit reproduction 2026-09-27: chạy lại `run_prefusion` với exact request từ
smoke manifest, Open3D 0.19.0 isolated runtime, output mới
`derived/aisle_cw/rec07_audit_20260927`. VERIFIED **54.957 points**, PLY checksum
khớp exact original `sha256:9e6893eee58da41142fe82e3279a862bb6e8a5badf6a3e8688efda2500a1df2b`.
Native coordinate vẫn UNVERIFIED/GT-assisted, không phải RGB alignment proof.
Remaining audit: strict raw scan integrity trước native allocation và canonical
coordinate evidence bridge; không đổi status DONE chỉ từ successful replay.

### Coordinate evidence 2026-09-27 — prefusion 20 frame, axis/unit đo thật

Bổ sung evidence cho canonical coordinate bridge, **không** phải acceptance.
Owner cho phép mở rộng lát cắt smoke từ 5 lên 20 scan. Không sửa code: chạy
`tests/test_reconstruction/smoke/rec07_smoke.py` với env `REC07_SMOKE_*` sẵn có, nên
regression 5-frame cũ giữ nguyên.

**Vì sao chọn frame 100–119:** REC-03/04 đã dựng COLMAP/Brush trên frames
100–200 (`derived/aisle_cw/rec03_smoke_workspace_sub100_200/images/`), nên lát cắt
LiDAR phải nằm trong cùng dải để REC-09 same-scene correspondence có thể dùng.
DATASET_PLAYBOOK §row "Trajectory" khuyến nghị "gộp khoảng 20 LiDAR frames";
20 frame ở đây phủ 1,6m đường đi (toàn traversal 81,1m), nên đây là lát cắt
sắc nét theo playbook, **không** phải bản đồ toàn cửa hàng.

**VERIFIED — chạy thật, Open3D 0.19.0 / NumPy 2.5.3:**
- Command: `REC07_SMOKE_START_FRAME=100 REC07_SMOKE_FRAME_COUNT=20
  REC07_SMOKE_OUTPUT_RELATIVE=derived/aisle_cw/rec07_prefusion_sub100_119
  data/rec07_runtime/bin/python -m tests.test_reconstruction.smoke.rec07_smoke`
- Output: `derived/aisle_cw/rec07_prefusion_sub100_119/`, 20 scan, voxel 0,05 m.
- Point count **133.039** (bản 5-frame: 54.957; gấp 2,42×).
- PLY SHA-256 `4d7cce292587d0d22cf0925ad28c57085c9c10f5007bd1b7dad202d66e6ded4c`
  (3,2 MB). Manifest SHA-256 `f920d2459e1910ff06804e2cbd6f9c9a3d9989a8237fca3ed23fca699146ed83`,
  content checksum `sha256:d9a14b8b3716187f4e36a73183f0a45d9b6566b85418b452beccfda702d57987`.
- Bounds min `[-11.315, -28.173, -0.849]`, max `[15.585, 32.229, 6.139]`;
  mở rộng rõ ở `-y` (bản 5-frame chỉ tới `-17.79`).
- **Determinism:** replay vào `rec07_replay_sub100_119` cho PLY và manifest
  **cùng checksum byte-for-byte**; thư mục replay đã xoá sau khi so, giữ một
  attempt duy nhất.

**VERIFIED — up-axis và unit, đo từ point cloud (nguồn cho coordinate bridge):**
- Trục Z là up: mặt sàn là một mặt phẳng phẳng chứa **38.434 điểm = 28,9%**
  tổng số điểm, tại `z = -0,218 m`, bề dày < 6 cm. Dominant slab theo Z mỏng
  **1,75 cm / 11,8%** điểm, trong khi X là 6,7 cm / 6,9% và Y là 15,1 cm / 4,1%.
  Trục X/Y không có mặt phẳng chiếm ưu thế tương tự.
- Đơn vị mét: quãng cấu hình 50 m, trục Y dài 60,4 m; footprint sàn
  21,7 m × 20,9 m, trần cách sàn ~6,36 m.
- Cross-check quỹ đạo: 1092 pose của `traj_gt.txt` có độ nghiêng khỏi mặt ngang
  **max 2,17° / mean 1,12° / p99 1,86°**; cao độ cảm biến z = 0,171–0,248 m.
  Heading quét 359,6° là yaw bình thường, không phải nghiêng.
- Sàn đọc ra `z ≈ -0,22 m` trong khi world origin z=0 → còn lệch gốc nhỏ cần owner
  chốt quy tắc gốc `world`; **handedness chưa kiểm**, đề xuất test bằng cách chiếu
  điểm 3D qua extrinsic/intrinsics xuống ảnh frame 500.

#### Handedness/up-axis — VERIFIED bằng hai phép đo độc lập 2026-09-27

Owner cho phép kiểm tra up-axis/handedness. Dùng **hai nguồn độc lập**, không
dùng camera extrinsic (xem REC-09 vì sao camera chain chưa verify được):

1. **Merged cloud, world frame:** lát cắn z đậm nhất `z = -0,218 m`, bề dày
   2,15 cm, chứa 37.154 điểm = 27,9% cloud.
2. **Single raw scan `000110.pcd`, os_sensor frame:** lát cắn z đậm nhất
   `z = -0,468 m`, bề dày 2,15 cm, chứa 37.274 điểm = 44,9% scan.

Cộng cao độ cảm biến `z_world ≈ +0,23 m` (traj, 1092 pose) → sàn ở world
`0,23 − 0,468 = -0,238 m`. Hai phép đo từ hai frame khác nhau **khớp nhau trong
2 cm**. Đây là bằng chứng mạnh rằng phép compose `T_world_from_os_sensor` trong
REC-07 giữ đúng trục Z là trục lên và giữ đúng đơn vị mét — nếu sai trục hoặc
sai dấu, hai lát cắn này không thể trùng nhau.

Chốt được: **up-axis = Z, đơn vị = mét, không cần xoay/đảo trục**. Còn lại:
- **handedness (thuận/ngược tay)** chưa chốt. Thử chiếu LiDAR xuống ảnh thì
  phụ thuộc camera chain chưa verify (REC-09), nên chưa dùng được làm chứng cứ.
- **quy tắc gốc `world`**: sàn nằm ở `z ≈ -0,238 m`, không phải 0.

**Evidence trực quan** (gitignored, theo quy ước REC-05):
`data/rec07_axis_evidence_20260927/up_axis_proof.png`
SHA-256 `05c77d10b9726147d014f5b0b335f078c282cdbf46da15cbe05a86d6c03e7d0b`.
Sáu panel: 3 góc nhìn trực giao XY/XZ/YZ, lát cắn đậm nhất theo trục, zoom lát
cắn sàn, và cao độ cảm biến theo thời gian. Người review tự kiểm bằng mắt:
trục Z cho một mặt phẳng nằm ngang sắc ở một giá trị không đổi, X/Y thì không.

**Đối chiếu bằng nguồn độc lập thứ ba — `raw/global/groundtruth_map.ply`:**
Đây là scan thật của cửa hàng (1.065.059 điểm, `VCGLIB`), **không** do REC-07
sinh ra. Đo sàn trong map này cho mặt phẳng đậm ở `z ≈ -0,25 m` — khớp hai phép
đo ở trên trong 1–2 cm. Ba nguồn độc lập (merged cloud của REC-07, raw scan
`000110`, GT map của dataset) đều đặt sàn cùng một cao độ.

**Khoảng cách tới `groundtruth_map.ply` (độc lập, 40.000 điểm thuộc scan
`000110`, frame 110, giới hạn dưới 2,5 m):**

| Biến thể | median | p90 | <0,10 m | <0,25 m |
| --- | --- | --- | --- | --- |
| **H0 khai báo, không đảo** | **0,0592 m** | 0,6003 m | **76,6%** | **82,7%** |
| H1 mirror x | 0,0692 m | 0,8608 m | 68,9% | 76,1% |
| H2 mirror y | 0,0814 m | 0,7516 m | 60,7% | 76,2% |
| H3 mirror z | 0,8410 m | 0,9484 m | 5,7% | 14,7% |
| H4 180° quanh y | 0,8360 m | 0,9430 m | 3,7% | 12,4% |

Chuỗi khai báo khớp GT map tốt nhất, kém hơn biến thể mirror-z/180° tới **14×**.
Đây là test **có phân biệt được** (khác với test chân trời, mù với handedness),
và nó xác nhận chuỗi đọc PCD + áp quaternion + frame là tự nhất quán.

**Handedness — trạng thái thật, không nói quá:** `+Z là lên` là **sự thật vật lý**
(trọng lực: sàn âm, trần dương, cảm biến nghiêng ≤2,17° suốt 81 m). Nhưng
"native frame thuận hay ngược tay" là **quy ước ghi nhãn**, không thể chứng minh
từ dữ liệu nội tại: phản chiếu toàn cục cả pose lẫn map là vô hình với mọi phép
kiểm trên dữ liệu. Nguồn chưa chốt được:
- Ouster OS1-128 hardware convention (x forward, y left, z up) — **chưa tra được**,
  các URL datasheet thử đều 404 và không đoán URL.
- README/PDF của dataset **không** nêu handedness.
- Figure chính thức `Figures/slam_sensor_frames.png` cho **blue = lên** (khớp
  Z-up) nhưng ảnh phối cảnh không phân định được thuận/ngược tay.

→ **Cần owner chốt hoặc cung cấp datasheet Ouster.** Không tự chọn.

**Owner xác nhận 2026-09-27:** Ouster OS1-128 dùng convention `x` forward,
`y` left, `z` up — tức **thuận tay**, trùng với canonical convention của project
(meter, Z-up, right-handed). Hệ quả: **không cần đảo trục nào** khi chuyển native
frame sang canonical `world`; chỉ còn phép tịnh tiến để đặt gốc.

Lưu ý mức độ tin cậy: đây là **owner attestation**, **không phải** agent tự verify
từ nguồn. Agent đã thử tra datasheet Ouster qua nhiền URL và đều 404, không đoán
URL; README/PDF của dataset không nêu handedness; figure phính cảnh không phân
định được. Vì vậy khi khóa `coordinate_status` cần ghi nguồn là owner decision,
**không** ghi là VERIFIED từ tài liệu. Nếu sau này có datasheet hoặc raw ROS
bag/tf_static của chính dataset thì đối chiếu lại và cập nhật nguồn.

**LIMIT — evidence này KHÔNG đổi trạng thái task:**
- `coordinate_status` vẫn `UNVERIFIED`, `assistance_class` vẫn `GT-assisted`,
  `confirmed_rgb_alignment` vẫn `false`. Không tự nâng trạng thái.
- DATASET_PLAYBOOK §"Observed Aisle_CW" ghi `source_frame = os_sensor` là
  *"hypothesis mạnh từ projection/map, chưa được SLAM backend xác nhận trực tiếp"*
  và yêu cầu không biến thành hard fact. Đo trục Z/unit là bằng chứng thực nghiệm
  mạnh nhưng vẫn cần owner review trước khi khóa.
- Code vẫn chặn ở 3 chỗ, chưa đụng: `scripts/torwic/build_registered_lidar.py:31`
  (`coordinate_status="UNVERIFIED"` cứng),
  `src/services/reconstruction/lidar/models.py:31` (`Literal["UNVERIFIED"]`),
  `src/services/reconstruction/lidar/ingest.py:136` (`build_request_from_rec07_manifest`
  raise vô điều kiện). REC-07 giữ `VALIDATING`.
- Validation: `pytest tests/test_reconstruction/ -q` **338 passed, 20 skipped**
  (130,60s); `ruff check src/ tests/ scripts/torwic` pass; `ruff format --check`
  **186 files**. Worktree không có thay đổi code nào.

### Task Capsule / bootstrap 2026-09-26

- Outcome: reproducible offline scan→registered PLY, bằng Open3D primitives,
  không claim đã canonical/confirmed RGB alignment.
- Authority: PRD FR-05/06; Dataset Playbook §13.4, §15 (controlled prefusion);
  Contract §3.5; Track Guide REC-07; Architecture `scripts/torwic/` ownership.
- Baseline: branch `feat/ex-rec`, HEAD `c98df2a`, clean; entrypoint hiện chỉ là
  placeholder. REC-01 source/normalized metadata tồn tại. Raw trajectory là TUM
  timestamp + xyz + xyzw; source-frame hypothesis `os_sensor`, axes UNVERIFIED.
- Inputs: explicit checksum-bound scans/poses/timestamps/calibration và config;
  output: new attempt directory có PLY, manifest, point stats, source/runtime/code
  checksums. Giữ raw input bất biến và không xuất absolute private paths.
- Owned: `scripts/torwic/`, EX-REC tests, task/active plan. Không sửa raw/GT,
  shared schemas, app dependency locks, other tracks hoặc source-frame evidence.
- Reuse audit: Open3D **0.19.0**, MIT, `isl-org/Open3D` v0.19.0;
  [license](https://raw.githubusercontent.com/isl-org/Open3D/v0.19.0/LICENSE),
  [read_point_cloud](https://www.open3d.org/docs/0.19.0/python_api/open3d.io.read_point_cloud.html),
  [PointCloud](https://www.open3d.org/docs/0.19.0/python_api/open3d.geometry.PointCloud.html).
  REUSE PCD/PLY IO, transform and voxel downsample; NumPy arrays/sort. SELF-CODE
  orchestration, timestamp/identity checks, manifest/immutable publication. Không
  copy research modules, tự viết odometry hoặc đưa toàn dependency vào app env.
- Runtime riêng `data/rec07_runtime`; app `.venv` không có Open3D/NumPy. Disk
  còn khoảng 7.8 GiB ở bootstrap: bắt đầu small smoke, bound point budget,
  không chạy full sequence trước khi biết memory/output size.
- Sequence: typed request/path/pose validation → Open3D bounded workflow → CLI
  và immutable manifest → tests synthetic + real small-sequence reproducibility.
- Proof: missing/stale source, path escape, undeclared GT, timestamp/frame
  mismatch, bad quaternion/nonfinite/empty cloud đều reject; known transform
  đúng chiều, sorted output deterministic, rerun cùng input hash bằng nhau;
  existing attempt không overwrite. Real GT-assisted output ghi nhãn đúng.
- Unknown: full canonical axes và RGB correspondence chưa confirmed; không chặn
  offline prefusion trong explicitly declared native frame, nhưng không được
  nâng output đó thành unified metric scene.

## 10. Tests

- Transform/merge/filter unit tests.
- Missing pose/frame metadata negative test.
- Small scan sequence prefusion smoke và reproducibility check.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Output tái tạo được từ immutable raw input.
- [x] Mọi use của `traj_gt` được khai báo rõ.
- [x] Artifact không được claim là independent LiDAR mapping benchmark khi methodology không cho phép.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

Audit 2026-09-27: focused/offline subset proof có, nhưng source coordinate review
→ REC-08 canonical ingest handoff chưa hoàn tất. Status giữ VALIDATING.

## 12. Result / Evidence

### Evidence 2026-09-26 — REC-07 Hoàn thành (DONE)

1. **Unit & Contract Tests:**
   - File test: `tests/test_reconstruction/test_rec07_prefusion.py`
   - Command: `pytest tests/test_reconstruction/test_rec07_prefusion.py -v`
   - Kết quả: **9 passed in 18.04s** (100% pass).
   - Kiểm thử: path traversal rejection, frame ID mismatch rejection, GT declaration requirements, output directory boundary (`derived/`), checksum tamper detection, unnormalized quaternion rejection, desynchronized timestamp detection, CLI invocation, và tính đơn định (deterministic SHA-256 byte-for-byte reproducibility).

2. **Real-Tool Smoke Execution trên Aisle_CW:**
   - Script: `tests/test_reconstruction/smoke/rec07_smoke.py`
   - Command: `data/rec07_runtime/bin/python -m tests.test_reconstruction.smoke.rec07_smoke`
   - Input: Scans 100 đến 104 (`raw/traversals/aisle_cw/lidar/00010[0-4].pcd`, 262.144 points/scan từ cảm biến Ouster OS1-128).
   - Output directory: `data/torwic_slam/derived/aisle_cw/rec07_smoke_sub100_104/`
   - Output files:
     - `registered_lidar.ply` (1.3 MB, checksum: `sha256:9e6893eee58da41142fe82e3279a862bb6e8a5badf6a3e8688efda2500a1df2b`)
     - `preparation_manifest.json` (checksum: `sha256:f002903e21078da945da81f3ac88241b293dfae8287c7751896292ee3a5fcfd5`)
   - Thống kê mây điểm:
     - Tổng điểm hợp nhất (sau voxel filter $0.05\text{m}$): **54.957 điểm**.
     - Bounds min: `[-11.1444, -17.7897, -0.5411]` mét.
     - Bounds max: `[14.2995, 32.1617, 6.1304]` mét.
     - Minh bạch provenance: `assistance_class: "GT-assisted"`, `trajectory_gt_used_for_lidar_prefusion: true`.
