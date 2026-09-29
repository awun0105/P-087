# Execution Plan: Hoàn thiện pipeline và Studio (sau Cloud đợt 1)

Date: 2026-09-29

## Status

Active — owner (Quân) yêu cầu ngày 2026-09-29: "ghi các quyết định vào docs, cho kế
hoạch tổng thể tất cả các việc còn thiếu, rồi thực hiện theo kế hoạch". Branch hiện
tại `feat/rec-completion` (từ `develop` tại `7a58880`).

## Outcome

Một người dùng mở Studio, đưa vào video / file 3DGS `.ply` / `.zip` (PLY + COLMAP),
hệ thống tự nhận diện loại và chạy đúng luồng tới scene có tỉ lệ mét, collision mesh
và bundle bàn giao cho EX-SCENE/EX-SIM; xem được kết quả của từng bước; demo so sánh
ba hướng tỉ lệ trên Aisle_CW.

## Authority

- ADR 0001 (metric scale), 0002 (Studio MVP), 0003 (cloud, role, ngân sách trình
  duyệt), [0004](../../decisions/0004-input-kinds-and-routing.md) (loại đầu vào, ba
  hướng demo), [0005](../../decisions/0005-stage-results-viewer.md) (xem từng bước).
- Task files `docs/execution/tracks/*/tasks/*.md`; plan con: [EX-REC](2026-09-24-ex-rec-track.md),
  [Cloud Studio](2026-09-29-cloud-studio.md) (tạm dừng, handoff riêng).
- Plan này không tạo task ID mới. Mục không thuộc task có sẵn ghi là "gói" trong plan;
  nếu owner muốn task ID riêng thì owner cấp.

## Hiện trạng (VERIFIED 2026-09-29)

- DONE: REC-01, 02A, 02, 03, 04, 07; SIM-02, SIM-04; PRODUCT-05.
- IN_PROGRESS: REC-05, 06, 08, 09, 10, 11; PRODUCT-01–03, 06–11.
- TODO: PRODUCT-04, PRODUCT-12; SCENE-02…10; SIM-01, 02A, 03, 05–09. SCENE-01 VALIDATING.
- Worker Studio chạy: prepare → COLMAP → Brush → preview → **chờ xác nhận tỉ lệ**
  (REC-06, UI + API đã có, commits `66f3433`…`c48ec4d`). Sau xác nhận chưa có bước nào chạy.
- Nhận diện loại đầu vào: có module (`95fa90d`), chưa nối vào upload.

## Quyết định đã chốt trước gói 3 (owner, 2026-09-29)

| # | Quyết định | Ghi tại |
| --- | --- | --- |
| Q1 | C/D bắt buộc, chọn cùng bước A/B + sàn, kiểm ngay khi xem trước | REC-06 |
| Q2 | `tolerance_m = 2√2·e·(1 + L_CD/L_AB)`, đoạn ≥ 0,5 m, ≤ 5% L_CD; `e = 1 cm` tạm, đo và khóa ở gói 2 | REC-06 |
| Q3 | Voxel từ `configs/product/geometry_v1.json` (chưa hiệu chỉnh); seed camera hạ sát sàn, dời ≤ 1 m, hỏng thì mời click | REC-05 |
| Q4 | Không nới `ReconstructionBundle`; `.ply` trần dừng trước bundle | ADR 0004 §4 |

## Các gói việc (thứ tự thực hiện)

Mỗi gói: code + test tập trung + cập nhật task file liên quan + commit nhỏ.

### Gói 1 — Nhận diện đầu vào vào upload (ADR 0004 §1–2) · EX-PRODUCT + EX-REC

- Upload nhận `.mp4/.mov/.ply/.zip`; sau khi verify checksum, server chạy
  `detect_input` và lưu `input_kind` + bằng chứng vào `UploadRecord`; loại sai → FAILED
  với lý do. Cả đường stream qua API và upload thẳng lên kho file.
- InputManifest ghi kind vào `preparation_provenance` (không đổi shared contract).
- UI một ô tải lên, hiện loại nhận diện được trước khi tạo scene.
- Proof: unit test cho từng loại + file sai, API test, vitest.

### Gói 2 — Ổn định bước xác nhận tỉ lệ (REC-06) · EX-REC + EX-PRODUCT

- Browser QA chọn điểm thật trên một job Aisle_CW đang chờ; test HTTP luồng đủ.
- Đo sai số click `e` so với LiDAR trên đoạn hiệu chỉnh riêng, khóa vào REC-06 (Q2).
- Proof: ảnh chụp QA + test; REC-06 evidence.

### Gói 3 — Chạy tiếp sau xác nhận: REC-06 canonical → REC-05 → REC-10 → REC-11 · EX-REC

- Worker nhận job RUNNING ở METRIC có bản xác nhận → canonical visual + poses →
  voxel/collision (capsule OTTO 0,4610/0,308) → bundle metric verify → ReconstructionBundle.
- Timeline thêm các bước này; job SUCCEEDED khi bundle publish.
- Theo Q1–Q3; UI xác nhận tỉ lệ thêm C/D (7 điểm). Proof: test fixture toàn chuỗi qua runner + một lần chạy GPU thật.

### Gói 4 — Xem kết quả từng bước (ADR 0005) · EX-PRODUCT

- API: danh sách bước có gì để xem; server tạo bản xem (GLB mesh/voxel, point cloud
  giảm mẫu, camera COLMAP dạng JSON nhẹ).
- UI: click bước trên timeline → viewer tương ứng (PlayCanvas cho 3DGS, three.js cho
  mesh/point cloud, lưới ảnh cho frame); một lớp mỗi lúc, cleanup khi đổi.
- Làm trước được: frame, COLMAP, 3DGS, tỉ lệ mét. REC-05 trở đi sau gói 3.

### Gói 5 — Import 3DGS (ADR 0004 §3) · EX-REC + EX-PRODUCT

- 5a `gaussian_ply_colmap`: đọc model COLMAP → camera pose + visual import có
  camera → đi tiếp như video từ REC-06.
- 5b `gaussian_ply`: visual import không camera; REC-06 thêm điểm "phía trên sàn",
  bỏ kiểm độ cao camera; REC-05 seed do người dùng click. Tới REC-05, không tạo bundle (Q4).
- Cả hai: server chuyển PLY → SOG để xem, không cần GPU.

### Gói 6 — Demo ba hướng trên Aisle_CW (ADR 0004 §5) · EX-REC + EX-PRODUCT

- Hướng LiDAR: hoàn tất REC-08 → REC-09 alignment trên dữ liệu thật; nối vào job demo.
- Hướng anchor người dùng: dùng gói 2–3.
- Hướng RGB only: mock có nhãn "Mô phỏng · P1", không số tỉ lệ giả.
- Màn hình so sánh ba cột (timeline, scene, tỉ lệ, sai số của cùng đoạn kiểm so với LiDAR).
- Sau đó PRODUCT-12 (demo route ổn định).

### Gói 7 — UI/UX Studio · EX-PRODUCT

- Rà luồng upload → xử lý → xác nhận → xem; thông báo lỗi, trạng thái chờ, mobile.
- LOD nhẹ/vừa/đầy đủ (Cloud plan mục 7) nếu kịp.

### Phụ thuộc track khác (không thuộc owner EX-REC; theo dõi, không tự làm)

- EX-SCENE (Đức): SCENE-01 VALIDATING, SCENE-02…10 TODO — cần consume bundle từ gói 3.
- EX-SIM (Đạt): SIM-01, 03, 05–09 TODO — Isaac smoke, OpenUSD, ValidationReport; Web
  hiện báo cáo/video của EX-SIM theo ADR 0005 §2.
- Cloud/ops: 21 việc ở [handoff](../../execution/tracks/ex_product/HANDOFF-2026-09-29-cloud-ops.md), tạm dừng.

## Progress

- [x] Ghi ADR 0004, 0005 và plan này.
- [ ] Gói 1 … Gói 7.

## Validation

Mỗi gói ghi command + kết quả tại task file liên quan và tóm tắt ở đây.
