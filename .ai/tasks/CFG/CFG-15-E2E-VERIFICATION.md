TASK: CFG-15-E2E-VERIFICATION

STATUS: DONE — all required gates passed; all 3014 backend cases covered across the configured full run and the explicit KISS-ICP supplement.

## Executable checkpoint (2026-10-13)

- Added `tests/integration/test_config_pipeline_e2e.py`: real HTTP suggestions and scene creation, checksum-bound job dispatch, typed geometry overlays and actual native command builders.
- Four cases passed: indoor/outdoor × smooth/faces. Both COLMAP CLI namespaces preserve loop detection and staged vocabulary path; indoor emits external-fill 1.6; outdoor emits floor-fill 1.6 and omits external fill.
- `ruff check src/ tests/`: clean. `ruff format --check src/ tests/`: 609 files already formatted.
- Default full backend run: 2984 passed, 30 opt-in cases skipped, no failures. Final frontend: 539 passed, typecheck clean, production build successful.
- Additional configured checks: real codec 83 passed (one GPU case initially skipped), real GPU 2 passed, isolated MinIO/PostgreSQL 25 passed. Counts overlap the default suite and are not summed as independent tests.
- Offline LiDAR CLI tests: 2 passed using the isolated Open3D 0.19.0 runtime installed from the hashed offline lock. Configured complete backend run: 3013 passed, one KISS-ICP case skipped; that exact case then passed with the existing pinned KISS-ICP 1.3.0 runtime explicitly configured. All 3014 collected backend cases were exercised successfully across these two runs; this is not a single zero-skip run.
- Necessary additional test path: tests/integration/test_direct_upload_minio.py. Its old success fixtures declared random/7-byte payloads as MP4 and were correctly rejected by content validation. The fixtures now use a genuine FFmpeg MP4; a valid free box exercises multipart transfer. Production validation was not weakened.
- Both pinned vocabulary assets pass check-only checksum validation.
- Browser QA services were isolated and had no reconstruction worker. The owned development frontend was stopped before the successful production build to avoid sharing its Next build directory.
- Final report: docs/plans/active/2026-10-13-pipeline-config-and-vocab-tree/VERIFICATION_REPORT.md. Local acceptance passes; full user-scene reconstruction, cloud deployment and Isaac acceptance remain unverified. Graphify AST update completed. Required logs are attached under tasks/reports/CFG15-*.log.


## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Chuỗi cải tiến này trải rộng trên toàn bộ các lớp của hệ thống: từ core runners (C++ COLMAP, Rust Brush, Node.js splat-transform, Python SAM2/CoACD), schema Pydantic backend, REST API endpoints, file cấu hình Presets JSON, đến TypeScript contracts và giao diện Web Studio UI. Bất kỳ một sơ suất nhỏ nào về kiểu dữ liệu hoặc tên trường cũng có thể gây lỗi lệch contract (schema mismatch) hoặc crash khi submit job thật. Do đó, cần một bài kiểm thử tích hợp toàn trình (E2E) mô phỏng chính xác hành trình: Người dùng chọn các ô Wizard trên UI $\rightarrow$ API gợi ý Preset $\rightarrow$ Job được khởi tạo $\rightarrow$ Backend biên dịch ra các cờ CLI thực thi chính xác của từng công cụ.
- **Yêu cầu cốt lõi (What):**
  1. Viết bài test tích hợp toàn trình trong `tests/integration/test_config_pipeline_e2e.py`.
  2. Chạy toàn bộ static checks backend (`ruff check`, `ruff format --check`, `.venv/bin/pytest`).
  3. Chạy toàn bộ frontend checks (`pnpm typecheck`, `npx vitest run`, `pnpm build`).
  4. Lập bản báo cáo nghiệm thu Pre-flight Gates Report chi tiết gắn vào kết quả thực hiện.

GOAL:
Thực hiện kiểm thử tích hợp toàn trình (End-to-End Integration & Quality Gates Verification), bảo đảm toàn bộ pipeline từ Backend, Presets, API đến Frontend Web Studio hoạt động đồng bộ, không có lỗi gãy vỡ hồi quy (regression) và thỏa mãn mọi tiêu chuẩn chất lượng của repository.

INPUT CONTRACT:
- Kết quả hoàn thành của toàn bộ chuỗi task từ CFG-01 đến CFG-14.
- Mã nguồn trong `src/`, `configs/`, `frontend/`.

OUTPUT CONTRACT:
- Toàn bộ các test suite mới và cũ pass 100%:
  - Backend pytest (unit, contract, integration).
  - Frontend vitest và TypeScript typecheck.
- Không có lỗi linter/formatter (`ruff check`, `ruff format --check`).
- Frontend production build thành công (`pnpm build`).
- Bản báo cáo nghiệm thu Pre-flight Gates Report chi tiết gắn vào kết quả thực hiện.

OWNED FILES:
- `tests/integration/test_config_pipeline_e2e.py`
- `docs/plans/active/2026-10-13-pipeline-config-and-vocab-tree/VERIFICATION_REPORT.md`

FILES YOU MAY MODIFY:
- `tests/`
- `docs/plans/active/2026-10-13-pipeline-config-and-vocab-tree/`

FILES YOU MUST NOT MODIFY:
- `src/models/contracts/manifests.py`

PRIMARY TOOL:
- Pytest, Ruff, Vitest, PNPM, Next.js build.

IMPLEMENT:
1. Viết bài test tích hợp toàn trình trong `tests/integration/test_config_pipeline_e2e.py`:
   - Mô phỏng quá trình người dùng gửi `ScenarioPreferences` (ví dụ: indoor + 360 loop + full room).
   - Kiểm tra API gợi ý ra đúng preset `video_indoor_orbital_360`.
   - Kiểm tra lệnh sinh ra cho COLMAP: chứa `--SequentialMatching.loop_detection 1` và `--SequentialMatching.vocab_tree_path`.
   - Kiểm tra lệnh sinh ra cho splat-transform: chứa `--collision-mesh smooth` và `--voxel-external-fill 1.6`.
   - Kiểm tra trường hợp ngoài trời (outdoor): kiểm tra lệnh chứa `--voxel-floor-fill` và không có `--voxel-external-fill`.
   - Kiểm tra trường hợp chọn `--collision-mesh faces`.
2. Chạy toàn bộ static checks backend:
   - `ruff check src/ tests/`
   - `ruff format --check src/ tests/`
3. Chạy frontend checks:
   - `cd frontend && pnpm typecheck`
   - `cd frontend && npx vitest run`
   - `cd frontend && pnpm build`
4. Lập bản báo cáo nghiệm thu `VERIFICATION_REPORT.md`.

TEST:
- `.venv/bin/pytest tests/integration/test_config_pipeline_e2e.py -v`
- `ruff check src/ tests/`
- `ruff format --check src/ tests/`
- `cd frontend && pnpm typecheck`
- `cd frontend && npx vitest run`
- `cd frontend && pnpm build`

DONE WHEN:
- Tất cả các lệnh kiểm thử trên đều trả về exit code 0.
- Không có lỗi typecheck hay linting.

EVIDENCE:
- Test outputs và file `docs/plans/active/2026-10-13-pipeline-config-and-vocab-tree/VERIFICATION_REPORT.md`
