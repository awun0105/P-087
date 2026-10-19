# Implementation và bundle triển khai demo — 2026-10-19

## Outcome

Đã implement nhánh demo phân tán và tạo bundle thật tại `dist/studio-demo-20261019/`. Không thực hiện spike độc lập, không chạy workload GPU thử nghiệm, không deploy cloud. Repo vẫn private, chưa commit/push các thay đổi này. Landing không bị sửa/deploy.

### Phần đã có trong code

- PostgreSQL migration v24: catalog phiên, publication revocation và summary bền vững. Mỗi phiên giữ logical job IDs nhưng có schema riêng, không dùng SQLite qua hai host. URL fragment nội bộ chỉ chọn schema server-generated; không gửi fragment đó cho PostgreSQL driver.
- Mỗi transaction vào đúng schema và từ chối namespace đã bị xóa. Không fallback sang main/public schema. Migration lock của main DB giữ nguyên key cũ.
- Artifact resolver đọc session output trước, sau đó baseline immutable trên R2. Publish luôn ghi session prefix. Không upload lại baseline hàng GB mỗi lần mở phiên.
- API và GPU tra phiên qua control DB. Worker dùng advisory ownership lock và main resource reservation, native worker child process và production auth guard hiện có. Worker profile của API lấy được qua runtime discovery.
- Close/idle/hard-expiry thu hồi capability; janitor API mỗi 30 giây và worker poll dọn schema/output sau khi ownership được nhả. Mỗi host dọn cache của chính nó. Summary timing observations/event counts giữ riêng, không giữ scene edits trong summary; descriptor được scrub sau purge.
- Unpublish có durable marker trong DB, đóng session hiện có và serialize với session publication giữa các replica.
- API bootstrap từ thư viện mẫu đã ghim checksum, kiểm archive/member/workspace trước phục vụ. PRODUCT_DEMO_REQUIRED từ chối khởi động khi thiếu workspace. `/ready` kiểm worker runtime còn heartbeat và thư viện bên cạnh `/health`.
- Public sample payload và artifact đã kiểm allowlist có thể tải trực tiếp từ R2. Demo responses có no-store/no-referrer; Uvicorn entrypoint không ghi access log mặc định.
- CLI đóng gói source hiện tại và sample được chọn; CLI verify/publish/bootstrap library. Source bundle bao gồm source mới chưa commit trong allowlist, không dựa riêng vào git archive của HEAD cũ.
- Production templates đồng bộ, mặc định một GPU worker/tám session; workflow build/push image thủ công; frontend CI build cả editor SuperSplat.

## Bundle

| File | Nội dung |
| --- | --- |
| `studio-source.zip` | 1,185 source files, 6,966,949 bytes; đã đối chiếu với workspace hiện tại. |
| `demo-library.zip` | 3 mẫu, 2,497 data files, 3,373,872,210 bytes. |
| `SOURCE_MANIFEST.json` | File inventory và checksum source. |
| `RELEASE.json` | Base commit, dirty state, source/data checksums, schema v24, image digest chưa có. |
| `SHA256SUMS` | Checksum file bàn giao. |
| `DEMO_RUNBOOK.md` và env examples | Publish R2, bootstrap, build, vận hành, rollback; không có secret. |

- Base commit: `45cd6f43d9a5276b3287975b403edc2ad213d2df`; source hiện tại còn uncommitted và được mang trong ZIP.
- Source checksum: `sha256:1af92aec08e00645197df46c6343c3dfa60da7ba3fa7e9a2b6ef475cccf9438e`.
- Data checksum: `sha256:956dbc22addff4ef3436cc2c796192ad4fb8580f0e381f82f70a4e9286bcddce`.
- Samples: DrJohnson rev-198, Room rev-062 và Playroom rev-003. Chỉ DrJohnson có geometry-ready trong baseline hiện tại; không đổi Draft thành completed và không tạo kết quả Isaac giả.
- Pack đã kiểm source rights attestation, frozen workspace artifact hashes, public file hashes và scan credential metadata theo helper hiện có trước khi nén. Đây không phải chứng nhận license/secrets cho toàn Git history.

## Verification

| Kiểm tra đã chạy | Kết quả |
| --- | --- |
| Ruff check trên 16 Python files sửa/thêm | PASS, All checks passed. |
| Ruff format --check trên cùng 16 files | PASS, 16 files already formatted. |
| `frontend/node_modules/.bin/tsc --noEmit --incremental false`, chạy từ frontend | PASS, exit 0. |
| `frontend/node_modules/.bin/eslint next.config.ts`, chạy từ frontend | PASS, exit 0. |
| `bash -n scripts/gpu/docker_entrypoint.sh` | PASS, exit 0. |
| AST parse Python thay đổi; YAML parse hai workflow | PASS. Đây là kiểm cú pháp, không phải chạy GitHub Actions. |
| `python -m scripts.studio.deploy_env render --examples` | Đã sinh ba templates; không dùng credentials, không deploy. |
| `python -m scripts.studio.build_demo_release --release demo-20261019 --out dist/studio-demo-20261019` | PASS; source ZIP được refresh sau các sửa đổi cuối, không nén lại data. |
| `python -m scripts.demo.release verify dist/studio-demo-20261019/demo-library.zip` | PASS, 3 mẫu/2,497 files; đọc và kiểm từng member. |
| SOURCE_MANIFEST đối chiếu source ZIP inventory + workspace | PASS, 1,185 files. |
| `sha256sum -c SHA256SUMS` trong release directory | PASS, cả 9 file OK. |
| `git diff --check` | PASS. |
| `graphify update .` | PASS, 28,157 nodes/88,241 edges. Không gọi LLM/API. |
| Test suite, browser/DevTools, PostgreSQL/R2 integration thật, Docker build, GPU/Isaac workload, cloud deploy | SKIP trong lượt này. Không dùng kết quả test cũ để chứng minh code mới. |

Python scope: `src/main.py`, `src/config.py`, `src/api/demo_sessions.py`, `src/api/studio/samples.py`, `src/services/orchestration/jobs/database.py`, `projects/registry.py`, `artifacts/remote.py`, `storage.py`, `samples/sessions.py`, `samples/session_worker.py`, `samples/distributed.py`, `samples/release.py`, `scripts/demo/release.py`, `scripts/studio/build_demo_release.py`, `scripts/studio/deploy_env.py`, `scripts/studio/container_entrypoint.py`.

## Phần deployment cần tài nguyên bên ngoài

1. DB/R2 credentials, domain và host CPU/GPU của deployment. Cần session pooler/direct PostgreSQL và quyền schema như runbook.
2. Publish library bằng CLI; lấy archive key/checksum trả về, render env rồi deploy API/worker/frontend. API tự bootstrap archive.
3. Build/pull API và GPU image trên host đủ disk, lưu digest thật. Máy local còn khoảng 5 GB trước bundle nên không build native GPU image ở đây. Source bundle không giả lập image digest.
4. Cấp qualified input runtime registry của worker cho API theo template hiện có. Cấp Isaac runtime/launcher/resources nếu muốn chạy validation thật; reconstruction image không tự chứa Isaac Sim.
5. GitHub CI/runner billing phải được khôi phục nếu dùng GitHub Actions. Workflow mới không tự chạy hoặc deploy khi push.

Telemetry tổng người + máy/time-to-usable/mesh leaf spans vẫn thiếu theo audit trước. Summary mới giữ observations và event counts với coverage partial; không biến số thiếu thành tổng đầy đủ. Các invariant phân tán mới chưa được kiểm chứng bằng integration/runtime trong lượt này.

## Changed files và gate report

- Runtime/API: config, main/lifespan/readiness, demo session routes, sample delivery, DB adapter/migration, artifact remote/storage/registry và session lifecycle/dispatch.
- Packaging: `scripts/demo/release.py`, `scripts/studio/build_demo_release.py`, `samples/release.py`.
- Deployment: `.dockerignore`, production/api/worker env examples, env checker, API/GPU entrypoints, Next headers, CI/release workflows, deployment README/OVERVIEW và DEMO_RUNBOOK.
- Báo cáo kế hoạch trước đó được giữ nguyên; báo cáo implementation này bổ sung trạng thái thực tế.
- codegraph: đã dò call paths/blast radius trước sửa. minimal-code: giữ native pipeline/scene/validation workers và contract identity, không viết lại thuật toán/GPU tools. checks: chỉ static và bundle integrity như trên; runtime acceptance chưa xác nhận. report: file này.
