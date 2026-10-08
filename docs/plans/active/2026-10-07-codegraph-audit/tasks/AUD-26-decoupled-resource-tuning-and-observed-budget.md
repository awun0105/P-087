# AUD-26 — Hiệu chỉnh ước lượng tài nguyên theo số đo và tách auto-tune RAM/VRAM

## Metadata và goal

- PLANNED; P1; EX-PRODUCT processing/resources + orchestration admission.
- Canonical PRODUCT-02/08/09, REC-03/04.
- Goal: ước lượng RAM/VRAM không còn thấp hơn số đã đo và không còn cao gấp
  nhiều lần số đã đo; "tối đa cho máy này" không để RAM kéo tụt thông số GPU;
  bảng thông số trên UI dùng số đã đo khi có, giống hàng đợi admission.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0026](../../../../decisions/0026-decoupled-resource-tuning-and-observed-budget.md).

## Baseline và scope

Điểm bắt đầu trong source (kiểm lại bằng CodeGraph trước khi sửa):

- `src/services/orchestration/processing/resources.py`: `estimate_gb`, `evaluate`,
  `interpolate`, `_fits`, `maximum_for_machine`, `DRIVERS`.
- `src/services/orchestration/processing/observed.py`: `observed_budget`, `dominates`,
  `load_usages`, `_vram`.
- `src/services/orchestration/processing/telemetry.py`: `ResourceUsage`, `ResourceSampler`.
- `src/services/orchestration/jobs/admission.py`: `_demand`, `PHASE_TOOLS`, `PHASE_OPTIONAL_TOOLS`.
- `src/api/studio/processing.py`, `src/api/studio/scenes.py:180-184`,
  `src/api/studio/assemblies.py:429`: nơi gọi `evaluate`/`maximum_for_machine`.
- `scripts/gpu/gpu_plan.py:179-201`: `plan_for_machine` gọi `estimate_gb` để chia worker.
- `configs/product/processing_presets_v1.json`: khối `resource_model`.

### Số đo thật đã có (bằng chứng của task này)

Nguồn: bảng `r2s_resource_usage` trong `data/studio_local/runtime.db`, đọc ngày
2026-10-08. Có 28 bản ghi của 6 job trên hai GPU (Quadro T2000 4 GB và RTX 4000 Ada).
Cột "frame thật" lấy từ artifact của job, không lấy từ `params` của bản ghi, vì
`params` chỉ chứa giá trị trần người dùng chọn.

Tool `preview` (COLMAP + Brush), các lượt `completed`:

| Job | GPU | Preset | Frame thật (dựng pose / train) | Peak RAM đo | RAM ước lượng hiện tại | Peak VRAM đo | VRAM ước lượng hiện tại |
|---|---|---|---|---|---|---|---|
| `job-6bc02e5de4ed` | T2000 | tối thiểu | 50 / 43 | 1,04 GB | 7,08 | 2,03 GB | 2,22 |
| `job-9b9aa3dac9f1` | T2000 | tối thiểu | 174 / 152 | 1,46 GB | 7,08 | 2,63 GB | 2,22 |
| `job-a713242a38be` | T2000 | tối thiểu | 149 / 130 | 1,53 GB | 7,08 | 2,63 GB | 2,22 |
| `job-ed9cf7739a70` | RTX 4000 Ada | tối đa | 546 / 477 | 2,83 GB (lượt lỗi trước đó: 4,20) | 87,59 | 4,31 GB | 10,30 |

Tool `scene_extract` (SAM2), một lượt `completed` trên T2000 ở preset tối thiểu:
peak RAM 5,19 GB, peak VRAM 3,42 GB.

Kết luận từ số đo:

1. Ước lượng RAM cao hơn thực tế 5–20 lần. Thủ phạm là số hạng
   `frames * decode_mp * ram_per_decode_megapixel_gb` trong `estimate_gb`
   (`resources.py:81`): ở preset tối đa nó chiếm khoảng 83 trong 87,6 GB.
2. Ước lượng VRAM ở preset tối thiểu thấp hơn thực tế (2,22 so với 2,63 GB đo được).
3. `maximum_for_machine` dùng một hệ số nội suy `t` chung cho mọi thông số. Vì RAM
   bị ước lượng quá cao, máy 6 GB VRAM / 16 GB RAM và máy 24 GB VRAM / 16 GB RAM
   hiện nhận cùng một kết quả: 460 frame, 1.760 px, 1,9 triệu splat.
4. `admission.py:353-372` đã dùng `observed_budget` thay cho ước lượng khi có lượt
   chạy cũ phù hợp, nhưng `evaluate` (UI và điều kiện chặn tạo job) thì không. Hai
   nơi có thể cho hai kết luận khác nhau về cùng một cấu hình.

### Những điều chưa biết (không được coi là sự thật)

- Chưa có lượt chạy nào trên 546 frame thật. Hệ số RAM ở S1 là ngoại suy cho
  vùng 547–2.000 frame.
- Chưa biết số Gaussian cuối cùng của từng lượt, nên chưa tách được phần VRAM do
  số splat và phần do số ảnh. S1 chỉ nâng hằng số nền của VRAM, không đổi hai hệ số còn lại.
- Chỉ có một lượt đo `scene_extract`.

### Owned

`src/services/orchestration/processing/resources.py`,
`src/services/orchestration/processing/observed.py`,
`configs/product/processing_presets_v1.json`,
`scripts/resources/calibrate_resource_model.py` (mới),
`src/api/studio/processing.py`, `src/api/studio/scenes.py`, `src/api/studio/assemblies.py`
(chỉ dòng gọi `evaluate`), `src/services/orchestration/jobs/admission.py` (chỉ dòng import),
`tests/test_orchestration/test_processing_config.py`,
`tests/test_orchestration/test_observed_budget.py`.

Không sửa trong task này: `src/services/orchestration/jobs/runner.py`,
`src/services/orchestration/jobs/progress.py`,
`src/services/orchestration/projects/registry.py` (đang có thay đổi chưa commit
của người khác; nếu thấy cần sửa thì dừng và báo).

## Input / output / data contract

- Input: `ProcessingPresets`, `ResourceModel`, `MachineCapability`, các bản ghi `ResourceUsage`.
- Output: `estimate_gb` với hệ số mới; `maximum_for_machine` hai trục;
  `evaluate` nhận thêm số đã đo.
- Schema không đổi: `ResourceModel`, `MachineCapability`, `Evaluation`,
  `ResourceEstimate`, `ParameterStatus`, `ResourceUsage` giữ nguyên mọi field.
  Chỉ đổi giá trị trong file preset và nội dung chuỗi `message`.
- API không đổi đường dẫn và không đổi dạng payload: `GET /processing/options`,
  `POST /processing/evaluate`.
- Chữ ký hàm đổi: `evaluate(presets, params, capability, observed=None)`.
  Tham số mới có mặc định `None` nên các nơi gọi cũ vẫn chạy.

## Logic change và dependent updates

| Chỗ | Trước | Sau |
|---|---|---|
| Hệ số RAM trong preset | `ram_base_gb 1.5`, `ram_feature_bytes 160`, `ram_per_decode_megapixel_gb 0.012` | `0.9`, `420`, `0` |
| Hệ số VRAM trong preset | `vram_base_gb 0.8` | `1.25` (hai hệ số VRAM còn lại giữ nguyên) |
| `maximum_for_machine` | một `t` cho mọi thông số | hai lần tìm kiếm nối tiếp: nhóm SFM rồi nhóm SPLAT |
| `evaluate` | luôn dùng `estimate_gb` | dùng số đã đo cho RAM/VRAM khi nơi gọi truyền vào |
| `warn_ratio`, `danger_ratio` | 0,75 / 0,92 | giữ nguyên, không thêm hệ số đệm nào |

Consumer phải kiểm lại vì ước lượng RAM giảm:

- `scenes.py:184` và `assemblies.py:429`: điều kiện `evaluation.blocking` sẽ chặn ít hơn.
- `gpu_plan.py:147`: `ram_gb // job_ram_gb` sẽ cho phép nhiều worker song song hơn.
  Kiểm `tests/test_gpu/test_gpu_plan.py`; nếu test giả định RAM cũ thì cập nhật kỳ vọng và ghi lý do.
- `admission.py:347`: khi chưa có số đo, admission dùng cùng ước lượng mới.

## Dependencies

- S1 độc lập. S2 cần S1 (bảng kỳ vọng tính theo hệ số của S1). S3 cần S1.
- Liên quan AUD-15 (đo latency theo stage): AUD-15 đã ghi số frame thật vào bản
  ghi timing. Script ở S1 đọc artifact của job để lấy frame thật; không sửa schema của AUD-15.
- Xác nhận ngoại suy trên 546 frame cần owner chạy job thật (xem Exit của S1).
  Việc này không chặn S2 và S3.

---

## Sprint AUD-26.S1 — Script đối chiếu số đo và hệ số mới

**Input:** `r2s_resource_usage`, artifact của các job đã chạy, file preset.
**Output:** script đối chiếu chỉ đọc; khối `resource_model` với bốn giá trị mới; test khóa các điểm đo.
**Contract:** với mọi lượt `completed` của tool `preview`, ước lượng tính theo frame thật
phải lớn hơn hoặc bằng số đo. Không đổi tên field, không thêm field.

Implement:

1. Tạo `scripts/resources/calibrate_resource_model.py`. Script chỉ đọc, không ghi DB,
   không ghi artifact. Việc nó làm:
   - Đọc mọi bản ghi bằng `load_usages(RuntimeDatabase(settings.database_url))`.
   - Với mỗi `job_id`, lấy frame thật và số Gaussian từ artifact bằng các hàm đã có
     `pose_quality` (`registered_frames`) và `visual_quality` (`training_frames`, `gaussians`)
     trong `src/services/reconstruction/quality.py`. Job không đọc được artifact thì in `—`, không dừng.
   - In một bảng, mỗi dòng một bản ghi: job, tool, outcome, GPU, frame thật, Gaussian,
     các giá trị trần trong `params`, peak RAM, peak VRAM (dùng cùng quy tắc với `_vram`
     trong `observed.py`), và ước lượng của `estimate_gb` khi thay `sampling.max_frames`
     bằng frame thật.
   - In thêm cột `đạt` = ước lượng ≥ số đo, chỉ xét cho lượt `completed`.
2. Sửa bốn giá trị trong `configs/product/processing_presets_v1.json`:
   `ram_base_gb: 0.9`, `ram_feature_bytes: 420`, `ram_per_decode_megapixel_gb: 0`,
   `vram_base_gb: 1.25`. Không sửa các hệ số khác, không sửa `warn_ratio`/`danger_ratio`.
3. Viết lại `resource_model.note` trong file preset thành câu mô tả đúng nguồn:
   hệ số RAM và nền VRAM khớp theo số đo `r2s_resource_usage` ngày 2026-10-04 và 2026-10-05
   (4 job, tối đa 546 frame thật); vùng trên 546 frame là ngoại suy.
4. Thêm test vào `tests/test_orchestration/test_processing_config.py`, dùng các điểm đo
   ở bảng trên làm dữ liệu cố định:
   - RAM: preset tối thiểu với 50 frame ≥ 1,04; với 174 frame ≥ 1,46; preset tối đa với
     546 frame ≥ 4,20 (lấy cả lượt lỗi vì đó là mức cao nhất quan sát được).
   - VRAM: preset tối thiểu ≥ 2,63.
   - Chặn trên để không quay lại lỗi cũ: RAM của preset tối đa nguyên bản (1.200 frame) < 12 GB.

Không làm trong sprint này:

- Không đổi `ram` thành `min(frames, số_luồng)`. Chưa có số đo nào chứng minh dạng đó.
- Không sửa công thức trong `estimate_gb`; chỉ đổi giá trị hệ số.
- Không thêm field vào `ResourceUsage` hay `ResourceModel`.
- Không dùng lượt `failed`, `interrupted`, `cancelled` để khớp VRAM.

Giá trị kiểm tra nhanh sau khi sửa (tính bằng `estimate_gb` với hệ số mới):
preset tối thiểu → RAM 1,93 GB, VRAM 2,67 GB; preset tối đa → RAM 9,16 GB, VRAM 10,75 GB.
Nếu ra số khác thì đã sửa nhầm hệ số.

Tests: `tests/test_orchestration/test_processing_config.py`, `tests/test_gpu/test_gpu_plan.py`,
`tests/test_orchestration/test_resource_admission.py`.

**Exit:**
- [ ] Script chạy trên `data/studio_local/runtime.db`, bảng kết quả dán vào Result;
  mọi lượt `preview` `completed` có cột `đạt` = đúng.
- [ ] Bốn giá trị preset đã đổi; test mới và ba file test trên pass.
- [ ] (Owner, phần cứng thật) Hai lượt chạy có ≥ 1.000 frame thật; chạy lại script; ước
  lượng vẫn ≥ số đo. Chưa có thì ghi UNVERIFIED trong Result, không tick.

---

## Sprint AUD-26.S2 — `maximum_for_machine` hai trục

**Input:** `resources.py` sau S1.
**Output:** `maximum_for_machine` tìm riêng nhóm SFM và nhóm SPLAT.
**Contract:** kết quả luôn qua `presets.validate_params` và luôn thỏa `_fits` cho cả ba
tài nguyên; thông số dạng choice giữ giá trị của preset tối thiểu; mọi nhánh trả sớm
hiện có (không có số đo máy, mốc rảnh thiếu số) giữ nguyên hành vi.

Định nghĩa hai nhóm (đặt thành hằng số cạnh `DRIVERS`):

- Nhóm SFM: `sampling.sample_fps`, `sampling.max_frames`, `colmap.max_image_size`,
  `colmap.max_num_features`, `colmap.sequential_overlap`, `colmap.camera_model`.
- Nhóm SPLAT: mọi key còn lại (toàn bộ `brush.*`).
- Thêm một assert lúc import hoặc một test: hai nhóm phủ đủ và không trùng mọi key
  trong `presets.parameters`. Thêm thông số mới mà quên xếp nhóm thì test phải đỏ.

Thuật toán (viết đúng thứ tự này):

```text
available = mốc rảnh nếu có, ngược lại tổng năng lực máy   # giữ logic hiện tại
minimum, maximum = hai preset; floor = min của từng spec    # giữ logic hiện tại

def search(keys, fixed, resources):
    # Thử hai dải như code hiện tại: minimum→maximum trước, không vừa thì floor→minimum.
    for low, high in ((minimum, maximum), (floor, minimum)):
        candidate(t) = fixed, nhưng các key thuộc `keys` lấy từ interpolate(presets, low, high, t)
        nếu candidate(0) không thỏa _fits trên `resources`: thử dải kế tiếp
        nếu candidate(1) thỏa: trả candidate(1)
        tìm nhị phân 24 vòng trên t, trả candidate tốt nhất thỏa _fits
    trả fixed với các key thuộc `keys` ở mức floor

bước 1: sfm  = search(nhóm SFM,   fixed=minimum, resources=("ram", "disk"))
bước 2: best = search(nhóm SPLAT, fixed=sfm,     resources=("vram", "ram", "disk"))
return presets.validate_params(best)
```

Lý do của thứ tự: số frame quyết định RAM và phần lớn dung lượng đĩa, nên chốt trước.
Bước 2 kiểm cả ba tài nguyên nên kết quả cuối luôn thỏa `_fits` mà không cần bước
kiểm hợp nhất riêng. `_fits` hiện kiểm mọi tài nguyên; thêm tham số tùy chọn để chỉ
kiểm một tập con, mặc định vẫn là cả ba.

Việc đi kèm:

1. Sửa docstring của `interpolate` và `maximum_for_machine`: bỏ câu "mọi thông số số
   tăng cùng nhịp", thay bằng mô tả hai nhóm.
2. Thay test `test_big_gpu_gets_full_maximum_and_small_gpu_scales_everything_down_together`
   bằng test ma trận dưới đây. Đây là đổi yêu cầu, không phải sửa test cho xanh.
3. Giữ nguyên và chạy lại: `test_maximum_for_machine_stays_below_warning_and_valid`,
   `test_maximum_uses_idle_baseline_not_what_a_running_job_left_free`,
   `test_unknown_machine_is_not_reported_as_safe`.

Bảng kỳ vọng (đĩa trống 500 GB, không có mốc rảnh, hệ số của S1). Tôi đã mô phỏng
thuật toán trên bằng `interpolate` và `estimate_gb` thật để ra các số này:

| VRAM / RAM | max_frames | max_image_size | max_num_features | max_resolution | max_splats | total_train_iters |
|---|---|---|---|---|---|---|
| 4 / 16 GB | 1200 | 3200 | 16384 | 1280 | 1.200.000 | 31000 |
| 6 / 16 GB | 1200 | 3200 | 16384 | 1920 | 2.200.000 | 37000 |
| 8 / 16 GB | 1200 | 3200 | 16384 | 2400 | 3.200.000 | 43000 |
| 12 / 32 GB | 1200 | 3200 | 16384 | 3360 | 5.000.000 | 54000 |
| 24 / 16 GB | 1200 | 3200 | 16384 | 3840 | 6.000.000 | 60000 |
| 24 / 8 GB | 910 | 2560 | 13312 | 3840 | 6.000.000 | 60000 |
| 4 / 4 GB | 520 | 1920 | 9216 | 1280 | 1.200.000 | 31000 |

Test bắt buộc:

- Ma trận trên, so đúng từng giá trị. Nếu S1 chốt hệ số khác thì tính lại bảng bằng
  cùng thuật toán, ghi bảng mới vào Result và nêu lý do.
- Cùng RAM, VRAM tăng dần (4 → 6 → 8 → 24, RAM 16): nhóm SFM bằng nhau ở mọi máy;
  `brush.max_splats` và `brush.max_resolution` không giảm.
- Cùng VRAM 24, RAM 8 so với 16: nhóm SPLAT bằng nhau; nhóm SFM của máy 8 GB thấp hơn.
- Mọi kết quả trong ma trận thỏa `_fits` trên cả ba tài nguyên.

Không làm trong sprint này: không đổi `evaluate`, không đổi API, không đổi file preset.

Tests: `tests/test_orchestration/test_processing_config.py`, `tests/test_api/test_studio_routes.py`.

**Exit:**
- [ ] Ma trận khớp; ba test bất biến ở trên pass.
- [ ] Test phủ nhóm (mọi key thuộc đúng một nhóm) pass.
- [ ] `GET /processing/options` trả `machine_maximum` hợp lệ (test route hiện có pass).

---

## Sprint AUD-26.S3 — `evaluate` dùng số đã đo

**Input:** `observed.py`, `admission.py`, ba nơi gọi `evaluate` ở lớp API.
**Output:** khi có lượt chạy cũ phù hợp, UI và điều kiện chặn tạo job dùng cùng con số
với admission.
**Contract:** `resources.py` vẫn là hàm thuần, không mở kết nối DB. Không có số đo phù
hợp thì kết quả giống hệt trước sprint này.

Implement:

1. Chuyển `Phase`, `PHASE_TOOLS`, `PHASE_OPTIONAL_TOOLS` từ `admission.py` sang `observed.py`;
   `admission.py` import lại từ đó. Không đổi giá trị.
2. Thêm vào `observed.py` hàm `observed_for_config(usages, params, gpu_name, runtime_manifest_checksum)`:
   - Gọi `observed_budget` cho từng phase trong `PHASE_TOOLS` với đúng các tham số như
     `admission._demand` đang gọi.
   - Nếu bất kỳ phase nào trả `None` thì trả `None`.
   - Ngược lại trả `{"vram": max của các phase, "ram": max của các phase}`.
3. Sửa `evaluate` trong `resources.py`: thêm tham số
   `observed: dict[Literal["vram", "ram"], float] | None = None`. Khi khác `None`,
   dùng `observed["vram"]` và `observed["ram"]` làm `required` cho hai tài nguyên đó;
   đĩa luôn dùng ước lượng. Trong `message` của tài nguyên dùng số đo, đổi "Cần khoảng"
   thành "Đã đo ở lượt chạy trước". Không thêm field vào `Evaluation`.
4. Ở lớp API, tính `observed` rồi truyền vào `evaluate` tại ba nơi: `processing.py`
   (`evaluate_processing`), `scenes.py:180`, `assemblies.py:429`. Dùng `capability.gpu_name`
   và đúng `runtime_manifest_checksum` mà job mới sẽ nhận. Tìm nơi `scenes.py` gán giá trị
   này cho job khi tạo và dùng lại cùng nguồn; nếu tại `POST /processing/evaluate` không
   xác định được thì truyền `None` và ghi giới hạn này vào Result.
5. `maximum_for_machine` không dùng số đo. Lý do: `observed_budget` chỉ có số khi đã có
   lượt chạy nặng bằng hoặc hơn cấu hình đang xét (`dominates`), nên không thể dùng để
   tìm cấu hình cao hơn những gì đã chạy.

Không làm trong sprint này:

- Không thêm mức sàn cho `scene_extract` vào `ResourceModel`. Khi đã có lịch sử, số đo
  của phase `finalize` (gồm `scene_extract`) tự đi vào `evaluate` qua bước 2. Giới hạn
  còn lại, ghi vào Result: máy chưa có lịch sử thì UI chưa cảnh báo được bước này.
- Không sửa `gpu_plan.py`.

Test (thêm vào `test_observed_budget.py` và `test_processing_config.py`):

- Thiếu số đo của một phase → `observed_for_config` trả `None`.
- Có đủ hai phase → lấy max theo từng tài nguyên.
- `evaluate(..., observed=None)` cho kết quả bằng đúng kết quả trước sprint (so cả object).
- `evaluate(..., observed={"vram": 3.42, "ram": 5.19})` trên máy 4 GB VRAM: tài nguyên
  VRAM ở trạng thái `warn` (3,42 / 4 = 0,855), không `blocking`.
- Một test tích hợp: cùng một DB có lịch sử, `evaluate` qua API và `ResourceAdmission._demand`
  cho cùng `required` RAM/VRAM.

Tests: `tests/test_orchestration/test_observed_budget.py`,
`tests/test_orchestration/test_processing_config.py`,
`tests/test_orchestration/test_resource_admission.py`, `tests/test_api/test_studio_routes.py`,
`tests/integration/test_studio_processing_job.py`.

**Exit:**
- [ ] Năm test trên pass; các test hiện có của admission không đổi kỳ vọng.
- [ ] Result ghi rõ `runtime_manifest_checksum` lấy từ đâu ở từng nơi gọi.

## Verification và DoD

```bash
.venv/bin/ruff check src/ tests/ scripts/resources/
.venv/bin/ruff format --check src/ tests/ scripts/resources/
.venv/bin/pytest tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_observed_budget.py tests/test_orchestration/test_resource_admission.py tests/test_gpu/test_gpu_plan.py tests/test_api/test_studio_routes.py tests/integration/test_studio_processing_job.py -q
.venv/bin/python scripts/resources/calibrate_resource_model.py
```

Phân loại evidence: test ma trận và test hệ số là unit; bảng của script trên
`runtime.db` là local integration; lượt chạy ≥ 1.000 frame là GPU evidence do owner
chạy. Mô phỏng phần cứng bằng `MachineCapability` giả không được ghi là nghiệm thu GPU.

DONE khi cả ba sprint tick đủ Exit, trừ dòng phần cứng của S1 được phép để UNVERIFIED
kèm ghi chú.

## Result / Evidence

Chưa triển khai. Mỗi sprint ghi: commit base, file thật sự sửa, lệnh và output, bảng
của script (S1), bảng ma trận thực tế (S2), nguồn checksum (S3), giới hạn còn lại.
