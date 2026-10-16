# Review T-036

Verdict (vòng 1): CHANGES REQUESTED — trả lời 3 câu hỏi của engineer, làm lại bước 4 theo quyết định dưới.

Engineer làm đúng khi dừng và hoàn tác lúc kiểm 4.9 lệch. Code bước 1–3 sẽ được audit sâu ở vòng sau cùng report hoàn chỉnh;
full backend 3.726 pass / 0 fail / 28 skip (đo khi thư mục ở tên mới) ghi nhận.

## Quyết định của Architect

### 1. Checksum evidence của hai capability view: chọn (a) + (c)
Đã kiểm:
- Bản **production** `scripts/gpu/qualify_input_runtimes.py` băm **phiên bản** splat-transform (`_splat_version`, dòng 103,
  149–166), không băm đường dẫn.
- Bản **dev** `scripts/gpu/make_input_runtime_registry.py` dòng 146–147 băm `{"splat_transform": <đường dẫn tuyệt đối>}`.
  Đường dẫn không phải identity của runtime: đây là lỗi của script dev, không phải điều cần giữ.
- Dữ liệu đã lưu không gắn với checksum của hai view: `r2s_jobs`, `r2s_imports`, `r2s_projects`, `r2s_import_operations` và
  artifact trong `data/studio_local/artifacts/jobs` không chứa `qualification_evidence_checksum`/`registry_checksum`. Chỉ
  9 bản ghi `r2s_input_resolutions` (kết quả phân tích tạm, mỗi lần chạy dùng chính registry đã lưu trong bản ghi,
  `assemblies.py:655`) có nhắc tới registry.

Vì vậy:
- **(a)** Sửa `make_input_runtime_registry.py`: evidence của hai view băm **phiên bản** splat-transform (đọc `version` trong
  `package.json` của module, cùng cách với `_splat_version` của bản production; tách hàm dùng chung nếu gọn), không băm
  đường dẫn. `runtime_version` của view đổi từ `splat-transform-local` sang `splat-transform-<phiên bản>`.
  Test: đổi đường dẫn module (cùng phiên bản) → evidence **không đổi**; đổi phiên bản → evidence đổi. Test phải đỏ trên code
  cũ. Commit riêng.
- **(c)** Chấp nhận registry dev đổi **một lần** ở đúng hai capability view (`gaussian_ply_view`, `gaussian_sog_view`) và
  `registry_checksum`/`registry_version`. Acceptance 4 của plan sửa thành: "`qualification_evidence_checksum` và
  `runtime_version` của mọi capability khác không đổi; hai capability view đổi đúng một lần theo quyết định (a); runtime
  manifest không đổi."
- Ở bước 4.9: sinh registry mới vào thư mục tạm, so từng capability với bản cũ. Chỉ hai view được khác. Đúng như vậy thì
  ghi đè `data/studio_local/input_runtime_registry.dev.json` bằng `make -f Makefile.studio registry FORCE_REGISTRY=1`
  (sau khi `studio.env` đã đổi). Giữ bản cũ ở thư mục backups để hoàn tác.

### 2. `Makefile.studio`: giữ bản ở HEAD (`71eda154`, tên mới)
Bỏ thay đổi chưa commit trong working tree (`git checkout -- Makefile.studio`) **ngay trước** khi làm lại bước 4, không commit
bản tên cũ. Bước 4 làm lại sẽ đưa máy về khớp HEAD.

### 3. Stack
Stack đang chạy ở 8010/3010 là của phiên khác (unit `real2sim-studio-demo-route-20261016`, env `/tmp/r2s-demo-route-restart-20261016.env`),
không phải của task. **Không dừng nó.** Chờ chủ dự án báo phiên đó xong việc và cổng trống, rồi làm lại bước 4 từ đầu
(4.1 → 4.11) với các thay đổi trên. Sau khi bật lại bằng lệnh đã duyệt (`systemd-run --user --unit r2s-stack ...`), nếu
unit tên đó đã tồn tại thì báo, không tự xoá.

## Required changes (vòng 2)
1. Commit (a) kèm test như mô tả ở quyết định 1.
2. Sửa acceptance 4 trong report theo quyết định 1 (không sửa plan).
3. Khi chủ dự án cho phép: làm lại bước 4 trọn vẹn, ghi bảng kết quả mới; 4.11 cần đăng nhập để so mã HTTP của 3 job —
   dùng tài khoản Reviewer local (hỏi chủ dự án) hoặc ghi rõ chỉ kiểm được `/health`, `/api/v1/samples`, registry, manifest.
4. Thêm mục Round 2 vào report.

## Round 2 (một phần): (a) ACCEPTED, chờ làm lại bước 4

Audit `781c28fd`: `splat_transform_version` dùng chung; bản production (`qualify_input_runtimes._splat_version`) giữ đúng
ngữ nghĩa cũ (cùng `parents[1]/package.json`). Chạy `test_input_runtime_registry_script` + `test_qualify_input_runtimes`:
17 PASS; ruff sạch. Test mới đỏ trên code cũ như report ghi.

Sửa nhỏ, gộp vào lần làm lại bước 4 (một commit, có test):
- `make_input_runtime_registry.py` dòng ~118 và ~160: module có mà không đọc được phiên bản (`splat_version is None`) thì
  bản dev vẫn ghi view là QUALIFIED với `splat-transform-unknown`, còn bản production ghi `splat_transform_missing`. Cho
  bản dev cùng quy tắc: `view_missing = [] if splat_version else ["splat_transform_missing"]` (tính `splat_version` trước).
  Test: module tồn tại nhưng `package.json` hỏng → hai view UNAVAILABLE với `splat_transform_missing`.

Bước 4.11: DB local có tài khoản Reviewer nhưng mật khẩu là của chủ dự án; agent **không** hỏi hay dùng mật khẩu, không
tạo tài khoản mới. Agent kiểm `/health`, `/api/v1/samples` (5 mẫu), registry, manifest, log không có cảnh báo tên cũ;
chủ dự án tự đăng nhập và mở 3 scene + 5 scene mẫu trên trình duyệt, agent ghi kết quả chủ dự án báo vào report.

## Round 3 — ACCEPTED

Audit `ce64d52e` (dev registry: không đọc được phiên bản splat-transform → hai view `splat_transform_missing`, cùng quy tắc bản
production; test đỏ trước khi sửa) và bước 4 làm lại. Kiểm độc lập:
- Thư mục: `data/reconstruction_runtime`, `data/lidar_open3d_runtime`, `data/lidar_odometry_runtime`; `scene_runtime`,
  `objectgs_runtime` giữ nguyên. Cây làm việc sạch (`Makefile.studio` khớp HEAD).
- `runtime_env` + registry + qualify: 44 PASS.
- Stack `r2s-stack` (cổng 8011/3011 theo `studio.env`): `/health` 200, web 307; journal 30 phút gần nhất không có Traceback hay
  cảnh báo tên cũ.
- DB `studio_local` ở schema 23; `r2s_worker_runtimes` mang **khoá mới** `(software_runtime_checksum, config_checksum,
  seed_key)` (đã đọc DDL trong `sqlite_master`), 1 dòng do worker công bố; `r2s_job_leases` rỗng. Migration 22/23 đã chạy trước
  lần dừng này (một lần khởi động lại ở giữa), nhưng chạy bản đã sửa khoá nên không cần migration bổ sung.
- Engineer báo: manifest sinh lại trùng; registry dev chỉ khác hai view như quyết định (a)+(c); đăng nhập Reviewer 200; 3 job và
  `/scene` 200 khi đăng nhập, 401 khi chưa; 5 mẫu đọc được.

Còn lại (không chặn): chủ dự án tự mở 3 scene và 5 mẫu trên trình duyệt ở `http://localhost:3011`. Chưa chạy job thật; T-039 làm.
