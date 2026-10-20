# T-069 report: hồi quy toàn bộ, đo trước/sau, bàn giao

## Test (2026-10-20)
| Bộ | Kết quả |
|---|---|
| `pytest tests` (Python) | 4254 qua, 16 đỏ, 40 bỏ qua (12 phút 55 giây) — trước hai bản sửa dưới |
| `vitest run` (frontend) | 124 file, 1110 test qua |
| `npm run typecheck` | sạch |
| `npm run lint` | 0 lỗi, 7 cảnh báo (file test cũ) |
| `ruff check .` | 10 lỗi, đều trong script báo cáo cũ `.ai/reports/*` (không thuộc Sprint 8) |
| `ruff format --check .` | file Sprint 8 duy nhất chưa định dạng đã sửa (`test_artifact_download_links.py`) |

`pytest tests` (lệnh trần `pytest` thu cả `data/objectgs_runtime/...` cần torch nên dừng ở bước thu test).

### 16 test đỏ
| Test | Nguyên nhân | Chủ |
|---|---|---|
| `test_runtime_env_names::test_no_legacy_runtime_name…` | Sprint 8: `compact_gaussians.py` đọc tên cũ `REC05_VOXEL_CLI` | **Đã sửa** (`5c7cd2a3`, đọc qua `runtime_env`) |
| `test_role_matrix::test_every_route_is_classified_exactly_once` | route `demo-sessions`/`samples` chưa khai báo; route mới của Sprint 8 đã khai báo | Có từ trước Sprint 8 |
| `test_sample_routes` (7) | Có từ trước Sprint 8 (đã kiểm ở bf260701) | Phiên khác |
| `test_runtime_migrations` v11/v12 (2) | Test cũ mong schema 23 | Có từ trước Sprint 8 |
| `test_deploy_env::test_committed_examples…` | `deploy/studio/*.env.example` lệch nguồn (dòng demo download, Isaac) | Đóng gói (phiên khác) |
| `test_gpu/test_install_scripts` (2) | Cần gói apt hệ thống trên máy | GPU (phiên khác), môi trường |
| `test_gpu/test_setup_objectgs_runtime` (2) | Script cài ObjectGS | GPU (phiên khác) |

## Sửa trong T-069
- `/scenes` gọi `preview_ready` và `_awaiting_object_choice` hai lần mỗi scene (T-059 gây ra): sửa + test đếm lần gọi;
  55 ms → 27,5 ms.
- Tên biến môi trường cũ trong `compact_gaussians.py` (bảng trên).

## Migration và job thật (bản sao `data/studio_local/runtime.db`, không ghi DB thật)
Schema v25 → v26 thành công. `/jobs/{id}/pipeline` cho 4 job: 21–29 ms, 200, ETag trả 304; bước và việc tiếp theo hợp lý
(`confirm_objects`, `create_package`, `review_objects`, `retry_geometry`). `/scenes` 200.
Phiên GPU đã chạy `test_step_marks.py` (13) trên PostgreSQL 16 thật: qua, migration v26 thành công.

## Tài liệu
- `docs/plans/active/2026-10-20-pipeline-stability/HANDOFF.md`: thay đổi, số đo, việc kiểm bằng mắt, lưu ý deploy, backlog.
- `docs/PIPELINE_HIEN_TAI_VA_LUONG_USER.md` mục 7.1: đọc tiến trình, `next_action`, mốc bước.
- `.ai/roadmap.md`: kết quả Sprint 8.
