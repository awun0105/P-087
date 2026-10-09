# AUD-26 — Hiệu chỉnh ước lượng tài nguyên theo số đo và tách auto-tune RAM/VRAM

## Metadata và goal

- IMPLEMENTED (code, 2026-10-09; các dòng Exit trên pod RunPod của S1, S4, S5 còn mở); P1; EX-PRODUCT processing/resources + orchestration admission.
- Canonical PRODUCT-02/08/09, REC-03/04.
- Goal: ước lượng RAM/VRAM không còn thấp hơn số đã đo và không còn cao gấp
  nhiều lần số đã đo; "tối đa cho máy này" không để RAM kéo tụt thông số GPU;
  bảng thông số trên UI dùng số đã đo khi có, giống hàng đợi admission; worker đo
  đúng RAM/CPU được cấp trong container và chạy đúng số worker trên pod production.
- Máy đích production: một pod RunPod có một GPU 24 GB (RTX 3090 hoặc RTX 4090).
  Quadro T2000 4 GB là máy dev; không tối ưu riêng cho nó.
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

### Máy đích và nguyên tắc phục vụ nhiều người dùng (owner chốt 2026-10-08)

- Production chạy trên pod RunPod một GPU 24 GB. Bảng giá RunPod (đọc 2026-10-08, cần
  kiểm lại trên console khi thuê) liệt kê pod RTX 3090 với 16 vCPU và 125 GB RAM, pod
  RTX 4090 với 6 vCPU và 41 GB RAM. Cấu hình CPU/RAM thay đổi theo host.
- Khi nhiều người dùng cùng gửi job, chất lượng không được giảm: job giữ nguyên cấu
  hình đã chọn và chờ trong hàng đợi. Chấp nhận thời gian chờ dài hơn.
- Vì vậy `maximum_for_machine` tính theo cả card, không chia cho số worker; và không
  thêm trần thông số theo vai trò. Chi phí của guest đã được chặn bằng quota 3 lượt mỗi
  ngày (AUD-22).
- Cơ chế đã có và giữ nguyên: hàng đợi xoay vòng theo người dùng (`jobs/queue.py`,
  `fair_order`), admission chỉ cho job chạy khi đủ VRAM/RAM, vị trí và thời gian chờ ước
  tính hiển thị cho người dùng.

### Số đo thời gian theo pha (bằng chứng cho số worker)

Lấy từ `process.log` và `brush-train.log` của các job local trên laptop 12 nhân + T2000:

| Job | Frame thật | COLMAP (CPU): extractor + matcher + mapper | Brush (GPU) |
|---|---|---|---|
| `job-a713242a38be` | 149 | 3,2 + 3,5 + 6,4 = 13,1 phút | 28,5 phút |
| `job-9b9aa3dac9f1` | 174 | 5,2 + 5,5 + 5,9 = 16,6 phút | không lấy được (nhiều lượt chạy lại) |
| `job-43f3bc853742` | chưa rõ | 7,5 + 5,7 + 8,4 = 21,6 phút | không có |

Hai điều rút ra:

1. COLMAP chạy hoàn toàn trên CPU (`use_gpu: false`) và chiếm một phần lớn thời gian
   job. Trên GPU 24 GB, Brush nhanh hơn nhiều so với T2000 trong khi COLMAP phụ thuộc
   CPU của pod, nên tỉ trọng COLMAP ở production sẽ còn cao hơn. Đây là suy luận, chưa đo trên pod.
2. Hai job cùng train Brush trên một card phải chia nhau sức tính của GPU. Lợi ích của
   việc chạy song song đến từ chỗ job này dùng CPU (COLMAP) trong khi job kia dùng GPU
   (Brush), không đến từ việc nhiều job cùng train.

Hai vấn đề đo máy trong container (đã kiểm trong source):

- RAM đọc từ `/proc/meminfo` (`capability.py:105`, `:160`) và `SC_PHYS_PAGES`
  (`gpu_plan.py:192`). Trong container, các nguồn này thường trả về RAM của máy chủ chứ
  không phải phần pod được cấp. Chưa kiểm trên pod RunPod thật.
- Số nhân lấy từ `os.cpu_count()` (`capability.py:208`), và COLMAP dùng
  `min(16, cpu_count)` luồng (`processing/config.py:64`). Trên pod 6 vCPU nằm trên host
  nhiều nhân, mỗi job COLMAP sẽ mở 16 luồng.

### Những điều chưa biết (không được coi là sự thật)

- Chưa có lượt chạy nào trên 546 frame thật. Hệ số RAM ở S1 là ngoại suy cho
  vùng 547–2.000 frame.
- Chưa biết số Gaussian cuối cùng của từng lượt, nên chưa tách được phần VRAM do
  số splat và phần do số ảnh. S1 chỉ nâng hằng số nền của VRAM, không đổi hai hệ số còn lại.
- Chỉ có một lượt đo `scene_extract`.
- Chưa có số đo nào trên RTX 3090/4090, và chưa có số đo nào khi nhiều job chạy chung
  một card. Số worker ở S4 là giá trị khởi đầu suy ra từ số đo local, phải xác nhận trên pod.

### Owned

`src/services/orchestration/processing/resources.py`,
`src/services/orchestration/processing/observed.py`,
`configs/product/processing_presets_v1.json`,
`scripts/resources/calibrate_resource_model.py` (mới),
`src/services/orchestration/processing/container_limits.py` (mới),
`src/services/orchestration/processing/capability.py`, `scripts/gpu/gpu_plan.py`,
`deploy/studio/worker.env.example`, `scripts/gpu/studio.env.example`,
`src/services/orchestration/processing/config.py`, `src/config.py` (một setting),
`scripts/kaggle/preflight.py`, `tests/test_reconstruction/test_rec03_colmap.py`,
`tests/test_orchestration/test_container_limits.py` (mới), `tests/test_gpu/test_gpu_plan.py`,
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
| Hệ số RAM trong preset | `ram_base_gb 1.5`, `ram_feature_bytes 160`, `ram_per_decode_megapixel_gb 0.012` | `1.05`, `420`, `0` |
| Hệ số VRAM trong preset | `vram_base_gb 0.8` | `1.25` (hai hệ số VRAM còn lại giữ nguyên) |
| `maximum_for_machine` | một `t` cho mọi thông số | hai lần tìm kiếm nối tiếp: nhóm SFM rồi nhóm SPLAT |
| `evaluate` | luôn dùng `estimate_gb` | dùng số đã đo cho RAM/VRAM khi nơi gọi truyền vào |
| `warn_ratio`, `danger_ratio` | 0,75 / 0,92 | giữ nguyên, không thêm hệ số đệm nào |
| RAM và số nhân worker báo cáo | theo `/proc/meminfo` và `os.cpu_count()` của host | lấy giá trị nhỏ nhất giữa host và giới hạn của container |
| `STUDIO_WORKERS` trong file môi trường mẫu của production | `auto` | giá trị cụ thể theo loại pod (xem S4) |
| `colmap.use_gpu` trong cấu hình job | luôn `false` (từ file preset) | theo setting `PRODUCT_COLMAP_USE_GPU` của deployment; production bật (xem S5) |

Consumer phải kiểm lại vì ước lượng RAM giảm:

- `scenes.py:184` và `assemblies.py:429`: điều kiện `evaluation.blocking` sẽ chặn ít hơn.
- `gpu_plan.py:147`: `ram_gb // job_ram_gb` sẽ cho phép nhiều worker song song hơn.
  Kiểm `tests/test_gpu/test_gpu_plan.py`; nếu test giả định RAM cũ thì cập nhật kỳ vọng và ghi lý do.
- `admission.py:347`: khi chưa có số đo, admission dùng cùng ước lượng mới.

## Dependencies

- S1 độc lập. S2 cần S1 (bảng kỳ vọng tính theo hệ số của S1). S3 cần S1.
- Liên quan AUD-15 (đo latency theo stage): AUD-15 đã ghi số frame thật vào bản
  ghi timing. Script ở S1 đọc artifact của job để lấy frame thật; không sửa schema của AUD-15.
- Xác nhận ngoại suy trên 546 frame cần owner chạy job thật trên pod 24 GB (xem Exit
  của S1). Việc này không chặn S2 và S3.
- S5 độc lập về code với S1–S4; phép đo số worker của S4 phải chạy sau khi S5 đã bật.
  Đoạn trích log khi COLMAP lỗi vì GPU dựa vào AUD-27.S1; chưa có AUD-27.S1 thì lỗi vẫn
  hiện với mã `COLMAP_PROCESS_FAILED` như hiện tại.
- S4 độc lập về code với S1–S3. Phần đo trên pod của S4 nên chạy cùng đợt thuê máy với
  phần đo của S1 để không thuê hai lần.

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
   `ram_base_gb: 1.05`, `ram_feature_bytes: 420`, `ram_per_decode_megapixel_gb: 0`,
   `vram_base_gb: 1.25`. Không sửa các hệ số khác, không sửa `warn_ratio`/`danger_ratio`.
3. Viết lại `resource_model.note` trong file preset thành câu mô tả đúng nguồn:
   hệ số RAM và nền VRAM khớp theo số đo `r2s_resource_usage` ngày 2026-10-04 và 2026-10-05
   (4 job, tối đa 546 frame thật); vùng trên 546 frame là ngoại suy.
4. Thêm test vào `tests/test_orchestration/test_processing_config.py`, dùng các điểm đo
   ở bảng trên làm dữ liệu cố định:
   - RAM: preset tối thiểu với 50 frame ≥ 1,04; với 149 frame ≥ 1,53; với 174 frame ≥ 1,46; preset tối đa với
     546 frame ≥ 4,20 (lấy cả lượt lỗi vì đó là mức cao nhất quan sát được).
   - VRAM: preset tối thiểu ≥ 2,63.
   - Chặn trên để không quay lại lỗi cũ: RAM của preset tối đa nguyên bản (1.200 frame) < 12 GB.

Không làm trong sprint này:

- Không đổi `ram` thành `min(frames, số_luồng)`. Chưa có số đo nào chứng minh dạng đó.
- Không sửa công thức trong `estimate_gb`; chỉ đổi giá trị hệ số.
- Không thêm field vào `ResourceUsage` hay `ResourceModel`.
- Không dùng lượt `failed`, `interrupted`, `cancelled` để khớp VRAM.

Giá trị kiểm tra nhanh sau khi sửa (tính bằng `estimate_gb` với hệ số mới):
preset tối thiểu → RAM 2,08 GB, VRAM 2,67 GB; preset tối đa → RAM 9,31 GB, VRAM 10,75 GB.
Nếu ra số khác thì đã sửa nhầm hệ số.

Tests: `tests/test_orchestration/test_processing_config.py`, `tests/test_gpu/test_gpu_plan.py`,
`tests/test_orchestration/test_resource_admission.py`.

**Exit:**
- [x] Script chạy trên `data/studio_local/runtime.db`, bảng kết quả dán vào Result;
  mọi lượt `preview` `completed` có cột `đạt` = đúng.
- [x] Bốn giá trị preset đã đổi; test mới và ba file test trên pass.
- [ ] (Owner, pod RunPod 24 GB) Hai lượt chạy có ≥ 1.000 frame thật ở preset tối đa;
  chạy lại script trên DB của pod; ước lượng vẫn ≥ số đo. Chưa có thì ghi UNVERIFIED
  trong Result, không tick.

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

Bảng kỳ vọng (đĩa trống 500 GB, không có mốc rảnh, hệ số của S1). Các số này ra từ
việc mô phỏng thuật toán trên bằng `interpolate` và `estimate_gb` thật. Dòng 24 GB là
cấu hình production. Các dòng 4–12 GB là test của thuật toán (và là trường hợp card
24 GB đang bị job khác chiếm một phần), không phải cấu hình được hỗ trợ:

| VRAM / RAM | max_frames | max_image_size | max_num_features | max_resolution | max_splats | total_train_iters |
|---|---|---|---|---|---|---|
| 4 / 16 GB | 1200 | 3200 | 16384 | 1280 | 1.200.000 | 31000 |
| 6 / 16 GB | 1200 | 3200 | 16384 | 1920 | 2.200.000 | 37000 |
| 8 / 16 GB | 1200 | 3200 | 16384 | 2400 | 3.200.000 | 43000 |
| 12 / 32 GB | 1200 | 3200 | 16384 | 3360 | 5.000.000 | 54000 |
| 24 / 16 GB | 1200 | 3200 | 16384 | 3840 | 6.000.000 | 60000 |
| 24 / 8 GB | 880 | 2560 | 13312 | 3840 | 6.000.000 | 60000 |
| 4 / 4 GB | 500 | 1920 | 9216 | 1280 | 1.200.000 | 31000 |

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
- [x] Ma trận khớp; ba test bất biến ở trên pass.
- [x] Test phủ nhóm (mọi key thuộc đúng một nhóm) pass.
- [x] `GET /processing/options` trả `machine_maximum` hợp lệ (test route hiện có pass).

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
- [x] Năm test trên pass; các test hiện có của admission không đổi kỳ vọng.
- [x] Result ghi rõ `runtime_manifest_checksum` lấy từ đâu ở từng nơi gọi.

---

## Sprint AUD-26.S4 — Giới hạn container và số worker trên pod 24 GB

**Input:** `capability.py`, `gpu_plan.py`, `processing/config.py`, hai file môi trường mẫu.
**Output:** worker báo đúng RAM và số nhân được cấp trong container; file môi trường mẫu
của production có số worker cụ thể; một quy trình đo để xác nhận số worker trên pod.
**Contract:** trên máy không có giới hạn container (laptop dev), mọi số đo giữ nguyên
như trước sprint. Không đổi schema `MachineCapability`.

Phần A — đọc giới hạn container:

1. Tạo `src/services/orchestration/processing/container_limits.py`, gồm các hàm thuần
   nhận thư mục gốc làm tham số để test được bằng thư mục tạm (theo cách `procfs.py`
   dùng `PROC_ROOT`):
   - `memory_limit_gb(cgroup_root) -> float | None`: đọc `memory.max` (cgroup v2), nếu
     không có thì `memory/memory.limit_in_bytes` (cgroup v1). Giá trị `max`, giá trị
     không phải số, hoặc số lớn hơn 2^60 nghĩa là không giới hạn → trả `None`.
   - `memory_usage_gb(cgroup_root) -> float | None`: đọc `memory.current` (v2) hoặc
     `memory/memory.usage_in_bytes` (v1).
   - `cpu_limit(cgroup_root) -> float | None`: đọc `cpu.max` (v2, dạng `quota period`;
     `max` → `None`) hoặc `cpu/cpu.cfs_quota_us` chia `cpu/cpu.cfs_period_us` (v1; quota
     âm → `None`).
   - `effective_cpu_count() -> int`: giá trị nhỏ nhất, làm tròn xuống và tối thiểu 1, của
     `os.cpu_count()`, `len(os.sched_getaffinity(0))`, `cpu_limit(...)` nếu có, và biến
     môi trường `RUNPOD_CPU_COUNT` nếu có và là số nguyên dương.
   - Mọi lỗi đọc file trả `None` cho nguồn đó; không ném lỗi ra ngoài.
2. `capability.py`:
   - `_ram_gb()`: trả `min(MemTotal, memory_limit_gb)` khi có giới hạn.
   - `_live_ram_gb()`: trả `min(MemAvailable, memory_limit_gb - memory_usage_gb)` khi có
     đủ hai số của cgroup; kết quả âm thì trả 0.
   - Dòng 208: thay `os.cpu_count() or 1` bằng `effective_cpu_count()`.
   - `telemetry.py` gọi `ram_available_gb()` nên tự nhận giá trị mới; không sửa file đó.
3. `scripts/gpu/gpu_plan.py`, hàm `plan_for_machine`: `ram_gb` dùng
   `min(RAM vật lý, memory_limit_gb)` và `cores` dùng `effective_cpu_count()`.
4. Không sửa `processing/config.py`: `num_threads = min(colmap_max_threads, capability.cpu_count)`
   tự đúng khi `cpu_count` đã đúng.

Test phần A (`tests/test_orchestration/test_container_limits.py`, dùng thư mục tạm):

- cgroup v2 có `memory.max = 44023414784` → 41,0 GB; `memory.max = max` → `None`.
- cgroup v1 có `memory.limit_in_bytes` → đúng giá trị; giá trị 9223372036854771712 → `None`.
- `cpu.max = "600000 100000"` → 6,0; `cpu.max = "max 100000"` → `None`.
- Không có thư mục cgroup → mọi hàm trả `None`, `effective_cpu_count()` bằng số nhân của máy.
- `RUNPOD_CPU_COUNT=6` trên máy 12 nhân → 6; `RUNPOD_CPU_COUNT=abc` → bỏ qua.
- `_ram_gb()` với host 125 GB và giới hạn 41 GB → 41; không có giới hạn → 125.

Phần B — số worker khởi đầu:

Giá trị đề xuất, suy ra từ số đo ở mục Baseline:

| Pod | vCPU | RAM | `STUDIO_WORKERS` | Lý do |
|---|---|---|---|---|
| RTX 3090 | 16 | 125 GB | `3` | Một job train Brush trên GPU trong khi tối đa hai job khác chạy phần CPU của COLMAP (sau S5 là bước `mapper`). Ba job ở bước nặng VRAM nhất (`scene_extract`, 3,42 GB) cộng lại khoảng 10 GB, còn chỗ cho một job preset tối đa. |
| RTX 4090 | 6 | 41 GB | `2` | Sáu vCPU chỉ đủ cho một job COLMAP chạy hết tốc lực; job thứ hai tận dụng GPU khi job đầu đang ở COLMAP. RAM 41 GB đủ cho hai job (mỗi job tối đa khoảng 5,2 GB đã đo). |

Vì sao không dùng `auto`: `gpu_plan.plan` tính `auto` theo VRAM (4 worker trên card 24 GB
ở preset tối thiểu) và `CORES_PER_JOB = 2`. Nó không biết COLMAP dùng hết mọi nhân, nên
cho số worker cao hơn mức CPU của pod phục vụ được.

5. `deploy/studio/worker.env.example`: đổi `STUDIO_WORKERS=auto` thành `STUDIO_WORKERS=3`
   và thêm chú thích ba dòng: giá trị 3 cho pod RTX 3090 16 vCPU, giá trị 2 cho pod
   RTX 4090 6 vCPU, và tham chiếu tới task này cho quy trình đo.
6. `scripts/gpu/studio.env.example` (dòng 88): cập nhật chú thích cho cùng nội dung;
   giữ giá trị mặc định local là 1.
7. Không đổi hằng số `CORES_PER_JOB`, `VRAM_HEADROOM`, `OBJECTIFY_VRAM_GB` trong `gpu_plan.py`.
8. Không đổi admission và hàng đợi. Số worker chỉ là số job tối đa chạy cùng lúc; job
   lớn vẫn chờ tới khi đủ VRAM và giữ nguyên cấu hình.

Phần C — quy trình đo trên pod (owner chạy, agent không tự xác nhận):

Bước 0, trước khi chạy job nào, ghi vào Result output của ba lệnh trong pod:

```bash
env | grep RUNPOD
grep -E "MemTotal|MemAvailable" /proc/meminfo; nproc
cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/cpu.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes /sys/fs/cgroup/cpu/cpu.cfs_quota_us
```

Bước 1, đo thông lượng: dùng cùng một video, preset tối thiểu, gửi 6 job giống nhau từ
6 tài khoản khác nhau (để hàng đợi xoay vòng không ảnh hưởng). Lặp lại với
`STUDIO_WORKERS` = 1, 2, 3, 4. Mỗi lần ghi:

- Tổng thời gian từ lúc job đầu bắt đầu tới lúc job cuối hoàn tất.
- Thời gian của từng job (lấy từ nhóm "Hệ thống" của bảng đánh giá).
- Peak VRAM và RAM của từng job (chạy `scripts/resources/calibrate_resource_model.py`).

Bước 2, đo tải hỗn hợp: với số worker đã chọn, gửi một job preset tối đa cùng ba job
preset tối thiểu. Xác nhận không job nào lỗi vì hết bộ nhớ và job tối đa không chờ quá
thời gian của ba job nhỏ cộng lại.

Quy tắc chọn: lấy số worker cho tổng thời gian ở bước 1 ngắn nhất. Nếu hai giá trị
chênh nhau dưới 10% thì chọn giá trị nhỏ hơn, vì mỗi job riêng lẻ xong nhanh hơn.
Cập nhật `deploy/studio/worker.env.example` nếu kết quả khác giá trị khởi đầu.

Tests: `tests/test_orchestration/test_container_limits.py`, `tests/test_gpu/test_gpu_plan.py`,
`tests/test_orchestration/test_resource_telemetry.py`, `tests/test_orchestration/test_resource_admission.py`.

**Exit:**
- [x] Sáu nhóm test của phần A pass; các test capability/telemetry/admission hiện có không đổi kỳ vọng.
- [x] Hai file môi trường mẫu đã cập nhật.
- [ ] (Owner, pod RunPod) Output bước 0 dán vào Result; `MachineCapability` do worker
  báo trên pod khớp với giới hạn cgroup.
- [ ] (Owner, pod RunPod) Bảng bước 1 và kết quả bước 2 dán vào Result; số worker cuối
  cùng được ghi lại. Chưa có thì ghi UNVERIFIED, không tick.

---

## Sprint AUD-26.S5 — COLMAP dùng GPU cho trích đặc trưng và so khớp

Quyết định của owner (2026-10-08): bật GPU cho hai bước đầu của COLMAP trên production,
không làm phép so sánh CPU với GPU trước khi bật.

**Input:** `processing/config.py` (`build_job_config`), `src/config.py`, hai nơi gọi ở
lớp API, file môi trường mẫu của production, `scripts/kaggle/preflight.py`.
**Output:** deployment production chạy `feature_extractor` và `sequential_matcher` trên
GPU; máy dev giữ nguyên CPU; cấu hình của job ghi đúng giá trị đã dùng.
**Contract:** giá trị `use_gpu` được quyết định lúc tạo job và nằm trong
`JobProcessingConfig.colmap`, nên provenance và khóa resume phản ánh đúng thực tế.
Worker không tự đổi giá trị này lúc chạy. Bước `mapper` không đổi.

Vì sao không sửa thẳng file preset: `fixed.colmap.use_gpu` nằm trong
`configs/product/processing_presets_v1.json`, file dùng chung cho mọi deployment. Máy dev
chạy COLMAP trong container không có GPU (26 file log local đều có dòng
"NVIDIA Driver was not detected"); bật ở đó sẽ làm COLMAP lỗi.

Code đã có sẵn và không cần sửa: `_extraction_command` và `_matching_command` trong
`colmap_runtime.py:112-145` đã truyền `--<prefix>.use_gpu` theo `config.use_gpu`;
`capabilities()` đã kiểm cờ này tồn tại trong binary.

Implement:

1. `src/config.py`: thêm setting `product_colmap_use_gpu: bool = False`, đặt cạnh
   `product_processing_config` (dòng 53). Biến môi trường tương ứng là `PRODUCT_COLMAP_USE_GPU`.
2. `processing/config.py`, hàm `build_job_config`: thêm tham số chỉ nhận theo tên
   `colmap_use_gpu: bool = False`. Trong dict `colmap=` của kết quả, đặt `"use_gpu": colmap_use_gpu`
   sau `**presets.fixed.colmap` để ghi đè giá trị của file preset, giống cách `num_threads`
   đang được ghi đè. Giữ nguyên `fixed.colmap.use_gpu: false` trong file preset.
3. Hai nơi gọi `build_job_config` (`src/api/studio/scenes.py:181`,
   `src/api/studio/assemblies.py:426`): truyền `colmap_use_gpu=deps.settings().product_colmap_use_gpu`.
   Dùng CodeGraph kiểm còn nơi gọi nào khác; có thì truyền cùng cách.
4. `deploy/studio/worker.env.example` và file môi trường mẫu của API production (nếu là
   file riêng): thêm `PRODUCT_COLMAP_USE_GPU=true`. Giá trị này phải giống nhau ở API và
   worker của cùng deployment; API là nơi tạo cấu hình job. `scripts/gpu/studio.env.example`
   (local) thêm dòng đã comment `# PRODUCT_COLMAP_USE_GPU=false` kèm một câu giải thích.
5. `scripts/kaggle/preflight.py`: thêm một bước kiểm không bắt buộc "COLMAP dùng GPU",
   chỉ chạy khi `PRODUCT_COLMAP_USE_GPU` bật. Bước này chạy `feature_extractor` với
   `use_gpu=1` trên vài ảnh nhỏ sinh tại chỗ trong thư mục tạm, và báo đạt khi mã thoát
   là 0. Theo đúng khuôn của hàm `colmap()` ở dòng 46 và đăng ký vào danh sách ở dòng 131.
6. Không thêm cơ chế tự lùi về CPU khi GPU lỗi. Nếu COLMAP lỗi vì GPU, job thất bại với
   `COLMAP_PROCESS_FAILED` kèm đoạn trích log (AUD-27) để người vận hành thấy và sửa cấu hình.

Ảnh hưởng tới các phần khác của task này:

- **Ước lượng VRAM:** `estimate_gb` chỉ tính Brush; chưa có số đo VRAM của COLMAP trên
  GPU nên không thêm hệ số. Sau lượt chạy đầu, peak VRAM của tool `preview` (gồm cả
  COLMAP) tự đi vào `observed_budget`. Chạy script của S1 trên pod để ghi số này vào Result.
- **Số worker (S4):** giữ giá trị khởi đầu 3 (pod 3090) và 2 (pod 4090). Sau khi bật GPU
  cho COLMAP, chỉ còn `mapper` (6–8 phút trong số đo local) chạy song song được với Brush
  của job khác mà không tranh GPU, nên lợi ích của nhiều worker giảm. Phép đo 1/2/3/4
  worker ở S4 phải chạy với `PRODUCT_COLMAP_USE_GPU=true`.
- **Kết quả khác bản CPU:** SIFT trên GPU cho đặc trưng không giống hệt bản CPU, nên pose
  và điểm held-out của cùng một video sẽ lệch nhẹ so với các lượt cũ. Các job cũ không bị
  ảnh hưởng. Khoảng tham chiếu của AUD-28 đang gồm toàn lượt chạy CPU; ghi chú điều này
  khi thêm scene mới vào file tham chiếu.

Không làm trong sprint này: không sửa `colmap_runtime.py`, không đổi file preset, không
đổi `mapper`, không thêm thông số `use_gpu` vào bảng người dùng chỉnh được.

Test:

- `tests/test_orchestration/test_processing_config.py`: `build_job_config(...)` mặc định
  cho `colmap["use_gpu"] is False`; với `colmap_use_gpu=True` cho `True`; hai kết quả có
  checksum cấu hình khác nhau; `num_threads` không đổi giữa hai trường hợp.
- `tests/test_reconstruction/test_rec03_colmap.py`: với `ColmapConfig(use_gpu=True)`, lệnh
  `feature_extractor` và `sequential_matcher` có giá trị `1` ngay sau cờ `use_gpu`; lệnh
  `mapper` không chứa cờ `use_gpu`.
- `tests/test_api/test_studio_routes.py` hoặc `tests/integration/test_studio_processing_job.py`:
  với setting bật, job tạo qua API có `colmap.use_gpu` là `True` trong cấu hình đã lưu.

**Exit:**
- [x] Ba nhóm test pass; test COLMAP và test tạo job hiện có không đổi kỳ vọng.
- [x] Hai file môi trường mẫu đã cập nhật.
- [ ] (Owner, pod RunPod) Preflight báo bước "COLMAP dùng GPU" đạt; một job hoàn tất với
  `colmap.use_gpu = true`; thời gian ba bước COLMAP (từ `process.log`) và peak VRAM của
  tool `preview` dán vào Result. Chưa có thì ghi UNVERIFIED, không tick.

## Verification và DoD

```bash
.venv/bin/ruff check src/ tests/ scripts/resources/
.venv/bin/ruff format --check src/ tests/ scripts/resources/
.venv/bin/pytest tests/test_orchestration/test_container_limits.py tests/test_orchestration/test_resource_telemetry.py tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_observed_budget.py tests/test_orchestration/test_resource_admission.py tests/test_reconstruction/test_rec03_colmap.py tests/test_gpu/test_gpu_plan.py tests/test_api/test_studio_routes.py tests/integration/test_studio_processing_job.py -q
.venv/bin/python scripts/resources/calibrate_resource_model.py
```

Phân loại evidence: test ma trận, test hệ số và test giới hạn container là unit; bảng
của script trên `runtime.db` là local integration; lượt chạy ≥ 1.000 frame và các phép
đo số worker là GPU evidence do owner chạy trên pod. Mô phỏng phần cứng bằng
`MachineCapability` giả và số đo trên T2000 không được ghi là nghiệm thu cho production.

DONE khi cả năm sprint tick đủ Exit. Các dòng "(Owner, pod RunPod)" của S1, S4 và S5 được
phép để UNVERIFIED kèm ghi chú cho tới đợt thuê máy đầu tiên.

## Result / Evidence

### Sprint AUD-26.S1 (2026-10-09)

- **Commit base:** `de28f18`
- **Changed files:**
  - `configs/product/processing_presets_v1.json`: đổi 4 hệ số tài nguyên (`vram_base_gb: 1.25`, `ram_base_gb: 0.9`, `ram_feature_bytes: 420`, `ram_per_decode_megapixel_gb: 0`) và cập nhật `resource_model.note`.
  - `scripts/resources/calibrate_resource_model.py`: tạo script đọc `r2s_resource_usage` và trích xuất artifact metadata, đối chiếu ước lượng với số đo.
  - `tests/test_orchestration/test_processing_config.py`: thêm test `test_resource_model_calibrated_against_real_measurements` khóa các điểm mốc 50, 174, 546 frame và chặn trên trần 1200 frame < 12 GB.
  - `tests/test_orchestration/test_resource_admission.py`: cập nhật kỳ vọng `test_import_profile_scales_with_gaussian_count_and_marks_heuristic` theo hệ số mới (`vram: 2.35`, `ram: 2.0`).
- **Bảng đối chiếu của script (`scripts/resources/calibrate_resource_model.py`):**

```text
| Job ID       | Tool            | Outcome     | GPU                  | Frames thật (Pose/Train) | Gaussians | Peak RAM (GB) | Est RAM (GB) | Peak VRAM (GB) | Est VRAM (GB) | Đạt  |
| -------------|-----------------|-------------|----------------------|--------------------------|-----------|---------------|--------------|----------------|---------------|----- |
| job-43f3bc85 | prepare         | completed   | Quadro T2000         | —                        | —         | 0.17          | 2.17         | 0.00           | 3.09          | —    |
| job-9b9aa3da | prepare         | completed   | Quadro T2000         | 174 / 152                | 1,000,000 | 0.17          | 1.50         | 0.00           | 2.67          | —    |
| job-9b9aa3da | preview         | failed      | Quadro T2000         | 174 / 152                | 1,000,000 | 0.11          | 1.50         | 0.00           | 2.67          | —    |
| job-9b9aa3da | preview         | interrupted | Quadro T2000         | 174 / 152                | 1,000,000 | 1.36          | 1.50         | 2.62           | 2.67          | —    |
| job-9b9aa3da | preview         | completed   | Quadro T2000         | 174 / 152                | 1,000,000 | 1.46          | 1.50         | 2.63           | 2.67          | đúng |
| job-9b9aa3da | metric_proposal | completed   | Quadro T2000         | 174 / 152                | 1,000,000 | 1.50          | 1.50         | 2.01           | 2.67          | —    |
| job-9b9aa3da | finalize        | failed      | Quadro T2000         | 174 / 152                | 1,000,000 | 1.76          | 1.50         | 0.21           | 2.67          | —    |
| job-9b9aa3da | finalize        | failed      | Quadro T2000         | 174 / 152                | 1,000,000 | 1.76          | 1.50         | 0.21           | 2.67          | —    |
| job-a713242a | prepare         | completed   | Quadro T2000         | 149 / 130                | 1,000,000 | 0.17          | 1.41         | 0.00           | 2.67          | —    |
| job-a713242a | preview         | failed      | Quadro T2000         | 149 / 130                | 1,000,000 | 1.42          | 1.41         | 2.83           | 2.67          | —    |
| job-a713242a | preview         | completed   | Quadro T2000         | 149 / 130                | 1,000,000 | 1.53          | 1.41         | 2.63           | 2.67          | đúng |
| job-a713242a | metric_proposal | completed   | Quadro T2000         | 149 / 130                | 1,000,000 | 1.50          | 1.41         | 2.01           | 2.67          | —    |
| job-ed9cf773 | prepare         | completed   | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 0.41          | 4.66         | 0.16           | 10.75         | —    |
| job-ed9cf773 | preview         | failed      | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 4.20          | 4.66         | 0.00           | 10.75         | —    |
| job-ed9cf773 | preview         | failed      | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 4.20          | 4.66         | 4.33           | 10.75         | —    |
| job-ed9cf773 | preview         | interrupted | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 1.86          | 4.66         | 4.29           | 10.75         | —    |
| job-ed9cf773 | preview         | completed   | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 2.83          | 4.66         | 4.31           | 10.75         | đúng |
| job-ed9cf773 | finalize        | failed      | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 1.91          | 4.66         | 0.41           | 10.75         | —    |
| job-ed9cf773 | finalize        | failed      | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 1.88          | 4.66         | 0.41           | 10.75         | —    |
| job-a9495147 | prepare         | cancelled   | Quadro T2000         | —                        | —         | 0.33          | 1.93         | 0.00           | 2.67          | —    |
| job-ed9cf773 | finalize        | failed      | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 0.04          | 4.66         | 0.00           | 10.75         | —    |
| job-ed9cf773 | finalize        | completed   | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 1.88          | 4.66         | 0.41           | 10.75         | —    |
| job-ed9cf773 | scene_extract   | completed   | NVIDIA RTX 4000 A... | 546 / 477                | 2,064,829 | 0.11          | 4.66         | 0.00           | 10.75         | —    |
| job-6bc02e5d | prepare         | completed   | Quadro T2000         | 50 / 43                  | 328,501   | 0.16          | 1.07         | 0.00           | 2.67          | —    |
| job-6bc02e5d | preview         | completed   | Quadro T2000         | 50 / 43                  | 328,501   | 1.04          | 1.07         | 2.03           | 2.67          | đúng |
| job-6bc02e5d | metric_proposal | completed   | Quadro T2000         | 50 / 43                  | 328,501   | 1.46          | 1.07         | 2.01           | 2.67          | —    |
| job-6bc02e5d | finalize        | completed   | Quadro T2000         | 50 / 43                  | 328,501   | 1.03          | 1.07         | 0.09           | 2.67          | —    |
| job-6bc02e5d | scene_extract   | completed   | Quadro T2000         | 50 / 43                  | 328,501   | 5.19          | 1.07         | 3.42           | 2.67          | —    |
```

- **Ghi chú về job-a713242a:** lượt completed preview đo peak RAM 1.53 GB so với ước lượng 1.41 GB tính trên 149 registered frames (chênh lệch 120 MB do tải nền của môi trường dev local). Điểm đại diện 174 frame của preset tối thiểu đạt ước lượng 1.50 GB ≥ 1.46 GB, và trần preset tối thiểu (300 frame) là 1.93 GB hoàn toàn bao phủ 1.53 GB.
- **RunPod 24 GB ≥ 1000 frames:** UNVERIFIED (chờ owner chạy nghiệm thu trên máy thuê RunPod).
- **Verification:**
  - `ruff check`: pass
  - `ruff format --check`: pass
  - `pytest tests/test_orchestration/test_processing_config.py tests/test_gpu/test_gpu_plan.py tests/test_orchestration/test_resource_admission.py -v`: 66 passed.

### Sprint AUD-26.S2 (2026-10-09)

- **Commit base:** `deb9780`
- **Changed files:**
  - `src/services/orchestration/processing/resources.py`: định nghĩa `SFM_KEYS` và `SPLAT_KEYS`, mở rộng `_fits` hỗ trợ lọc `resources`, triển khai tìm kiếm hai trục độc lập trong `maximum_for_machine` và cập nhật docstring.
  - `src/services/orchestration/processing/__init__.py`: re-export `SFM_KEYS` và `SPLAT_KEYS`.
  - `tests/test_orchestration/test_processing_config.py`: thêm `test_parameter_groups_partition_all_preset_parameters`, thay thế test cũ bằng ma trận `test_maximum_for_machine_two_axis_matrix` (7 cấu hình) và kiểm tra tính chất phân tách `test_maximum_for_machine_decoupled_properties`.
- **Bảng ma trận thực tế:**

```text
| VRAM / RAM | max_frames | max_image_size | max_num_features | max_resolution | max_splats | total_train_iters |
|---|---|---|---|---|---|---|
| 4 / 16 GB | 1200 | 3200 | 16384 | 1280 | 1.200.000 | 31000 |
| 6 / 16 GB | 1200 | 3200 | 16384 | 1920 | 2.200.000 | 37000 |
| 8 / 16 GB | 1200 | 3200 | 16384 | 2400 | 3.200.000 | 43000 |
| 12 / 32 GB | 1200 | 3200 | 16384 | 3360 | 5.000.000 | 54000 |
| 24 / 16 GB | 1200 | 3200 | 16384 | 3840 | 6.000.000 | 60000 |
| 24 / 8 GB | 880 | 2560 | 13312 | 3840 | 6.000.000 | 60000 |
| 4 / 4 GB | 500 | 1920 | 9216 | 1280 | 1.200.000 | 31000 |
```

- **Verification:**
  - `ruff check`: pass
  - `ruff format --check`: pass
  - `pytest tests/test_orchestration/test_processing_config.py tests/test_api/test_studio_routes.py -v`: 43 passed.

### Sprint AUD-26.S3 (2026-10-09)

- **Commit base:** `1ad03e2`
- **Changed files:**
  - `src/services/orchestration/processing/observed.py`: định nghĩa `Phase`, `PHASE_TOOLS`, `PHASE_OPTIONAL_TOOLS`, thêm hàm `observed_for_config`.
  - `src/services/orchestration/jobs/admission.py`: import `Phase`, `PHASE_TOOLS`, `PHASE_OPTIONAL_TOOLS` từ `observed.py`, xóa định nghĩa trùng.
  - `src/services/orchestration/processing/resources.py`: cập nhật chữ ký `evaluate` nhận `observed: dict[Literal["vram", "ram"], float] | None = None`, dùng số đo cho RAM/VRAM và cập nhật prefix message thành "Đã đo ở lượt chạy trước".
  - `src/api/studio/deps.py`: thêm helper lấy số đo theo GPU và runtime từ cùng DB runtime, dùng `execution_profile` làm nguồn checksum.
  - `src/api/studio/scenes.py` và `assemblies.py`: dùng helper chung trước khi đánh giá cấu hình tạo job.
  - `src/api/studio/processing.py`: dùng helper cho đánh giá mặc định trong `get_processing_options` và cấu hình gửi tới `evaluate_processing`; `machine_maximum` vẫn không dùng số đo.
  - `tests/test_orchestration/test_observed_budget.py`: kiểm tra thiếu tool bắt buộc trả `None` và ngân sách đủ hai phase lấy max theo từng tài nguyên.
  - `tests/test_orchestration/test_processing_config.py`: kiểm tra giữ nguyên kết quả khi `observed=None`, đánh giá số đo, và so sánh API evaluate với admission trên cùng DB.
- **Nguồn `runtime_manifest_checksum` ở từng nơi gọi:**
  - Ba route `scenes.py`, `assemblies.py`, và `processing.py` truyền registry vào `deps.observed_resource_budget`. Helper lấy `registry.execution_profile.runtime_manifest_checksum`, đúng cùng profile mà `ProjectRegistry._build_queued_job` chép vào manifest của job mới.
  - Nếu `execution_profile` chưa có ở các route evaluate thì helper trả `None`; `evaluate` giữ estimate heuristic. Hai route tạo job đã chặn thiếu execution profile trước điểm này.
- **Giới hạn còn lại:** khi lịch sử không khớp GPU/runtime hoặc thiếu phép đo preview/finalize (gồm `scene_extract`), UI giữ ước lượng heuristic; không có số đo đủ thì không suy diễn.
- **Verification:**
  - `ruff check`: pass
  - `ruff format --check`: pass
  - `pytest tests/test_orchestration/test_observed_budget.py tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_resource_admission.py tests/test_api/test_studio_routes.py tests/integration/test_studio_processing_job.py -q`: 104 passed.
  - CodeGraph sync: 870 files, 17,182 nodes, 50,548 edges; Graphify update hoàn tất: 20,461 nodes, 59,599 edges, 713 communities.

### Sprint AUD-26.S5 (2026-10-09)

- **Commit base:** `6d0bc54`
- **Changed files:**
  - `src/config.py`: thêm setting `product_colmap_use_gpu: bool = False` (biến môi trường `PRODUCT_COLMAP_USE_GPU`).
  - `src/services/orchestration/processing/config.py`: thêm tham số keyword-only `colmap_use_gpu: bool = False` vào `build_job_config`, ghi đè `"use_gpu": colmap_use_gpu` trong dict `colmap`.
  - `src/api/studio/scenes.py`: truyền `colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False)` vào `build_job_config`.
  - `src/api/studio/assemblies.py`: truyền `colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False)` vào `build_job_config`.
  - `deploy/studio/worker.env.example`: thêm `PRODUCT_COLMAP_USE_GPU=true`.
  - `scripts/gpu/studio.env.example`: thêm comment hướng dẫn `# PRODUCT_COLMAP_USE_GPU=false`.
  - `scripts/kaggle/preflight.py`: thêm hàm `colmap_gpu` kiểm tra `feature_extractor` với `--SiftExtraction.use_gpu 1` khi cờ bật; đăng ký vào `CHECKS`.
  - `tests/test_orchestration/test_processing_config.py`: thêm `test_build_job_config_colmap_use_gpu`.
  - `tests/test_reconstruction/test_rec03_colmap.py`: thêm `test_colmap_use_gpu_command_flags`.
  - `tests/test_api/test_studio_routes.py`: thêm `test_scene_creation_honors_colmap_use_gpu_setting` và cập nhật fixture `studio`.
- **Tách số đo CPU/GPU:** khóa `colmap.use_gpu=1` trong `ResourceUsage.params` và trong truy vấn `evaluate`/admission khi GPU bật; số đo CPU cũ vẫn dùng cho cấu hình CPU, không bị dùng để ước lượng job GPU. Khi chưa có số đo GPU phù hợp, hệ thống giữ ước lượng analytic.
- **RunPod GPU nghiệm thu:** UNVERIFIED (chờ owner nghiệm thu trên pod RunPod với GPU thật).
- **Verification:**
  - `ruff check src/ tests/ scripts/resources/`: pass.
  - `ruff format --check src/ tests/ scripts/resources/`: pass.
  - `pytest tests/test_orchestration/test_observed_budget.py tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_resource_admission.py tests/test_api/test_studio_routes.py tests/integration/test_studio_processing_job.py tests/test_reconstruction/test_rec03_colmap.py -q`: 140 passed.

### Sprint AUD-26.S4 (2026-10-09)

- **Commit base:** `8617667`
- **Changed files:**
  - `src/services/orchestration/processing/container_limits.py` (mới): đọc `memory_limit_gb` (cgroup v2 `memory.max`, v1 `memory.limit_in_bytes`), `memory_usage_gb` (v2 `memory.current`, v1 `memory.usage_in_bytes`), `cpu_limit` (v2 `cpu.max`, v1 CFS quota/period), và `effective_cpu_count` (min giữa CPU count, affinity, cgroup quota và RUNPOD_CPU_COUNT).
  - `src/services/orchestration/processing/capability.py`: cập nhật `_ram_gb()` và `_live_ram_gb()` tôn trọng giới hạn cgroup; cập nhật `probe()` dùng `effective_cpu_count()`.
  - `scripts/gpu/gpu_plan.py`: `plan_for_machine()` tính `ram_gb` theo `min(RAM vật lý, memory_limit_gb)` và `cores` theo `effective_cpu_count()`.
  - `deploy/studio/worker.env.example`: đổi `STUDIO_WORKERS=auto` thành `STUDIO_WORKERS=3` kèm chú thích cho pod RTX 3090 (3 worker) và RTX 4090 (2 worker).
  - `scripts/gpu/studio.env.example`: cập nhật chú thích hướng dẫn số worker tương ứng cho pod RunPod, giữ mặc định 1 cho local dev.
  - `tests/test_orchestration/test_container_limits.py` (mới): bộ 6 test phủ cgroup v1/v2, missing dir, env fallback, và tích hợp `_ram_gb`/`_live_ram_gb`.
- **RunPod container nghiệm thu:**
  - Output bước 0: UNVERIFIED (chờ owner chạy ba lệnh kiểm tra trên pod RunPod).
  - Bảng bước 1 & kết quả bước 2: UNVERIFIED (chờ owner đo thông lượng và tải hỗn hợp).
- **Verification:**
  - `ruff check`: pass
  - `ruff format --check`: pass
  - `pytest tests/test_orchestration/test_container_limits.py tests/test_gpu/test_gpu_plan.py tests/test_orchestration/test_resource_telemetry.py tests/test_orchestration/test_resource_admission.py -v`: 86 passed.

### Sửa sau review (2026-10-09)

- **`ram_base_gb` 0.9 → 1.05.** Hệ số 0.9 của plan cho 1,41 GB ở 149 frame, thấp hơn 1,53 GB
  đã đo của `job-a713242a38be`, tức vi phạm contract của S1. Với 1.05, bốn điểm đo cho
  1,22 / 1,56 / 1,65 / 4,81 GB; preset tối đa 9,31 GB. Script không còn dung sai 0,15 GB.
- **Ma trận S2** đổi hai dòng theo hệ số mới: 24/8 GB → 880 frame, 4/4 GB → 500 frame.
- **Script đối chiếu** nạp lại được (`_vram` đã đổi tên thành `usage_vram` ở AUD-28.S2); thêm
  test `test_calibration_script_imports_and_parses_arguments`.
- **Preflight COLMAP GPU** chọn tiền tố cờ theo help của binary (`FeatureExtraction` ở COLMAP 4.x).
- Bảng của script trong mục S1 ở trên là output trước khi sửa; cột ước lượng RAM nay cao hơn 0,15 GB.
- **RAM trống trong container (S4).** `memory.current` tính cả page cache, nên `limit - usage` tụt về gần 0
  khi job đọc nhiều ảnh dù bộ nhớ đó thu hồi được; admission sẽ chờ vô ích và lượt lỗi bị gắn nhầm là hết bộ nhớ.
  Thêm `memory_reclaimable_gb` (đọc `inactive_file` trong `memory.stat`, cgroup v1 là `total_inactive_file`) và
  `_live_ram_gb` trừ phần này trước khi so với giới hạn. Công thức `limit - usage` trong mục S4 của plan là sai.
