# Handoff — EX-REC coordinate audit (opencode → Codex)

| | |
| --- | --- |
| **Ngày** | 2026-09-27 |
| **Giờ** | 09:49 – 10:47 (+07) |
| **Tác giả commit** | Lâm Quang Anh Quân `<quanlam0105@gmail.com>` |
| **Agent thực hiện** | opencode, làm theo yêu cầu owner trong phiên chat |
| **Track** | EX-REC — `@awun0105` (track owner) |
| **Branch** | `feat/ex-rec-pipeline` |
| **Base commit trước phiên** | `45db57e` |
| **4 commit phân tích** | `c1fe3f6` → `5713976` |
| **Commit của chính file handoff này** | commit kế tiếp sau `5713976`, docs-only |
| **Phạm vi** | Read + audit + chạy real tool. **Không sửa code.** Không push/merge/đổi branch. |

## Mốc thời gian trong phiên

| Giờ | Việc | Commit |
| --- | --- | --- |
| 09:45 | Chạy prefusion 20 scan (frame 100–119) | — |
| 09:46 | Xác minh checksum, replay byte-identical | — |
| 09:49 | Ghi evidence REC-07 + plan | `c1fe3f6` |
| 10:00 | Chốt up-axis 2 phép đo; ghi lỗ hổng camera chain | `a713d7e` |
| 10:20 | Tra dataset repo local, tìm ra nguyên nhân (ảnh đã undistorted) | — |
| 10:29 | Giải camera chain; chốt up-axis 3 nguồn | `4078686` |
| 10:37 | Owner chốt handedness | `5713976` |
| 10:47 | Viết handoff này | commit của file này |

## Nguồn của các quyết định trong phiên

| Nội dung | Ai quyết |
| --- | --- |
| Chạy prefusion 20 frame thay 5 frame | **Owner** yêu cầu |
| Up-axis = +Z, đơn vị = mét | Agent đo, **owner review** |
| `image_left/*.png` đã undistorted | Agent đo và chứng minh bằng 11 frame |
| Ouster OS1-128 thuận tay, không đảo trục | **Owner xác nhận** (không phải agent verify) |
| Giữ nguyên `Status` các task, không nâng | Agent, theo harness lifecycle |

> **Đây là snapshot một lần, KHÔNG phải nguồn status sống.** Trạng thái chính
> thứ vẫn nằm ở `tasks/REC-*.md` (mục `Status` + `Result/Evidence`) và
> `docs/plans/active/2026-09-24-ex-rec-track.md`. Khi hai chỗ lệch nhau, hai chỗ
> đó thắng. File này chỉ để một agent mới nắm nhanh bối cảnh phiên vừa rồi.

## 0. Trạng thái repo lúc bàn giao

- Worktree **sạch**. **Không sửa một dòng code nào** trong phiên này.
- Baseline chạy lại lúc bàn giao:
  - `pytest tests/test_reconstruction/ -q` → **338 passed, 20 skipped** (119,85s)
  - `ruff check src/ tests/ scripts/torwic` → pass
  - `ruff format --check src/ tests/ scripts/torwic` → **186 files**

### Cảnh báo môi trường

`.venv` **thiếu numpy** → `pytest tests/` collect được 494 test rồi **đứng** vì
`tests/test_simulation/test_colliders.py:5` lỗi `ModuleNotFoundError`. Đây là
vấn đề môi trường, **không phải lỗi code**, và nằm ngoài ownership EX-REC. Cần
vá trước khi chạy full suite.

## 1. Commit của phiên này (4, đều docs-only)

| Commit | Nội dung |
| --- | --- |
| `c1fe3f6` | Chạy prefusion 20 scan + đo trục up/unit |
| `a713d7e` | Chốt up-axis Z bằng hai phép đo; **ghi lỗ hổng** camera chain (chưa giải) |
| `4078686` | **Giải camera chain** — ảnh đã undistorted; chốt up-axis 3 nguồn; tra dataset docs |
| `5713976` | Owner chốt handedness (thuận tay) |

File sửa: `tasks/REC-07.md` (+133), `tasks/REC-09.md` (+107),
`../../plans/active/2026-09-24-ex-rec-track.md` (+100). Tổng **+340 dòng, 0 xoá**.

## 2. File tạo mới (đều gitignored, không có trong git)

`.gitignore:32` ignore `data/`. Agent sau **phải tự sinh lại**, đừng tìm trong git.

### `data/rec07_prefusion_sub100_119/`

| File | Size | SHA-256 |
| --- | --- | --- |
| `registered_lidar.ply` | 3,2 MB | `4d7cce292587d0d22cf0925ad28c57085c9c10f5007bd1b7dad202d66e6ded4c` |
| `preparation_manifest.json` | 9,4 KB | `f920d2459e1910ff06804e2cbd6f9c9a3d9989a8237fca3ed23fca699146ed83` |

Manifest content checksum: `sha256:d9a14b8b3716187f4e36a73183f0a45d9b6566b85418b452beccfda702d57987`

Lệnh sinh lại (không sửa code, dùng env có sẵn trong `tests/test_reconstruction/rec07_smoke.py`):

```bash
REC07_SMOKE_START_FRAME=100 \
REC07_SMOKE_FRAME_COUNT=20 \
REC07_SMOKE_OUTPUT_RELATIVE=derived/aisle_cw/rec07_prefusion_sub100_119 \
data/rec07_runtime/bin/python -m tests.test_reconstruction.rec07_smoke
```

### `data/rec07_axis_evidence_20260927/`

| File | SHA-256 | Nội dung |
| --- | --- | --- |
| `up_axis_proof.png` | `05c77d10b9726147d014f5b0b335f078c282cdbf46da15cbe05a86d6c03e7d0b` | 6 panel: 3 góc nhìn trực giao XY/XZ/YZ, lát cắn đậm nhất theo trục, zoom lát cắn sàn, cao độ cảm biến theo thời gian |
| `scan110_hypotheses.png` | `bb0085a058fbdeb7b42a58266c53485db6ecdd98f24fcb58eacf64b2780678e5` | 5 giả thuyết chồn lên ảnh thật (giai đoạn camera chain chưa giải) |
| `camera_chain_final.png` | `97dcbf2e242cc5b64434fa36789470183a26e94c1c666e808c163369a123664c` | raw scan `000110` chồn ảnh thật; chuỗi đúng dừng đúng ở vạch sàn vàng, biến thể sai rõ ràng |
| `dataset_official_sensor_frames.png` | `7e803b2ed82a026969b1756edba50e0d435fe32c9b586f45469a745a0ad6cc9b` | copy từ dataset repo `Figures/slam_sensor_frames.png` |

## 3. Phát hiện quan trọng nhất — cần hành động

> **`data/torwic_slam/normalized/aisle_cw/rgb_frames/*.png` ĐÃ LÀ ẢNH
> UNDISTORTED.** Hệ số `Camera1.D` trong `raw/global/calibrations.txt` **KHÔNG
> được áp** lên các ảnh này.

Chuỗi camera đúng:

```text
T_cam_from_os = inverse(T_os_from_cam)
  → frame camera theo OpenCV optical (x phải, y xuống, z trước)
  → KHÔNG áp distortion
```

Bằng chứng — residual chân trời (mặt sàn phải hội tụ về một đường ngang), đo trên
11 frame rải khắp traversal `100, 105, 110, 115, 119, 300, 450, 500, 700, 900,
1050`:

| | residual |
| --- | --- |
| Có áp distortion | 49,8 – 65,7 px (TB **57,8**) |
| Không áp | 5,0 – 7,1 px (TB **5,9**) |

Cải thiện **10×**, nhất quán cả 11 frame. Nghiêng suy ra từ sàn là `+2,93°`, khớp
`3,27°` mà extrinsic khai báo.

**Việc chưa làm, nên làm tiếp:** chưa có regression test khoá hành vi này. Bất kỳ
code chiếu/align LiDAR↔RGB nào áp `D` sẽ lệch hàng chục pixel. Đây là rủi ro
regression thật do phát hiện này mở ra.

Chi tiết đầy đủ: `tasks/REC-09.md` §"ĐÃ GIẢI 2026-09-27".

## 4. Đã xác nhận được

### Up-axis = +Z, đơn vị = mét

Ba nguồn độc lập, tất cả đặt mặt sàn cùng một cao độ:

| Nguồn | Frame | Giá trị sàn | Tỉ lệ điểm |
| --- | --- | --- | --- |
| Merged cloud 20 scan | world | z = **−0,218 m** | 27,9% (37.154) |
| Raw scan `000110.pcd` | os_sensor | z = **−0,468 m** | 44,9% (37.274) |
| `raw/global/groundtruth_map.ply` | world | z ≈ **−0,25 m** | 301.094 trong lát 0–0,3 m |

Cộng cao độ cảm biến `+0,218 m` (1092 pose, biên độ chỉ 7,6 cm) → sàn world
≈ `−0,238 m`. Ba cách đo khớp nhau trong 1–2 cm. Nếu sai trục hoặc sai dấu thì
không thể trùng nhau.

Trục Z là up còn xác nhận thêm bằng: lát cắn z đậm nhất **1,75 cm / 11,8%** điểm,
mỏng và đậm hơn X (6,7 cm / 6,9%) và Y (15,1 cm / 4,1%); 1092 pose nghiêng khỏi
mặt ngang max 2,17° / mean 1,12° / p99 1,86° (heading 359,6° là yaw bình thường).

### Chuỗi pose + scan tự nhất quán, khớp GT map

40.000 điểm thuộc scan `000110` (frame 110), giới hạn dưới 2,5 m, khoảng cách tới
bề mặt `raw/global/groundtruth_map.ply`:

| Biến thể | median | p90 | <0,10 m | <0,25 m |
| --- | --- | --- | --- | --- |
| **H0 khai báo, không đảo** | **0,0592 m** | 0,6003 m | **76,6%** | **82,7%** |
| H1 mirror x | 0,0692 m | 0,8608 m | 68,9% | 76,1% |
| H2 mirror y | 0,0814 m | 0,7516 m | 60,7% | 76,2% |
| H3 mirror z | 0,8410 m | 0,9484 m | 5,7% | 14,7% |
| H4 180° quanh y | 0,8360 m | 0,9430 m | 3,7% | 12,4% |

Chuỗi khai báo khớp nhất, kém hơn biến thể mirror-z tới **14×**. Test này **có
phân biệt được** (khác với test chân trời, mù với handedness vì mặt phẳng sàn vẫn
cho một đường chân trời dù đảo trục nào).

### Prefusion 20 scan chạy thật, deterministic

133.039 điểm (gấp **2,42×** bản smoke 5 scan trước đó: 54.957). Replay vào
thư mục khác cho PLY và manifest **cùng checksum byte-for-byte**; thư mục replay đã
xoá sau khi so.

Chọn frames 100–119 vì REC-03/04 đã dựng COLMAP/Brush trên frames 100–200
(`derived/aisle_cw/rec03_smoke_workspace_sub100_200/images/`), cùng dải để REC-09
same-scene correspondence dùng được. Số 20 theo khuyến nghị DATASET_PLAYBOOK.
20 frame này phủ 1,6 m đường đi (toàn traversal 81,1 m) — là lát cắt sắc nét theo
playbook, **không** phải bản đồ toàn cửa hàng.

Runtime: Open3D 0.19.0 + NumPy 2.5.3 trong `data/rec07_runtime`.

## 5. Nguồn đã tra (dataset repo local)

Owner cấp `private/TorWICDataset` @ `5e1839f`:

| Nguồn | Nội dung dùng được |
| --- | --- |
| `Figures/slam_sensor_frames.png` | Azure Kinect **xanh = phải, lục = xuống, đỏ = trước** ⇒ optical/OpenCV. Ouster **xanh = lên** ⇒ Z-up. |
| `README:235` | *"The poses (of the mounted Ouster OS1-128 LiDAR) were obtained by **aligning the 3D scans against the ground-truth 3D map**"* — đây là nguồn gốc giả thuyết `os_sensor` mà `DATASET_PLAYBOOK` ghi là *"hypothesis mạnh từ projection/map, chưa được SLAM backend xác nhận trực tiếp"*. |
| `README:219` | *"The robot always starts at the origin of our map frame"* — kết hợp sàn đo được ở `z ≈ −0,24 m` ⇒ **z=0 của map frame không phải mặt sàn**. |
| `README:161` | `depth_left/right` là **RGB-aligned depth**; checkout hiện tại **không có** thư mục depth. |
| `TorWIC_Dataset.pdf` | Mô tả kịch bản localization (rào, thùng), **không** mô tả convention. |

### Cảnh báo: `utils/calibration.py` là scenario KHÁC

File đó là cho **localization scenario** khác: `base_link`, RealSense D435i, Hokuyo
UAM501, 640×360, `D = [0,0,0,0,0]`, intrinsics `fx=461,10` / `cx=325,48`. **KHÔNG**
phải bộ calibration của dữ liệu SLAM mà ta có (`os_sensor` / `azure_left_camera`,
1280×720, `fx=621,40` / `cx=649,64`, `D≠0`). Tuyệt đối không lấy nhầm.

### Owner đã chốt

Ouster OS1-128 dùng convention `x` forward, `y` left, `z` up ⇒ **thuận tay**, trùng
canonical convention của project (meter, Z-up, right-handed). Hệ quả: **không cần
đảo trục nào** khi chuyển native frame sang canonical `world`; chỉ còn phép tịnh
tiến để đặt gốc.

**Mức độ tin cậy — quan trọng:** đây là **owner attestation, KHÔNG phải agent
verify**. Đã thử nhiều URL datasheet Ouster và đều 404, không đoán URL; README/PDF
của dataset không nêu handedness; figure phối cảnh không phân định được thuận/ngược
tay. Khi khóa `coordinate_status`, **ghi nguồn là owner decision, đừng ghi
"VERIFIED từ tài liệu"**. Nếu sau này có datasheet hoặc raw ROS bag / `tf_static` của
chính dataset thì đối chiếu lại và cập nhật nguồn.

## 6. Trạng thái task — không đổi trong phiên này

| Task | Status |
| --- | --- |
| REC-01, REC-02, REC-02A, REC-03, REC-04 | `DONE` |
| REC-07 | `VALIDATING` |
| REC-05, REC-06, REC-08, REC-09, REC-10, REC-11 | `IN_PROGRESS` |

Không task nào được nâng status. `coordinate_status` vẫn `UNVERIFIED`,
`assistance_class` vẫn `GT-assisted`, `confirmed_rgb_alignment` vẫn `false`.

## 7. Việc tiếp theo

### Làm được ngay, không cần owner

1. Vá `.venv` thiếu numpy → mở full suite.
2. Viết regression test khoá hành vi "không áp `D` lên ảnh đã undistorted".

### Chặn, cần owner quyết

3. **Quy tắc gốc `world`** — sàn ở `z ≈ −0,24 m`. Đặt sàn = z 0, hay giữ nguyên
   và khai báo rõ?
4. **2 cặp điểm A/B** trên LiDAR đã căn chỉnh — một cặp để tính scale, một cặp
   khác để kiểm chứng độc lập (ADR 0001: không dùng chung một measurement).
5. **`tolerance_m`** — hiện hardcode `0.05` tại
   `src/services/reconstruction/rgb/metric_verification.py:24`; PRD §11.4 câu 4
   vẫn `TBD`.
6. **Capsule robot** — `tasks/REC-05.md` chỉ có số demo `radius=0.35 m`,
   `height=1.20 m`, chưa phải số khóa.

Xong 3–6 → mở REC-06 → REC-05 real metric spike → REC-10/11 production verifier.

### Ba chỗ code đang chặn promote (chưa đụng)

- `scripts/torwic/build_registered_lidar.py:31` — `coordinate_status="UNVERIFIED"` cứng
- `src/services/reconstruction/lidar/models.py:31` — `Literal["UNVERIFIED"]`, type không cho giá trị khác
- `src/services/reconstruction/lidar/ingest.py:136` — `build_request_from_rec07_manifest` raise vô điều kiện

Cần owner duyệt trước khi mở. Đây là thay đổi behavior, không phải refactor.

## 8. Sai lệch docs cần biết

1. **DoD checkbox sai.** Sáu task file đã tick `[x]` hết ở các commit
   `feat(rec): hoàn thành` (2026-09-26); đợt audit chỉ revert `Status` về
   `IN_PROGRESS` mà **không bỏ tick DoD**. Đọc `Status` + `Result/Evidence`,
   **đừng dùng DoD checkbox làm bằng chứng**.
2. **Plan stale.** `docs/plans/active/2026-09-24-ex-rec-track.md` cuối file còn ghi
   *"REC-02 through REC-11 have all been completed"* + "274 passed" — mâu thuẫn
   checkpoint ở đầu `## Outcome`. Phần cuối đó là lịch sử, không phải trạng thái.
3. **Lỗi ngoài EX-REC.** `tests/test_contracts/test_identity.py` fail 2 case
   (SceneIR checksum). Cả file test lẫn `src/models/contracts/identity.py` chỉ
   bị sửa bởi commit foundation `49f2456`, **không** do EX-REC. Ngoài ownership.

## 9. Bối cảnh sản phẩm để khỏi đề xuất sai

- **`frontend/` chưa tồn tại.** `src/api/routes.py` chỉ có 2 route: `/chat`,
  `/status` — không có route reconstruction nào.
- **EX-PRODUCT: 13/13 task `TODO`.** UI là PRODUCT-05/06, tức task cuối.
- **EX-SIM: 2 `DONE` / 8 `TODO`.** Isaac validation chưa bắt đầu.
- **`tests/e2e/` rỗng** — chưa có test E2E nào.
- Thứ tự đúng: `REC → SCENE → SIM → PRODUCT`.
- **P0 không cần CUDA.** REC-03 COLMAP có toggle CPU/GPU; REC-04 Brush đã chạy
  thật trên Intel UHD 630; REC-05 voxel dùng WebGPU và đã chạy ở index 0. Chỉ
  AI auto-scale (ADR 0001 §P1) và Isaac Sim mới cần NVIDIA — **đừng thuê GPU host
  vì lý do EX-REC**.

## 10. Cách tái lập các phép đo trong handoff này

Mọi script phân tích nằm ở `/tmp/opencode/` và **không tồn tại sau restart**. Nếu
cần tái lập hoặc kiểm chứng lại:

- Đọc PLY không cần Open3D: file `binary_little_endian 1.0`, offset =
  `raw.index(b"end_header\n") + len(b"end_header\n")`, shape `(N, 3)`, dtype `<f8`.
- Cần NumPy + Open3D thì dùng `data/rec07_runtime/bin/python` (Open3D 0.19.0,
  NumPy 2.5.3, scipy 1.18.1, matplotlib, PIL). `.venv` thiếu numpy.
- Đọc GT map bằng `open3d.io.read_point_cloud` (1.065.059 điểm); **không** parse
  thủ công — header `end_header` không có newline cuối và offset thủ công dễ sai.
- Camera: parse `calibrations.txt` tách cả dòng số **và** `Camera1.D` ( là list,
  không parse được bằng `float()`).

## Validation của chính phiên này

- `pytest tests/test_reconstruction/ -q` → 338 passed, 20 skipped
- `ruff check src/ tests/ scripts/torwic` → pass
- `ruff format --check src/ tests/ scripts/torwic` → 186 files
- `git diff 45db57e..HEAD -- src/ tests/ scripts/` → **rỗng**, xác nhận không sửa code
- Không push, không merge, không đổi branch
