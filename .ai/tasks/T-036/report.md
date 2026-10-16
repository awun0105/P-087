# Report T-036: Đổi tên thư mục runtime và biến RECxx_* theo chức năng

## Trạng thái: CHANGES-REQUESTED (cần Architect)

Code (bước 1–3) đã xong và đã commit. Bước 4 trên máy **không hoàn thành**: kiểm bước 4.9 lệch (checksum evidence của registry),
đã hoàn tác thư mục, shebang, `studio.env`, và stack không còn chạy bằng cấu hình của task. Lý do và câu hỏi cho Architect ở cuối.

## Done

### Bước 0 — chuẩn bị (không sửa gì ngoài trạng thái)
- Sao lưu `data/studio_local/runtime_manifest.json` và `input_runtime_registry.dev.json` vào thư mục tạm (không trong repo);
  checksum ghi ở `sha256_before.txt` của thư mục tạm.
- Trước khi dừng: `/health` = `{"status":"ok"}`; không job RUNNING/QUEUED, không validation đang chạy, GPU rảnh (6 MiB, 0%).
- Ghi chú: plan yêu cầu ghi mã HTTP của `GET /jobs/{id}/scene` cho 3 job trước khi đổi; **không ghi được** (không có phiên đăng
  nhập), và lần kiểm sau cũng trả 401 (xem bước 4.11).

### Bước 1 — code nhận cả hai tên (commit `f6e65d7b`)
- `src/runtime_env.py`: bảng đổi tên `LEGACY_PREFIXES`, `RuntimeSettings`, `runtime_env`, `legacy_name`, `requirement_env_name`.
- Sáu lớp settings (`ColmapRuntimeSettings`, `BrushRuntimeSettings`, `SplatRuntimeSettings`, `VoxelRuntimeSettings`, `MogeSettings`,
  `LidarOdometryRuntimeSettings`) đọc `R2S_*`, rơi về `RECxx_*` kèm đúng một cảnh báo mỗi tên; tên mới thắng khi có cả hai.
- `tests/test_runtime_env_names.py`: 25 test (tham số hoá qua 6 lớp), đạt. Test adapter cũ dùng tên cũ vẫn xanh.

### Bước 2 — script và test (commit `5feb4b4f`)
- Script đọc qua `runtime_env`: `gpu_plan.py`, `make_input_runtime_registry.py`, `make_runtime_manifest.py`,
  `qualify_input_runtimes.py` (khoá `requires` trong JSON giữ nguyên; khi so khớp dùng `requirement_env_name`),
  `kaggle/preflight.py`, `setup_scene_runtime.sh` (in hướng dẫn). `eval/pose/scale_proposal_error.py` và docstring
  `brush.py` đổi tên.
- Test đổi tên: `test_input_runtime_registry_script`, `test_qualify_input_runtimes`, `test_gpu_plan`, `test_worker_cleanup`,
  `test_lidar_odometry`, `test_studio_routes`.

### Bước 3 — Makefile, file mẫu, tài liệu (commit `71eda154`)
- `Makefile.studio`: đường dẫn `data/reconstruction_runtime`, `data/lidar_odometry_runtime`; template env và hai dòng `ensure`
  đổi sang `R2S_*`.
- `scripts/gpu/studio.env.example` (chỉ phần đổi tên được stage; phần ObjectGS của agent khác đã commit riêng trong `2997baca`),
  `README.md` (bản đồ thư mục + một câu về tên cũ), `docs/RUNPOD_GUIDE.md`, `THIRD_PARTY_NOTICES.md`,
  `scripts/gpu/README.md`, `eval/pose/lidar_odometry_benchmark.py`, `tests/test_reconstruction/test_rec07_prefusion.py`.
- Test chặn tái phát `test_no_legacy_runtime_name_is_left_outside_the_rename_table`: quét 529 file trong `src/`, `scripts/`,
  `eval/`, `Makefile.studio`; ngoại trừ `src/runtime_env.py`, `docker_entrypoint.sh` (T-038), `scripts/gpu/studio.env` (file
  riêng của máy). Đạt.

## Bước 4 — trên máy (đã làm đến 4.9, lệch, hoàn tác)

| Bước | Kết quả thật |
| --- | --- |
| 4.1–4.3 Dừng stack | `kill -TERM` đúng pid `run_stack.sh` (3663882). Cổng 8010 và 3010 trống. |
| Sao lưu | `data/studio_local/backups/studio.env.before-T-036` (`cmp` khớp sau khi khôi phục). |
| 4.5 Dời thư mục | `mv` 3 thư mục thành công. |
| 4.6 Shebang | 13 script `lidar_odometry_runtime/bin` và 25 script `lidar_open3d_runtime/bin` đổi shebang; `grep` còn đường dẫn cũ: 0 (trong `bin/`). `pyvenv.cfg` còn dòng `command = ... data/lidar_runtime` (ghi nhận lịch sử, không ảnh hưởng). |
| 4.7 `studio.env` | 18 tên biến đổi sang `R2S_*` và đường dẫn đổi; không giá trị nào khác bị đổi. |
| 4.8 Runtime | Brush `brush-cli 0.3.0` ✅; splat-transform có mặt ✅; KISS-ICP `1.3.0` (đúng pin) ✅; Open3D `0.19.0` ✅. |
| 4.9 Manifest | Sinh lại vào thư mục tạm: **0 khác biệt** so với `runtime_manifest.json` ✅. |
| 4.9 Registry | **LỆCH** — xem dưới. Registry trên đĩa **không bị ghi đè**. |

### Lệch ở 4.9 (lý do hoàn tác)
Registry sinh lại (thư mục tạm) khác bản dev hiện có ở:
- `capabilities[6]` (`gaussian_ply_view`) và `capabilities[7]` (`gaussian_sog_view`): `qualification_evidence_checksum` đổi;
- `registry_checksum` và `registry_version` đổi theo.

Nguyên nhân (đã xác minh trong mã `scripts/gpu/make_input_runtime_registry.py`): hai capability view băm
`{"splat_transform": <đường dẫn module>}` vào evidence. Đường dẫn đổi từ `data/rec04_runtime/...` sang
`data/reconstruction_runtime/...`, nên checksum đổi. Acceptance 4 của plan yêu cầu checksum không đổi, nên tôi hoàn tác
theo chỉ dẫn "bước nào lệch thì dừng và hoàn tác".

### Hoàn tác (đã làm)
1. Dời ngược 3 thư mục về `data/rec04_runtime`, `data/rec07_runtime`, `data/lidar_runtime`; đảo shebang và đường dẫn trong
   `activate*`; `data/rec04_runtime/run-smoke.sh` về đường dẫn cũ. `data/lidar_runtime/bin/python -c "import kiss_icp"` vẫn chạy.
2. `scripts/gpu/studio.env` khôi phục từ bản sao lưu (`cmp` khớp).
3. `Makefile.studio` (working tree, **chưa commit**) đưa về nội dung của `2997baca` (trước đổi tên). Lý do: `make up` gọi
   `registry` → `ensure R2S_LIDAR_ODOMETRY_PYTHON`; nếu giữ Makefile mới với `studio.env` cũ, `make up` sẽ chèn đường dẫn đã không
   còn và `lidar-runtime` sẽ tạo venv mới qua mạng.

## Bật lại stack và kiểm 4.11 — KHÔNG hoàn thành

- Đã chạy lệnh được duyệt: `systemd-run --user --unit r2s-stack -p CPUQuota=250% --working-directory="$PWD" make -f Makefile.studio up`.
- Journal cho thấy stack của lệnh này (`make` pid 3851695) đã chạy và phục vụ request từ ~19:27 đến 19:31. Lúc **19:33:05** có một
  lệnh `[stop]` bên ngoài dừng stack ("[stop] dừng FastAPI + worker + Next.js"); stack ra khỏi cổng 8010/3010 lúc 19:33:07.
- Lúc **19:33:24** một stack khác đã chiếm 8010/3010: `run_stack.sh /tmp/r2s-demo-route-restart-20261016.env` (pid 3925034,
  uvicorn 3925041, worker 3925042, Next 3925085). Đây **không phải** stack của `scripts/gpu/studio.env` và không phải của task này.
- Unit `r2s-stack` không còn tồn tại (đã kết thúc). Tôi **không** dừng tiến trình của người khác và không khởi động lại
  để đè lên nó.
- Kết quả 4.11 (thu được từ stack khác, nên không kết luận được cho stack của task):
  - `/health` = 200; frontend cổng 3010 = 307.
  - `GET /api/v1/jobs/{id}` và `/scene` cho 3 job = **401** (không có phiên đăng nhập; không so được với mã trước khi đổi).
  - `GET /api/v1/samples` = 5 mẫu.
  - Checksum `runtime_manifest.json` và `input_runtime_registry.dev.json` = khớp bản bước 0 (`sha256sum -c` OK).
- **Chưa kiểm** trên stack của `studio.env`: đọc preview 5 scene, trạng thái R1–R6 qua API, log không có cảnh báo tên cũ.
- Chưa chạy job video thật. **Chưa chạy job thật, sẽ kiểm ở T-039.**

## Full backend suite (sau bước 3, trước khi hoàn tác)
```
.venv/bin/python -m pytest tests -q -p no:cacheprovider
→ 3726 passed, 28 skipped, 15 warnings in 529.64s (0:08:49)   EXIT=0
```
Chạy khi thư mục đang ở tên mới (trạng thái trước hoàn tác).

## Commits
- `f6e65d7b` Read runtime settings from R2S_* names and keep accepting the RECxx_* names (bước 1)
- `5feb4b4f` Use the R2S_* runtime variable names in scripts and tests (bước 2)
- `71eda154` Point Makefile, examples and docs at the renamed runtime folders and variables (bước 3)
- `0fa890b6` Start T-036 runtime rename (status)

## Trạng thái working tree của task này (cần quyết định)
- `Makefile.studio`: đã đưa về bản `2997baca` (tên cũ, đường dẫn cũ) — **chưa commit**. HEAD (`71eda154`) vẫn có bản đổi tên.
  Hai việc này mâu thuẫn cho đến khi có quyết định (xem câu hỏi 2).
- File khác đang sửa không thuộc task này (`frontend/...`, `src/api/studio/samples.py`, `tests/test_api/test_role_matrix.py`,
  …) do agent khác làm; không đụng.

## Việc còn lại cho T-038 (Dockerfile / compose / deploy / entrypoint, ngoài phạm vi T-036)
- `scripts/gpu/docker_entrypoint.sh` xuất tên `REC03_*`, `REC04_*`, `REC05_*`, `REC06_*`, `REC17_*` vào container (dòng 45–87) →
  mỗi lần container chạy sẽ in cảnh báo tên cũ cho đến khi đổi.
- `docker-compose.gpu.yml` dòng 60, 64–76, 97, 111–127; `docker-compose.yml` dòng 90–93; `Dockerfile` dòng 69–71;
  `Dockerfile.gpu` dòng 36 (`R2S_LIDAR_RUNTIME`, đã là tên mới), đường dẫn container `/opt/real2sim/lidar_runtime` trong
  `src/services/reconstruction/lidar/odometry.py:174`, `scripts/gpu/make_input_runtime_registry.py:37`,
  `scripts/gpu/qualify_input_runtimes.py:37`, `docker-compose.gpu.yml:60,97`, `Dockerfile.gpu:36`.
- `tests/test_packaging/test_compose_config.py` dòng 94–110 (assert tên cũ trong compose).

## Cách hoàn tác (đã dùng cho lần thử này; áp dụng lại khi làm lại)
Dừng stack; `mv` ngược 3 thư mục; đảo shebang/activate; `cp -p` bản sao lưu về `scripts/gpu/studio.env`; đưa `Makefile.studio`
về bản trước đổi tên (hoặc giữ bản mới và đổi `studio.env` tương ứng); bật lại stack. Ba commit code không cần hoàn tác vì
tên cũ vẫn được nhận.

## Câu hỏi cho Architect
1. **Checksum evidence của view splat (`gaussian_ply_view`, `gaussian_sog_view`) băm đường dẫn module.** Đổi thư mục làm đổi
   checksum và `registry_checksum`/`registry_version`. Acceptance 4 của plan không đạt nếu đổi đường dẫn. Chọn một:
   (a) băm tên module tương đối/logic thay vì đường dẫn tuyệt đối (đổi cách tính evidence — thay đổi có ảnh hưởng tới các
   job đã lưu, cần quyết định); (b) giữ tên thư mục cũ cho `rec04_runtime` (bỏ đổi tên thư mục reconstruction, chỉ đổi biến);
   (c) chấp nhận đổi registry (dev-local, chỉ các view) và ghi rõ trong plan.
2. **Makefile và HEAD.** `71eda154` đổi đường dẫn trong `Makefile.studio`, nhưng máy đang chạy bằng tên cũ. Có muốn commit
   việc đưa Makefile về tên cũ (cùng quyết định 1) hay giữ bản mới đến khi đổi xong?
3. **Stack.** Hiện 8010/3010 do stack demo `/tmp/r2s-demo-route-restart-20261016.env` chạy. Cần chủ dự án quyết định có dừng nó
   để khôi phục `studio.env` không (tôi không tự dừng). Unit `r2s-stack` không còn; có thể bật lại bằng lệnh đã duyệt sau khi
   cổng trống.

## Acceptance (kiểm được)
1. Ba thư mục mang tên mới trên đĩa: **đã đạt rồi hoàn tác** (không còn ở trạng thái mới).
2. Sáu lớp settings đọc `R2S_*`, tên cũ vẫn chạy kèm cảnh báo, tên mới thắng: **đạt** (test 25 pass).
3. Test chặn tái phát xanh: **đạt**.
4. `qualification_evidence_checksum` và `runtime_version` của mọi capability khác không đổi; hai capability view đổi đúng một lần theo quyết định (a) của review; runtime manifest không đổi. (Sửa theo review vòng 2; acceptance gốc của plan không đổi.)
5. Stack chạy lại với cấu hình task: **không đạt / chưa xác nhận** (stack của task đã dừng bởi tiến trình bên ngoài; stack đang chạy là của phiên khác).
6. `input_runtime_qualification_v1.json`, Dockerfile, compose, deploy không bị sửa: **đạt**.

## Round 2 (theo review.md vòng 2)

### (a) Evidence của hai view băm phiên bản splat-transform — commit `781c28fd`
- `scripts/gpu/make_input_runtime_registry.py`: thêm `splat_transform_version(module)` (đọc `version` từ `package.json` cạnh
  module, cùng cách với bản production). Evidence của `gaussian_ply_view` và `gaussian_sog_view` băm
  `{"splat_transform": <phiên bản>}`; `runtime_version` đổi từ `splat-transform-local` sang `splat-transform-<phiên bản>`.
- `scripts/gpu/qualify_input_runtimes.py`: `_splat_version` gọi cùng hàm dùng chung (hành vi giữ nguyên).
- Test mới trong `tests/test_reconstruction/test_input_runtime_registry_script.py`:
  - `test_splat_view_evidence_ignores_the_module_path_when_the_version_is_the_same`: đổi đường dẫn module, cùng phiên bản →
    evidence và `runtime_version` của hai view **không đổi**; các capability khác không đổi.
  - `test_splat_view_evidence_follows_the_splat_transform_version`: đổi phiên bản → evidence đổi.
- **Đỏ trên code cũ**: trước khi sửa, cả hai test fail (`2 failed, 5 passed`). Sau khi sửa: các test của registry, qualify,
  gpu_plan đạt (49 passed trong lần chạy cùng nhóm).

### Acceptance 4 trong báo cáo: đã sửa (plan không đổi)
Xem dòng 4 ở mục Acceptance: checksum và `runtime_version` của mọi capability khác không đổi; hai view đổi đúng một lần.

### Trạng thái hiện tại của máy (chưa làm lại bước 4)
- Stack đang chạy ở 8010/3010 vẫn là của phiên khác; **chưa** làm lại bước 4 (chờ chủ dự án báo).
- `Makefile.studio` trong working tree vẫn là bản tên cũ (hoàn tác trước đó), **chưa commit**. Theo quyết định 2, sẽ đưa về
  HEAD (`git checkout -- Makefile.studio`) ngay trước khi làm lại bước 4. Hệ quả: test chặn tái phát
  `test_no_legacy_runtime_name_is_left_outside_the_rename_table` **đỏ** cho đến khi Makefile được đưa về HEAD. Đây là kết quả
  có chủ đích của trạng thái hoàn tác, không phải lỗi code; không commit Makefile tên cũ.
- Registry dev trên đĩa chưa đổi; sẽ đổi đúng một lần ở bước 4.9 (chỉ hai view) theo quyết định (c).

### Việc còn lại (chờ chủ dự án báo)
- Làm lại bước 4 trọn vẹn (4.1 → 4.11) và ghi bảng kết quả mới.
- 4.11: cần tài khoản Reviewer local để so mã HTTP của 3 job; nếu không có, chỉ kiểm được `/health`, `/api/v1/samples`,
  registry và manifest, và ghi rõ như vậy.
- Unit tên `real2sim-studio-demo-route-20261016` là của phiên khác: không dừng, chỉ chạy lại khi cổng đã trống.

