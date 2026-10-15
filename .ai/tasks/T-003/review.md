# Review T-003

Verdict: CHANGES REQUESTED (chỉ một việc nhỏ, phần còn lại đạt)

Đã đọc `plan.md`, `report.md`, diff thật của `f62c9dc9`, `b0cebd69`, `767ff587`, `d4013681`, `c95dacd4`.
Chạy lại test trong Tests required, cộng `test_objectgs_required_stage.py` (agent có sửa nhưng chưa chạy) và
`test_objectgs_objectify_flow.py`: **357 passed**. `check_contract_mirror.py` PASS.

## Trả lời câu hỏi của Engineer

**Câu 1: đổi preset trước khi có nhánh shell. Chọn A.** Engineer đúng: plan mâu thuẫn. Đổi preset bây giờ sẽ cho
job mới mang nhãn `shell` nhưng ra hình học legacy và bị coi là `ready`. Giữ preset hiện tại (`objectgs`).
Bước 5 (presets) **chuyển sang T-013**, lúc đã có Draft (T-005), build (T-007/T-009) và nút "Tạo mesh" trong Studio.
Plan T-013, T-020 và roadmap đã cập nhật theo.

**Câu 2: gắn code lỗi. Chọn A.** Tạo lớp con:
```python
class ObjectGeometryNotReadyError(SceneEditRejectedError):
    code = "OBJECT_GEOMETRY_NOT_READY"
```
Không đổi envelope HTTP (`ApiErrorResponse` chỉ có `detail`). Frontend không cần đọc code: nó biết trạng thái Draft từ
`SceneIR.provenance.object_geometry` và tự khoá nút (T-013). Plan T-009, T-010, T-012 đã bỏ phần "code trong body",
thay bằng lớp lỗi riêng + thông điệp `detail` tiếng Việt.

## Acceptance criteria
1. `ObjectShellManifest` từ chối sai type / object ngoài membership / `quality.passed` không True: **pass**.
2. `SceneObject` nhận `ObjectShellMesh`, vẫn từ chối collider: **pass**.
3. `object_geometry_state`: **pass**. `require_geometry_ready`: **chưa làm** (chờ câu 2, nay đã trả lời).
4. `job_requires_strict_geometry` đúng 4 trường hợp: **pass**.
5. Presets: **hoãn sang T-013** (quyết định câu 1), không tính là lỗi của task.
6. `SceneObjectifyConfig()` mặc định legacy: **pass**.
7. Lift runner không nhận `geometry_review`: **pass**.

## Required changes
1. `src/services/scene/geometry_state.py`: thêm `ObjectGeometryNotReadyError` (đặt ở
   `src/services/orchestration/scene/errors.py` cạnh `SceneEditRejectedError`) và
   `require_geometry_ready(scene, action) -> None`, raise lỗi đó với thông điệp
   `f"Cần tạo mesh trước khi {action}."` khi state là `awaiting_review`; scene `ready`/thiếu khóa không raise.
   Test: raise đúng lớp + đúng `code`, là instance của `SceneEditRejectedError`, thông điệp chứa `action`; không raise khi ready.
   Lệnh: `.venv/bin/python -m pytest tests/test_scene/test_geometry_state.py -q` + ruff. Một commit.
2. Cập nhật `report.md` (thêm mục "Round 2") và đặt `status.md` → `implemented`.

## Suggestions (không chặn)
- Đổi tên biến `objectgs_required` trong `extract_scene` và thông điệp "ObjectGS job requires…" sẽ làm ở T-005, khi nhánh shell
  thật sự chạy. Ghi chú này đã có trong Known issues; không cần làm ở đây.
- Alias `job_requires_objectgs` không còn nơi nào dùng; có thể xoá ở T-005.
