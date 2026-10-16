# T-036: Đổi tên thư mục runtime và biến môi trường `RECxx_*` theo chức năng

## Goal
Thư mục runtime trong `data/` và biến môi trường cấu hình runtime mang tên theo chức năng, không theo mã task cũ
(`rec04`, `REC03_`…). Webapp, worker, 3 scene trong Studio và 5 scene mẫu chạy như trước. Tên biến cũ vẫn được nhận
(kèm cảnh báo), để máy GPU thuê, Docker của teammate và file env cũ không hỏng.

## Vì sao việc này dễ sai (đọc kỹ trước khi làm)
1. **Stack đang chạy** (API cổng 8010 + 1 worker + Next dev) qua `scripts/gpu/run_stack.sh scripts/gpu/studio.env`, do
   một phiên khác bật. Đổi tên thư mục khi worker đang chạy job → job hỏng giữa chừng.
2. `scripts/gpu/studio.env` là file **riêng của máy, không nằm trong git** (quyền 600). Stack đọc biến từ đây chứ không
   phải từ `.env`. `Makefile.studio` chỉ sinh file này khi chưa có, nên sửa template trong Makefile **không** cập nhật
   file đang dùng: phải sửa cả hai.
3. `data/objectgs_runtime/python` là **môi trường conda**: tiền tố tuyệt đối được ghi vào `.so` và script bên trong.
   Dời đi là hỏng. **Không đổi tên, không dời `objectgs_runtime`.**
4. `configs/product/input_runtime_qualification_v1.json` dùng tên biến cũ làm khoá trong `requires`, và
   `registry_version` được tính từ checksum của **cả file này**. Job LiDAR đã lưu so `qualification_evidence_checksum`
   với registry (`registry.py:1533`, `1545`, `1573`; `persistence.py:463`). **Không sửa file này.** Code đọc nó phải ánh
   xạ tên cũ → tên mới (xem bước 2).
5. Artifact của job đã lưu có đường dẫn `attempts/<id>/rec04/...`. Đó là tên **thư mục stage trong URI artifact**, không
   phải runtime. **Không đổi** bất kỳ đoạn `rec0x` nào trong URI artifact, stage id, tên module hay tên file test.
6. Console script trong venv (`bin/pip`, `bin/kiss_icp_pipeline`…) có shebang tuyệt đối. Code gọi runtime bằng
   `bin/python` (vẫn chạy sau khi dời), nhưng shebang phải được sửa để không bỏ lại script hỏng.

## Phạm vi

### A. Đổi tên thư mục (chỉ 3 thư mục; giữ nguyên vị trí ngay dưới `data/`, hậu tố `_runtime` như hai thư mục còn lại)

| Cũ | Mới | Chứa gì |
| --- | --- | --- |
| `data/rec04_runtime` | `data/reconstruction_runtime` | lệnh chạy COLMAP qua Docker, Brush 0.3.0, splat-transform (Node) |
| `data/rec07_runtime` | `data/lidar_open3d_runtime` | venv Python + Open3D cho công cụ LiDAR offline (REC-07/08/09) |
| `data/lidar_runtime` | `data/lidar_odometry_runtime` | venv Python + KISS-ICP (luồng LiDAR thô R5/R6) |

Giữ nguyên: `data/scene_runtime` (tên đã đúng chức năng), `data/objectgs_runtime` (conda, xem mục 3 ở trên).
Không đổi đường dẫn **trong container** (`/opt/real2sim/...`): đó là phần đóng gói của teammate.

### B. Đổi tiền tố biến môi trường (6 lớp settings, đổi cả tiền tố nên mọi trường đi theo)

| Tiền tố cũ | Tiền tố mới | Lớp | File |
| --- | --- | --- | --- |
| `REC03_COLMAP_` | `R2S_COLMAP_` | `ColmapRuntimeSettings` | `src/services/reconstruction/adapters/colmap_runtime.py:25` |
| `REC04_BRUSH_` | `R2S_BRUSH_` | `BrushRuntimeSettings` | `src/services/reconstruction/adapters/brush_runtime.py:35` |
| `REC04_SPLAT_` | `R2S_SPLAT_` | `SplatRuntimeSettings` | `src/services/reconstruction/adapters/splat.py:21` |
| `REC05_VOXEL_` | `R2S_VOXEL_` | `VoxelRuntimeSettings` | `src/services/reconstruction/adapters/voxel_runtime.py:24` |
| `REC06_MOGE_` | `R2S_MOGE_` | `MogeSettings` | `src/services/reconstruction/metric_proposal.py:59` |
| `REC17_LIDAR_ODOMETRY_` | `R2S_LIDAR_ODOMETRY_` | `LidarOdometryRuntimeSettings` | `src/services/reconstruction/lidar/odometry.py:177` |

Ví dụ: `REC03_COLMAP_COMMAND` → `R2S_COLMAP_COMMAND`, `REC04_BRUSH_LPIPS_PYTHON` → `R2S_BRUSH_LPIPS_PYTHON`,
`REC17_LIDAR_ODOMETRY_WORK_ROOT` → `R2S_LIDAR_ODOMETRY_WORK_ROOT`.

### Ngoài phạm vi (không đụng)
- `Dockerfile`, `Dockerfile.gpu`, `docker-compose*.yml`, `deploy/**`, `scripts/gpu/docker_entrypoint.sh`,
  `tests/test_packaging/test_compose_config.py`: phần đóng gói của teammate. Chúng vẫn chạy nhờ tên cũ được nhận.
  Ghi danh sách dòng cần đổi vào report để chuyển cho teammate.
- Biến chỉ dùng cho smoke/test: `REC03_SMOKE_*`, `REC04_SMOKE_*`, `REC04_PREVIEW_*`, `REC07_SMOKE_*`,
  `REC04_TEST_SPLAT_MODULE`, `REC05_TEST_*`, `REC07_DEBUG`. Chúng đi cùng file smoke mang tên task.
- `configs/product/input_runtime_qualification_v1.json` (bằng chứng đã đóng băng).
- Tài liệu lịch sử: `docs/execution/**`, `docs/plans/completed/**`, `docs/decisions/**`, `.ai/tasks/T-0xx/**` cũ,
  `tasks/**`. Đó là hồ sơ, giữ nguyên chữ cũ.
- Thư mục bằng chứng có chữ `rec0x` trong `data/evidence/`, `data/torwic_slam/derived/`, và mọi URI artifact.

## Thiết kế nhận tên cũ (bắt buộc làm đúng như dưới)

Tạo `src/runtime_env.py`, nguồn duy nhất của bảng đổi tên:

```python
"""Tên biến môi trường của runtime ngoài: tên theo chức năng (`R2S_*`), vẫn nhận tên cũ theo mã task (`RECxx_*`).

Tên cũ chỉ để máy và file env chưa đổi tiếp tục chạy; mỗi tên cũ được dùng sẽ ghi một cảnh báo (một lần mỗi tên).
Khi cả hai cùng có, tên mới thắng.
"""

import logging
import os
from collections.abc import Mapping
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, EnvSettingsSource, PydanticBaseSettingsSource

LEGACY_PREFIXES: dict[str, str] = {
    "R2S_COLMAP_": "REC03_COLMAP_",
    "R2S_BRUSH_": "REC04_BRUSH_",
    "R2S_SPLAT_": "REC04_SPLAT_",
    "R2S_VOXEL_": "REC05_VOXEL_",
    "R2S_MOGE_": "REC06_MOGE_",
    "R2S_LIDAR_ODOMETRY_": "REC17_LIDAR_ODOMETRY_",
}
_warned: set[str] = set()
_log = logging.getLogger(__name__)


def _warn(old: str, new: str) -> None:
    if old not in _warned:
        _warned.add(old)
        _log.warning("Biến môi trường %s là tên cũ, sẽ bỏ; đổi thành %s", old, new)


def legacy_name(new: str) -> str | None:
    for prefix, old_prefix in LEGACY_PREFIXES.items():
        if new.startswith(prefix):
            return old_prefix + new[len(prefix):]
    return None


def runtime_env(env: Mapping[str, str], new: str, default: str = "") -> str:
    """Cho script đọc thẳng dict môi trường: tên mới trước, rồi tên cũ (kèm cảnh báo), rồi `default`."""
    value = env.get(new, "").strip()
    if value:
        return value
    old = legacy_name(new)
    if old is not None and env.get(old, "").strip():
        _warn(old, new)
        return env[old].strip()
    return default


class _LegacyEnvSource(EnvSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        value, key, complex_ = super().get_field_value(field, field_name)
        if value is not None:
            new = key.upper().replace(self.env_prefix.upper(), _new_prefix(self.env_prefix), 1)
            _warn(key.upper(), new)
        return value, key, complex_


def _new_prefix(old_prefix: str) -> str:
    return next(new for new, old in LEGACY_PREFIXES.items() if old == old_prefix.upper())


class RuntimeSettings(BaseSettings):
    """Lớp cha của settings runtime: đọc `R2S_<X>_*`, thiếu thì đọc tên cũ `RECxx_<X>_*`."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        legacy = LEGACY_PREFIXES[settings_cls.model_config["env_prefix"]]
        return (init_settings, env_settings, _LegacyEnvSource(settings_cls, env_prefix=legacy), dotenv_settings,
                file_secret_settings)
```

Đây là phác thảo. Chi tiết `get_field_value` phải kiểm trên pydantic-settings **2.15.0** đang cài (đọc mã nguồn
`EnvSettingsSource` trong `.venv`, không đoán). Yêu cầu hành vi, có test cho từng ý:
- Chỉ có tên mới → đọc tên mới, không cảnh báo.
- Chỉ có tên cũ → đọc tên cũ, cảnh báo đúng một lần mỗi tên.
- Có cả hai, khác giá trị → tên mới thắng.
- Trường kiểu tuple/dict nhận JSON (`R2S_COLMAP_COMMAND='["sh","x"]'`, `R2S_BRUSH_ENVIRONMENT='{...}'`) qua **cả hai**
  tên.
- `extra="forbid"` của các lớp hiện có không làm lỗi khi môi trường có cả biến tên cũ lẫn tên mới. Nếu nguồn env với
  tiền tố cũ bị `forbid` bắt lỗi, dừng lại và ghi vào report (cần Architect), không tự đổi sang `extra="ignore"`.

Sáu lớp ở mục B đổi cha từ `BaseSettings` sang `RuntimeSettings` và đổi `env_prefix` sang tiền tố mới. Không đổi tên
trường hay giá trị mặc định.

Script đọc thẳng `os.environ`/dict phải dùng `runtime_env(env, "R2S_...")`:
`scripts/gpu/qualify_input_runtimes.py` (`_live`, `_splat_version`, `_brush_binary_present`, dòng ~142 và vòng so
`requires` ~dòng 190), `scripts/gpu/make_input_runtime_registry.py` (`build_registry`),
`scripts/gpu/make_runtime_manifest.py`, `scripts/gpu/gpu_plan.py`, `scripts/kaggle/preflight.py`,
`eval/pose/scale_proposal_error.py`, `src/services/reconstruction/adapters/brush.py` (chỉ docstring, dòng 216).
Đọc từng file bằng `codegraph_explore` trước khi sửa; danh sách đầy đủ lấy bằng lệnh ở bước 1.

**Riêng `qualify_input_runtimes.py`:** khoá trong `requires` của bản ghi v1 là tên cũ. Khi so, đổi khoá sang tên mới
bằng một bảng ánh xạ trong `src/runtime_env.py` (ví dụ `requirement_env_name("REC03_COLMAP_RUNTIME_IDENTITY")` →
`"R2S_COLMAP_RUNTIME_IDENTITY"` dựa trên `LEGACY_PREFIXES`), rồi đọc bằng `runtime_env`. Không sửa file JSON.

## Steps

### Bước 0. Chuẩn bị, chưa sửa gì
1. Đặt `status.md` T-036 → `in-progress`.
2. Ghi lại hiện trạng vào thư mục tạm của bạn (không trong repo):
   - `sha256sum data/studio_local/runtime_manifest.json data/studio_local/input_runtime_registry.dev.json`
   - Bản sao `data/studio_local/input_runtime_registry.dev.json` và `runtime_manifest.json`.
   - `curl -s localhost:8010/health`, và mã HTTP của `GET /api/v1/jobs/{id}/scene` cho 3 job
     `job-b8f744da2286`, `job-f3393ecbfbd6`, `job-a14981f78f85`; danh sách scene mẫu qua API thư viện mẫu.
3. Kiểm kê tham chiếu, lưu kết quả để đối chiếu cuối task:
   ```
   grep -rnE "\bREC(03_COLMAP|04_BRUSH|04_SPLAT|05_VOXEL|06_MOGE|17_LIDAR_ODOMETRY)_" \
     --exclude-dir={node_modules,data,graphify-out,.codegraph,.git,.venv,.next} .
   grep -rnE "rec04_runtime|rec07_runtime|lidar_runtime" \
     --exclude-dir={node_modules,data,graphify-out,.codegraph,.git,.venv,.next} .
   ```

### Bước 1. Code nhận cả hai tên (chưa đổi môi trường nào). Commit.
- Tạo `src/runtime_env.py` như thiết kế. Đổi 6 lớp settings.
- Test mới `tests/test_runtime_env_names.py` (đặt ở gốc `tests/`; **không** tạo thư mục `tests/test_config/` vì đã có
  file `tests/test_config.py`, trùng tên module sẽ làm hỏng import): đủ các ý ở mục "Yêu cầu hành vi", tham số hoá qua cả 6 lớp, dùng `monkeypatch.setenv`/`delenv`, và
  `caplog` cho cảnh báo. Reset `_warned` giữa các test bằng fixture.
- Chạy: test mới + các test hiện có của 6 adapter (`tests/test_reconstruction/test_rec04_brush.py`,
  `test_lidar_odometry.py`, `test_rec05_scale.py`, `test_rec06_canonical_visual.py`, test nào khởi tạo `MogeSettings`,
  `ColmapRuntimeSettings`, `VoxelRuntimeSettings`, `SplatRuntimeSettings`; tìm bằng grep tên lớp trong `tests/`).
  Các test hiện có vẫn đặt tên cũ: chúng phải **vẫn xanh** (chứng minh tên cũ chạy).
- Commit: `Read runtime settings from R2S_* names and keep accepting the RECxx_* names`.

### Bước 2. Script và test chuyển sang tên mới. Commit.
- Sửa các script ở mục "Thiết kế" sang `runtime_env(...)`.
- Đổi tên biến trong test (trừ test đóng gói và test smoke ngoài phạm vi) sang tên mới. Giữ **một** test riêng cho tên cũ
  (đã có ở bước 1).
- Thêm test chặn tái phát trong `test_runtime_env_names.py`: quét `src/`, `scripts/` (trừ `scripts/gpu/docker_entrypoint.sh`),
  `Makefile.studio`, `scripts/gpu/studio.env.example`, `eval/` bằng regex của bước 0; chỉ cho phép xuất hiện trong
  `src/runtime_env.py` và chuỗi docstring nói về tên cũ. Test phải đỏ trước khi sửa xong.
- Chạy: `tests/test_runtime_env_names.py`, `tests/test_config.py`, `tests/test_reconstruction/test_qualify_input_runtimes.py`,
  `tests/test_reconstruction/test_input_runtime_registry_script.py`, `tests/test_gpu/test_gpu_plan.py`,
  `tests/test_orchestration/test_worker_cleanup.py`, `tests/test_api/test_studio_routes.py`,
  `tests/test_packaging/test_input_runtime_registry_wiring.py`, và mọi file test đã sửa.
- Commit: `Use the R2S_* runtime variable names in scripts and tests`.

### Bước 3. Makefile, file mẫu, tài liệu đang dùng. Commit.
- `Makefile.studio`: biến `BRUSH`, `SPLAT`, `COLMAP` → `$(ROOT)/data/reconstruction_runtime/...`; `LIDAR_PY` →
  `$(ROOT)/data/lidar_odometry_runtime/bin/python`; target `lidar-runtime` (venv path và chữ trong echo); template
  `studio.env` (dòng ~116–140) sang tên `R2S_*`.
- **Bẫy:** target `registry` (dòng ~152–157) có `ensure REC17_LIDAR_ODOMETRY_PYTHON …` và
  `ensure REC17_LIDAR_ODOMETRY_WORK_ROOT …`: `ensure` chèn biến vào `studio.env` khi chưa có tên đó, nên nếu để tên cũ
  thì mỗi lần `make registry` sẽ chèn lại tên cũ cạnh tên mới. Đổi cả hai sang `R2S_LIDAR_ODOMETRY_*`.
- `scripts/gpu/studio.env.example`, `scripts/gpu/README.md`, `docs/RUNPOD_GUIDE.md`, `README.md` (mục "Bản đồ thư
  mục `data/`" dòng ~195 và bảng có `data/rec07_runtime` dòng ~209), `THIRD_PARTY_NOTICES.md` nếu nhắc đường dẫn,
  `eval/pose/lidar_odometry_benchmark.py` (docstring), `tests/test_reconstruction/test_rec07_prefusion.py` (đường dẫn
  `data/rec07_runtime`), `docs/plans/active/*` chỉ ở chỗ hướng dẫn chạy lệnh.
- README thêm một câu: "Tên biến cũ `RECxx_*` vẫn được nhận và in cảnh báo; bảng đổi tên ở `src/runtime_env.py`."
- Chạy lại test chặn tái phát ở bước 2.
- Commit: `Point Makefile, examples and docs at the renamed runtime folders and variables`.

### Bước 4. Đổi trên máy (không commit; làm tuần tự, dừng ngay khi một bước kiểm thất bại)
1. **Hỏi chủ dự án** trước khi dừng stack: stack do phiên khác bật (tiến trình `run_stack.sh` cha của
   `uvicorn ... --port 8010`). Không tự `kill` khi chưa được đồng ý.
2. Kiểm không có việc đang chạy: không job `RUNNING`/`QUEUED` và không yêu cầu scene đang chạy trong
   `data/studio_local/runtime.db` (đọc ở chế độ chỉ đọc), log worker không có bước đang chạy. Có việc đang chạy → chờ.
3. Dừng stack bằng `kill -TERM <pid run_stack.sh>` (script tự dừng cả ba tiến trình). Kiểm cổng 8010 và tiến trình
   `worker_cli` đã tắt.
4. Sao lưu: `cp -p scripts/gpu/studio.env data/studio_local/backups/studio.env.before-T-036`.
5. Dời thư mục bằng `mv` (cùng phân vùng, không sao chép):
   ```
   mv data/rec04_runtime data/reconstruction_runtime
   mv data/rec07_runtime data/lidar_open3d_runtime
   mv data/lidar_runtime data/lidar_odometry_runtime
   ```
6. Sửa shebang của console script trong hai venv (chỉ file văn bản có shebang trỏ đường dẫn cũ):
   ```
   for pair in "lidar_runtime:lidar_odometry_runtime" "rec07_runtime:lidar_open3d_runtime"; do
     old="$PWD/data/${pair%%:*}"; new="$PWD/data/${pair##*:}"
     grep -lI "^#!$old/" "$new"/bin/* | xargs -r sed -i "1s|^#!$old/|#!$new/|"
     grep -lI "$old" "$new"/bin/activate* | xargs -r sed -i "s|$old|$new|g"
   done
   ```
   Sau đó `grep -rlI "data/lidar_runtime\|data/rec07_runtime" data/lidar_odometry_runtime/bin data/lidar_open3d_runtime/bin`
   phải rỗng.
7. Sửa `scripts/gpu/studio.env`: mọi đường dẫn `data/rec04_runtime` → `data/reconstruction_runtime`,
   `data/lidar_runtime` → `data/lidar_odometry_runtime`; mọi tên `REC03_COLMAP_`/`REC04_BRUSH_`/`REC04_SPLAT_`/
   `REC05_VOXEL_`/`REC06_MOGE_`/`REC17_LIDAR_ODOMETRY_` → tên `R2S_*` tương ứng. Không đổi giá trị nào khác, không in
   nội dung file ra log/report (có thể có khoá). `diff` với bản sao lưu chỉ được khác ở đúng các dòng đó.
8. Kiểm runtime trước khi bật stack:
   - `data/reconstruction_runtime/brush/brush-app-x86_64-unknown-linux-gnu/brush_app --version` in `brush-cli 0.3.0`.
   - File `data/reconstruction_runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs` tồn tại.
   - `data/lidar_odometry_runtime/bin/python -c "import kiss_icp, importlib.metadata as m; print(m.version('kiss-icp'))"`
   - `data/lidar_open3d_runtime/bin/python -c "import open3d; print(open3d.__version__)"` (mong đợi 0.19.0).
9. Sinh lại vào thư mục tạm và so với bản ở bước 0 (**không ghi đè** bản đang dùng nếu khác):
   - `set -a; source scripts/gpu/studio.env; set +a; .venv/bin/python -m scripts.gpu.make_runtime_manifest --out <tmp>/m.json`
     → nội dung trùng `data/studio_local/runtime_manifest.json`.
   - Registry dev: chạy cùng lệnh mà target `registry` của `Makefile.studio` dùng, ghi ra `<tmp>`. Mọi
     `qualification_evidence_checksum` và `runtime_version` của từng capability trùng bản cũ. Khác → dừng, ghi report.
10. Bật lại stack đúng như cũ: `scripts/gpu/run_stack.sh scripts/gpu/studio.env` với `STUDIO_FRONTEND=dev`, chạy nền
    (hỏi chủ dự án muốn bật ở phiên nào). Không có dòng cảnh báo "tên cũ" nào trong log API/worker (studio.env đã đổi).
11. Kiểm sau khi bật: `/health` 200; 3 job ở bước 0 trả cùng mã HTTP; thư viện mẫu liệt kê đủ 5 scene và đọc được
    preview của từng scene; `GET` registry năng lực input của API (route mà frontend dùng) cho cùng trạng thái R1–R6 như
    trước.
12. Job thật: **chỉ khi chủ dự án đồng ý** (máy local, một việc nặng một lúc vì nhiệt). Nếu được, chạy một job video
    ngắn nhất có sẵn tới bước preview, ghi thời gian và kết quả. Không chạy thì ghi rõ "chưa chạy job thật".

### Bước 5. Report
`report.md` gồm: kết quả từng lệnh kiểm ở bước 4 (số thật), diff tên dòng của `studio.env` (chỉ tên biến, không giá trị),
danh sách dòng trong Dockerfile/compose/deploy còn dùng tên cũ để chuyển cho teammate, và cách hoàn tác.

## Hoàn tác (ghi vào report, chỉ dùng khi bước 4 thất bại)
Dừng stack; `mv` ngược 3 thư mục; chạy lại vòng sửa shebang theo chiều ngược; `cp -p` bản sao lưu về
`scripts/gpu/studio.env`; bật lại stack. Ba commit code không cần hoàn tác vì tên cũ vẫn được nhận.

## Acceptance criteria
1. Ba thư mục mang tên mới; `scene_runtime`, `objectgs_runtime` và mọi URI artifact không đổi.
2. Sáu lớp settings đọc `R2S_*`; tên cũ vẫn chạy kèm đúng một cảnh báo mỗi tên; tên mới thắng khi có cả hai.
3. Test chặn tái phát xanh: ngoài `src/runtime_env.py`, không còn tên `RECxx_` của 6 nhóm trong phạm vi.
4. `qualification_evidence_checksum` của registry dev và nội dung runtime manifest không đổi.
5. Stack chạy lại: `/health` 200, 3 job và 5 scene mẫu đọc được như trước, log không có cảnh báo tên cũ.
6. `input_runtime_qualification_v1.json`, Dockerfile, compose, deploy không bị sửa.

## Tests required
```
.venv/bin/python -m pytest tests/test_runtime_env_names.py tests/test_config.py -q
.venv/bin/python -m pytest tests/test_reconstruction/test_qualify_input_runtimes.py \
  tests/test_reconstruction/test_input_runtime_registry_script.py tests/test_gpu/test_gpu_plan.py \
  tests/test_orchestration/test_worker_cleanup.py tests/test_api/test_studio_routes.py \
  tests/test_packaging/test_input_runtime_registry_wiring.py tests/test_packaging/test_compose_config.py \
  tests/test_reconstruction/test_rec04_brush.py tests/test_reconstruction/test_lidar_odometry.py \
  tests/test_reconstruction/test_rec05_scale.py tests/test_reconstruction/test_rec06_canonical_visual.py \
  tests/test_reconstruction/test_rec07_prefusion.py -q
.venv/bin/ruff check <file đã sửa> && .venv/bin/ruff format --check <file đã sửa>
```
Ngoại lệ quy tắc 4 của `.ai/README.md`: task này chạm cấu hình mọi runtime nên **chạy full backend một lần** sau bước 3:
`.venv/bin/python -m pytest tests -q -p no:cacheprovider` (khoảng 9 phút), ghi số thật.

## Commit
Ba commit code theo bước 1–3, một commit report + status. `git add` đúng path. Không Co-Authored-By.
`graphify update .` sau bước 3. Không push, không tạo branch. Không xoá gì ngoài thư mục tạm của bạn
(bản sao lưu `studio.env` giữ lại).
