# REC-09 — RGB-LiDAR Alignment

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | `@awun0105` |
| Target milestone | `M2/M4` |


## 2. Goal

Xác nhận transform giữa same-scene RGB và LiDAR artifacts mà không mutate source artifacts.

## 3. Why This Task Exists

Mixed scene không được gọi unified/metric-ready trước confirmed alignment.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- REC-03/04 same-scene RGB artifacts cho preparation/đối chiếu metric trước REC-05.
- REC-06 metric derivative và REC-05 RGB geometry cho final shared AlignmentRecord
  bind `target_rgb_geometry_checksum`; không yêu cầu REC-06 DONE để bắt đầu preparation.
- REC-08 LiDARGeometryArtifact.
- Authority/config xác định known or user-confirmed transform; automatic sensor alignment không phải P0.

## 5. Input Contract

- Immutable same-scene RGB artifact refs/checksums.
- Immutable LiDARGeometryArtifact.
- Calibration/known transform hoặc approved confirmation input.
- TorWIC raw label `T_cam1_os` phải normalize thành `T_os_from_cam`; LiDAR→camera
  dùng inverse. `os_sensor` vẫn là source-frame hypothesis, phải record evidence.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Confirmed alignment transform/record riêng.
- Overlap/same-scene checks và alignment provenance.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/alignment/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` + Open3D transform/registration primitives; P0 không hứa automatic sensor alignment.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

Audit/rework 2026-09-27: `0629a6e` defaults CONFIRMED và chỉ kiểm caller booleans,
không resolve source/evidence. Sensor extrinsic không cung cấp world alignment.
Theo Contract §3.5/§4 và Re3Sim frame composition: giữ sensor frame labels đúng,
chỉ compose khi connecting frames khớp; injected confirmation verifier + byte
resolver bắt buộc, default DECLARED, evidence bind vào immutable record payload.
Thêm negative tests trước khi sửa, rồi focused/broader tests; old DONE summary
bên dưới là lịch sử chưa qua audit, không phải nghiệm thu hiện tại.

Ordering clarification 2026-09-26: cùng REC-07/08 chuẩn bị LiDAR/correspondence
cho ba demo modes của ADR 0001 trước real REC-05. Measurement/alignment preparation
không phải final shared AlignmentRecord. Record cuối vẫn bind hai geometry refs
đúng Contract §3.5; không encode similarity scale vào shared rigid Transform.
Task vẫn TODO cho implementation; thay dependency không là evidence đã alignment.

Assignee điền sau khi inspect code/test hiện tại: files cụ thể, sequence, failure handling và proof. Không đổi goal, I/O hoặc authority gate của task.

## 10. Tests

- Transform composition/unit tests.
- Different-scene and unconfirmed-transform negative tests.
- Known-transform alignment fixture và non-mutation test.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [ ] Same-scene identity/checksums được verify.
- [x] Confirmed record tách khỏi immutable LiDAR artifact.
- [x] Composer/downstream trace được transform và source artifacts.
- [ ] Focused tests và required handoff proof pass; evidence/limitations được ghi.

Audit 2026-09-27: source/ref validators và synthetic reviewer có tests; physical
RGB–LiDAR correspondence/real confirmation chưa có. Checked items không thay
same-scene measurement evidence của Aisle_CW.

## 12. Result / Evidence

### 2026-09-29 — căn chỉnh SfM → world bằng quỹ đạo camera (GT-assisted, dataset demo)

Quyết định owner 2026-09-29 (ADR 0004 §5): trên dataset mẫu, khoảng cách A/B, C/D
lấy từ LiDAR thay vì người dùng tự đo; cần căn chỉnh 3DGS ↔ LiDAR. Chọn căn chỉnh
theo quỹ đạo camera vì chính xác (hàng chục cặp điểm) và không thêm thao tác tay.

- Code: `alignment/similarity.py` (Umeyama, chặn phản xạ, từ chối suy biến);
  `scripts/torwic/align_sfm_to_world.py` (ghép frame theo nội dung ảnh + kiểm dãy
  đều → tâm camera map = `T_map_from_os(i)·t_os_from_cam` → cầu nối world → fit).
- **GT-assisted:** đọc `traj_gt.txt` ở bước chuẩn bị dataset theo DATASET_PLAYBOOK;
  chỉ cho demo/integration, không claim độ chính xác RGB-only.
- Chạy thật trên `job-ac2bfd924cc6` (video `aisle_cw_200.mp4`): frame video `f` ↔
  ảnh dataset `f + 100` (frame 100–299), khớp đúng dãy đều. 50 cặp tâm camera,
  quỹ đạo 16,68 m (bề ngang 14,14 m): scale **1,2062 m/đơn vị SfM**, residual
  trung vị **4,4 cm**, p90 9,4 cm, RMS **6,8 cm**, max 20,5 cm (frame 88/92/199).
  Output `data/torwic_slam/derived/aisle_cw/rec09_alignment_job-ac2bfd924cc6/alignment.json`
  (`sha256:0f340050…`, git-ignored).
- Test: `test_rec09_similarity_fit.py` (3), `test_rec09_trajectory_alignment.py` (2) pass.
- Chưa làm: publish alignment + LiDAR (REC-08) vào store của job; bắt điểm click vào
  point cloud LiDAR để ra khoảng cách; bản ghi AlignmentRecord chính thức.


### Audit correction 2026-09-27 — implementation, chưa real acceptance

- VERIFIED: bốn regression tests đã fail trên code cũ (auto-CONFIRMED,
  publish không resolver/authority, relabel extrinsic thành world, zero quaternion).
  Đã sửa bằng default DECLARED, injected verifier/resolver bắt buộc, byte checks
  cho sources/evidence và immutable record chứa full reviewed request.
- Sensor calibration giữ `os_sensor`/`azure_left_camera`; world alignment cần
  compose transform có connecting frames đúng. Reuse math của local metric module,
  tham chiếu frame composition Re3Sim `frame_tools.py`, không copy dependency graph.
- Added tamper/reload/provenance guards, nontrivial rotation/translation tests.
  `pytest tests/test_reconstruction/test_rec09*.py tests/test_reconstruction/test_rec10_bundle.py -q`:
  **22 passed**; `pytest tests/test_reconstruction/ -q`: **293 passed, 11 skipped**.
  Ruff check/format toàn `src/ tests/ scripts/torwic` pass (177 files).
- LIMIT: verifier positive là synthetic fixture rõ nhãn, không phải physical
  same-scene/overlap proof cho Aisle_CW. Task vẫn IN_PROGRESS; các claim world
  normalization/DONE trong historical checkpoint dưới đây đã bị audit bác bỏ.

### Phát hiện 2026-09-27 — camera chain KHÔNG verify được bằng ground truth sàn

Owner cho phép kiểm tra handedness/up-axis. **Up-axis đã chốt được** (xem REC-07:
Z là trục lên, đơn vị mét, hai phép đo độc lập khớp trong 2 cm). Nhưng cách kiểm
tra bằng cách chiếu LiDAR xuống ảnh RGB **đã lộ ra một vấn đề riêng**, ghi lại
đây vì nó thuộc scope REC-09 chứ không phải REC-07.

**Cách kiểm:** chiếu raw scan `000110.pcd` (đúng frame, ở `os_sensor` frame, không
cần pose/gộp) vào ảnh `000110.png` bằng chuỗi khai báo
`T_cam_from_os = inverse(T_os_from_cam)` + intrinsics + distortion OpenCV
`[k1,k2,p1,p2,k3]`. Ảnh đúng 1280×720 khớp calibration, nên không phải lỗi resize.

**Kết quả — không khớp:**
- Extrinsic khai báo: trục quang học camera trong sensor frame là
  `(-0.0246, -0.9981, -0.0571)`, tức nhìn gần như dọc **−Y** của sensor, nghiêng
  **3,27°**.
- Mặt sàn trong ảnh phải hội tụ về một đường chân trời ngang. Fit `v = v_h + a/d`
  trên 13.110 điểm sàn cho `v_h = 470,6 px` → nghiêng ngầm **−9,48°**, residual
  **60,7 px**. Không khớp 3,27°, và residual 60 px là lớn.
- Giả thuyết không inverse (`T_os_from_cam` thẳng) tệ hơn: `v_h = 454,7`,
  residual **164,2 px**.
- Chấm điểm khớp cấu trúc ảnh (mean image-gradient tại điểm chiếu / baseline):
  khai báo **0,803** (dưới baseline 1,0), không-inverse 1,183, mirror-y 1,373.
  Chỉ số này yếu vì cảnh kho gần đối xứng, nên lấy số residual chân trời làm
  tiêu chí chính.

**Điều này KHÔNG chứng minh calibration sai.** Các giả thuyết còn sống, chưa loại:
ảnh `image_left` có thể đã undistorted sẵn (thử "bỏ distortion" → ratio 0,781,
tệ hơn, nên chưa loại trừ hoàn toàn); Ouster OS1-128 có origin offset riêng cần
đặt đúng; hoặc khung camera thật sự không phải OpenCV z-forward.

**Hệ quả trực tiếp:** **không dùng được đường chiếu LiDAR→ảnh làm bằng chứng
handedness cho tới khi camera chain verify.** Vì vậy REC-07 chỉ chốt được
up-axis/unit, còn handedness vẫn để mở. REC-09 vẫn `IN_PROGRESS`.

**Evidence:** `data/rec07_axis_evidence_20260927/scan110_hypotheses.png`
SHA-256 `bb0085a058fbdeb7b42a58266c53485db6ecdd98f24fcb58eacf64b2780678e5`
(5 giả thuyết chồn lên ảnh + ảnh gốc).

### ĐÃ GIẢI 2026-09-27 — nguyên nhân là ảnh đã undistorted sẵn

Owner cung cấp dataset repo local (`private/TorWICDataset`, commit `5e1839f`) để
tra tài liệu. **Giả thuyết "ảnh đã undistorted sẵn" là đúng**, và nó là nguyên
nhân duy nhất của sai lệch 57,8 px ở trên.

**Bằng chứng định lượng — residual chân trời trên 11 frame rải khắp traversal:**

| frame | n điểm sàn | residual CÓ distortion | residual KHÔNG distortion |
| --- | --- | --- | --- |
| 100 | 9.845 | 53,2 px | **5,0 px** |
| 105 | 9.631 | 49,8 px | **5,0 px** |
| 110 | 10.672 | 56,7 px | **5,3 px** |
| 115 | 11.000 | 59,6 px | **5,7 px** |
| 119 | 8.321 | 61,2 px | **5,6 px** |
| 300 | 8.941 | 58,5 px | **7,1 px** |
| 450 | 7.367 | 65,7 px | **7,0 px** |
| 500 | 12.078 | 53,5 px | **5,3 px** |
| 700 | 9.905 | 53,8 px | **5,7 px** |
| 900 | 13.169 | 61,1 px | **6,6 px** |
| 1050 | 8.151 | 62,6 px | **6,6 px** |
| **TB** | | **57,8 px** | **5,9 px** |

Cải thiện **10×**, nhất quán trên cả 11 frame. Với residual 5,9 px, nghiêng suy
ra từ sàn là `+2,93°`, khớp `3,27°` mà extrinsic khai báo.

**Kết luận chuỗi camera (đã verify):**
`T_cam_from_os = inverse(T_os_from_cam)` → frame camera theo **OpenCV optical**
(x phải, y xuống, z trước) → **KHÔNG** áp `D`. Cụ thể:

> **`image_left/*.png` đã là ảnh undistorted. Hệ số `Camera1.D` trong
> `calibrations.txt` KHÔNG được áp lên các ảnh này.**

Đây là kết luận có tác động thật: bất kỳ code nào chiếu/align LiDAR↔RGB mà áp
`D` sẽ lệch hàng chục pixel. Cần có regression test khoá hành vi này.

**Quy ước camera frame — có nguồn chính thức:** Figure
`Figures/slam_sensor_frames.png` của dataset vẽ mũi tên trục RGB. Đọc được:
Azure Kinect **xanh = phải, lục = xuống, đỏ = trước** ⇒ đúng optical/OpenCV
convention. Ouster OS1-128 **xanh = lên** ⇒ khớp Z-up đã đo. Figure này được
copy vào `data/rec07_axis_evidence_20260927/dataset_official_sensor_frames.png`
(`7e803b2e…`) để review.

**Tin tức dataset liên quan tới gốc `world`:** README dòng 235 — *"The poses (of
the mounted Ouster OS1-128 LiDAR) were obtained by **aligning the 3D scans
against the ground-truth 3D map**"*. Đây chính là nguồn gốc của giả thuyết
`os_sensor` mà DATASET_PLAYBOOK ghi là "hypothesis mạnh từ projection/map": pose
đến từ scan-to-map alignment, không phải từ SLAM backend xác nhận trực tiếp.
README dòng 219 — *"The robot always starts at the origin of our map frame"*;
đo được LiDAR ở `z = +0,218 m` và sàn ở `z ≈ -0,24 m`, nên **z=0 của map frame
không phải mặt sàn** mà cao hơn sàn ~0,24 m. Việc này giải thích độ lệch đo được
và cho owner một căn cứ để chốt quy tắc gốc.

**Cảnh báo về `utils/calibration.py` trong dataset repo:** file đó là cho
**scenario localization khác** — `base_link`, RealSense D435i, Hokoyo UAM501,
640×360, `D = [0,0,0,0,0]`, intrinsics `fx=461,10` / `cx=325,48`. **KHÔNG** phải
bộ calibration của dữ liệu SLAM mà ta có (`os_sensor` / `azure_left_camera`,
1280×720, `fx=621,40` / `cx=649,64`, `D≠0`). Tuyệt đối không lấy nhầm.

**Còn mở:** handedness thuần/ngược tay của native frame vẫn chưa chốt (lý do và
các nguồn chưa có ở mục REC-07); đây là quy ước ghi nhãn, không chứng minh được
từ dữ liệu nội tại.

**Evidence:** `data/rec07_axis_evidence_20260927/camera_chain_final.png`
SHA-256 `97dcbf2e242cc5b64434fa36789470183a26e94c1c666e808c163369a123664c`
(raw scan `000110` chồn ảnh thật: chuỗi đúng dừng đúng ở vạch sàn vàng; các biến
thể sai rõ ràng).

### Checkpoint 2026-09-26 — DONE, RGB-LiDAR alignment service and models Refactor

**Implemented / VERIFIED:**
- `src/services/reconstruction/alignment/models.py`:
  - `AlignmentRequest`: ràng buộc `rgb_geometry_ref`, `lidar_geometry_ref`, `transform_target_from_source`, `same_scene_attestation` và provenance.
  - `normalize_torwic_extrinsics`: chuẩn hóa extrinsic TorWIC chuyển `T_os_from_cam` thành `T_world_from_lidar` theo hệ trục canonical Z-up.
  - `invert_transform`: nghịch đảo rigid transform bảo toàn $R^T$ và $-R^T t$.
  - `parse_torwic_calibrations` & `load_torwic_cam_to_lidar_transform`: trích xuất tự động ma trận extrinsic từ file `data/torwic_slam/raw/global/calibrations.txt` của dataset TorWIC thật, chuẩn hóa quaternion và đưa về canonical `world` frame.
- `src/services/reconstruction/alignment/service.py`:
  - `RgbLidarAlignmentService`:
    - Thẩm định tiền điều kiện: kiểm tra cùng scene, đúng kiểu `RgbGeometry` và `LiDARGeometryArtifact`, transform target frame là canonical `world`.
    - Kiểm tra tính nhất quán boundary: kiểm tra `job_id` của các artifact đầu vào phải khớp với `job_id` của AlignmentRequest, ngăn ngừa ô nhiễm dữ liệu giữa các jobs.
    - Tính toán canonical content checksum và xuất bản `AlignmentRecord` (`status=CONFIRMED`, `producer_stage=StageId.RGB_LIDAR_ALIGN`).
    - Nguồn RGB và LiDAR artifacts giữ nguyên bất biến, không bị sửa đổi.
- `tests/test_reconstruction/test_rec09_alignment.py`:
  - 6/6 test cases pass: xác nhận thành công AlignmentRecord với LiDAR thật từ `LiDARIngestService`, nạp trực tiếp file `calibrations.txt` của TorWIC thật, từ chối khi khác scene (`same_scene_attestation=False`), từ chối khi lệch job_id, từ chối khi target frame sai, kiểm định roundtrip nghịch đảo transform.

## Cập nhật 02/10/2026 (không đổi Goal/I/O/DoD đã khoá)

Với gói LiDAR của người dùng, căn chỉnh đến từ quỹ đạo + calibration + thời điểm frame (dựng pose bám quỹ đạo), không có UI chọn cặp điểm; người dùng xem sai số rồi xác nhận. Chưa làm — [plan](../../../../plans/active/2026-10-02-lidar-video-flow.md) (L5, L6).
