# Review T-040

Verdict (vòng 1): CHANGES REQUESTED (1 sửa) · Vòng 2: ACCEPTED

Audit: đọc diff 9 commit (`418e1d2a` → `30889790`, 37 file), trọn `jobs/lease.py`, `jobs/worker_runtimes.py`, phần sửa
`jobs/profile.py`, `jobs/dispatch.py`, `jobs/worker_cli.py` (dispatch, `_leased_call`, `recover_expired_leases`,
`_rebind_orphaned_job`), `projects/registry.py` (`job_profile`, `rebind_job_runtime`), `projects/persistence.py`
(`save_job` + `fence`, `_require_runtime_rebind`), `runner._run_tool`, provenance ở `objectify_queue`/`runner`, các nơi lọc
usage (`observed.py`, `benchmark.py`). Chạy 8 file test mới: 54 PASS.

## Đã kiểm, đúng
- **Fencing phủ mọi revision**: `fence()` gọi trong transaction của `ProjectPersistence.save_job` (`persistence.py:229`), mà
  mọi `transition_job`/publish stage đều đi qua `save_job`. Token so trong cùng transaction ghi; lease hết hạn hoặc đổi chủ
  thì không ghi được. Đột biến của engineer (bỏ fencing → test đỏ) khớp.
- **ContextVar**: lease giữ trong `ContextVar`, thread mới không thừa hưởng. Đã kiểm vòng `_run_tool` (`runner.py:205–245`)
  chạy **cùng thread** với `_leased_call`, nên `lease_lost()` thấy đúng lease; luồng gia hạn chỉ dùng object `held` truyền
  trực tiếp. Không có chỗ ghi revision từ thread khác trong attempt.
- **So thời gian dạng chuỗi trong SQL**: `_stamp` luôn ra `isoformat(timespec="microseconds")` với `+00:00` (độ dài cố định),
  nên so `<=` theo chuỗi đúng thứ tự trên SQLite và PostgreSQL.
- **Job chờ người dùng** (RUNNING chờ xác nhận tỉ lệ) không có dòng lease vì `leased()` trả lease khi runner xong lượt
  preview; `recover_expired_leases` chỉ duyệt bảng lease, nên không đánh FAILED job đang chờ người.
- **Rebind**: chỉ QUEUED, `stage_artifacts == []`, runtime cũ không có worker sống, CAS theo revision; persistence chỉ cho
  đổi đúng trường runtime khi có event `runtime_rebound` khớp (`_require_runtime_rebind`). Job cũ (checksum đầy đủ) được
  nhận qua `accepts_runtime`, không bị rebind vô cớ.
- **Provenance tách vật/attempt**: số đo ghi runtime phần mềm của máy chạy (`machine_runtime_checksum`), budget và admission
  so cùng giá trị với job mới.

## Required changes

### 1. Khoá bảng `r2s_worker_runtimes` phải gồm config và seed (câu hỏi 4 của report)
`worker_runtimes.publish` upsert `ON CONFLICT(software_runtime_checksum)` rồi ghi đè `config_checksum`, `seed`. `select()`
lọc `config_checksum` và `seed` **sau khi đọc**. Hai worker cùng image nhưng khác file config hoặc seed (lúc đổi config,
lúc chạy song song bản cũ/mới) sẽ ghi đè nhau theo nhịp heartbeat; API có config A lúc thấy dòng của B → `select` trả
`None` → **tạo scene lúc được lúc bị từ chối** ("Chưa có runtime cho job").

Sửa:
- Migration 22: `PRIMARY KEY (software_runtime_checksum, config_checksum, seed_key)` với `seed_key INTEGER NOT NULL`
  (`-1` khi `seed` là `NULL`, vì PostgreSQL không cho cột NULL trong PRIMARY KEY; giữ cột `seed` để đọc). Upsert
  `ON CONFLICT(software_runtime_checksum, config_checksum, seed_key)`.
- **Sửa migration 22 tại chỗ được**, vì chưa DB nào lên 22: `data/studio_local/runtime.db` đang ở 21, stack đang chạy (unit
  demo-route, cùng DB) bật trước khi có T-040, production chưa có. **Kiểm lại ngay trước khi commit**: nếu bất kỳ DB local
  nào đã lên 22 (stack được khởi động lại trong lúc chờ), thêm migration 23 đổi khoá thay vì sửa 22.
- `has_live_runtime`, `live_runtime_checksums`, `find`: giữ nghĩa "có worker sống chạy được checksum này"; `find` trả runtime
  sống mới nhất trong các dòng cùng checksum phần mềm.
- Test (đỏ trên code cũ): worker A (config X) và B (config Y) cùng phần mềm cùng công bố → hai dòng; API config X luôn chọn
  được runtime sau mọi thứ tự công bố của A/B. Thêm tham số PostgreSQL theo fixture `runtime_database_url`.

## Trả lời 5 câu hỏi của report
1. **Job RUNNING cũ lúc deploy:** không cần làm. Ba job local đều `SUCCEEDED` (đã đọc manifest), production chưa có dữ liệu.
   Ghi một dòng vào `deploy/studio/OVERVIEW.md` mục nâng cấp: "Nâng cấp từ bản trước T-040 khi còn job RUNNING: đưa job đó
   về FAILED retryable bằng tay trước khi bật worker mới."
2. **Nút "Chạy lại từ đầu":** để backlog (roadmap), làm khi có người dùng thật gặp đổi phiên bản image.
3. **Cổng T-036:** chấp nhận làm Phần B trước. Lỗi duy nhất của full suite là `Makefile.studio` chưa commit của T-036, không
   thuộc T-040.
4. **Khoá bảng:** sửa, xem Required change 1.
5. **`PRODUCT_INPUT_RUNTIME_REGISTRY` còn chép tay:** cùng loại vấn đề với manifest. Tách task sau (worker công bố registry
   vào DB như runtime). Trước khi có task đó, T-041 làm bước chép một lần cho mỗi phiên bản image.

## Suggestions (không bắt buộc)
- **Vòng bật GPU sau khi đổi image (ảnh hưởng T-042):** runtime cũ vẫn "sống" thêm tới 15 phút (`RUNTIME_TTL`) sau worker
  cuối. Trong khoảng đó job chưa có stage của runtime cũ không được rebind, nhưng autoscaler vẫn đếm (runtime cũ còn sống) →
  bật worker image mới, worker không chạy được job, thoát, lại bật. Ghi vào T-042: khi worker image mới khởi động, cho rebind
  job chưa có stage nếu runtime của job có `last_seen_at` **trước** `first_seen_at` của runtime worker này (image cũ hơn),
  không chờ hết TTL.
- `benchmark._tool_timings` lọc usage theo `job.runtime_manifest_checksum`. Job tạo trước T-040 (checksum đầy đủ) mà chạy lại
  sau deploy sẽ ghi usage theo checksum phần mềm → thiếu thời gian công cụ trong snapshot của lượt đó. Chỉ ảnh hưởng job cũ.

## Round 2 — ACCEPTED

Audit `e4e38683`, `491c0954`. Migration 22: `PRIMARY KEY (software_runtime_checksum, config_checksum, seed_key)`, `seed_key`
`-1` cho seed NULL, `publish` từ chối seed âm; upsert đúng khoá, không còn ghi đè `config_checksum`/`seed`; `select` lọc trong
SQL; `find` chọn dòng sống mới nhất. `has_live_runtime`, `live_runtime_checksums` còn nguyên (engineer báo đã lỡ xoá rồi khôi
phục trước commit; đã kiểm có trong HEAD). Sửa 22 tại chỗ hợp lệ: `data/studio_local/runtime.db` vẫn ở schema 21; bảng lease là
migration 23. Chạy worker_runtimes, selection, migrations, rebind, autoscaler: 55 PASS. `OVERVIEW.md` có mục "Nâng cấp từ bản
trước T-040".

Lưu ý vận hành: stack đang chạy là code trước T-040; lần khởi động lại kế tiếp sẽ chạy migration 22 và 23 trên
`data/studio_local/runtime.db`. Nên khởi động lại trong lần làm lại bước 4 của T-036, không trước.
