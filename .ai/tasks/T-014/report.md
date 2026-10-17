# T-014: Box model TypeScript thuần — báo cáo

**Trạng thái:** implemented. Không có câu hỏi thiết kế chặn việc giao T-014; các điểm cần Architect xác nhận nằm ở mục cuối. Nếu Architect muốn duyệt trước, đổi thành `changes-requested` theo `.ai/README.md` mục 10.

**Branch:** `mvp-pipeline-v2`. Không tạo branch, không push, không merge, không PR.

## Đã làm

Module thuần `frontend/src/features/studio/region/box-model.ts` (không import PlayCanvas, không gọi API) và test `frontend/tests/region-box-model.test.ts` với 38 test. Làm theo 4 step của plan; mỗi step theo TDD: thấy RED đúng lý do, viết code tối thiểu, GREEN, eslint và typecheck, rồi commit.

API theo đúng interface của plan: `MIN_HALF_M`, `MAX_HALF_M`, `MAX_BOXES`, `fitBoxToPoints`, `dragFace`, `translateBox`, `rotateYaw`, `clampToFloor`, `faceCenter`, `faceNormal`, `contains`, `toCommandBoxes`, `validateBoxes`, `boxesKey`, và các kiểu `Vec3`, `BoxOp`, `EditableBox`, `FaceId`, `RegionBox`.

## Commit

| Commit | Nội dung |
| --- | --- |
| `e27364e8` | Step 1: `contains`, `toCommandBoxes`, `validateBoxes`, các kiểu |
| `8accbb36` | Step 2: `dragFace`, `translateBox`, `rotateYaw`, `faceCenter`, `faceNormal` |
| `cff82a88` | Step 3: `fitBoxToPoints`, `clampToFloor` |
| `f22bc96c` | Step 4: `boxesKey` |
| `59488592` | Test cho nhánh hoán trục của `fitBoxToPoints` (phát hiện khi tự rà soát) |
| `22474a8d` | `fitBoxToPoints` không cắt kích thước âm thầm (phát hiện khi tự rà soát) |
| (commit báo cáo) | `report.md` và `status.md` |

File: tạo `box-model.ts`, `region-box-model.test.ts`, `.ai/tasks/T-014/report.md`. Sửa `.ai/status.md` (T-014: planned → in-progress → implemented). `graphify-out/` được `graphify update .` làm mới; thư mục này nằm trong `.gitignore` nên không commit.

## Tiêu chí chấp nhận của plan

| # | Tiêu chí | Test tương ứng |
| --- | --- | --- |
| 1 | `dragFace(+x, 0.1)`, yaw 0: half.x +0,05, center.x +0,05, mặt −x đứng yên | "grows +x by the drag amount and keeps the -x face fixed at yaw 0" |
| 2 | Cùng thao tác, yaw π/2: dịch theo +y world | "moves along world +y at yaw π/2 and keeps the opposite face fixed" |
| 3 | Kéo âm quá mức: kẹp ở MIN, không đảo chiều | "clamps a shrinking drag at MIN_HALF_M without flipping the box" |
| 4 | Fit box xoay 30°: yaw ≈ 30° sai ≤ 2°, half ≈ thật + lề | "recovers yaw within 2 degrees and half-extents plus margin for a rotated box" |
| 5 | `clampToFloor` giữ đỉnh cố định, đáy = floorZ | "lifts the bottom to the floor and keeps the top fixed" |
| 6 | `contains` khớp quy tắc server, điểm trên mặt → true | "accepts points on faces and corners", "rejects points outside a face with a 1e-6 absolute tolerance" |
| 7 | `validateBoxes`: thiếu box cộng, > 16 box, half ngoài khoảng | "requires at least one add box", "caps the box count at 16", "checks half-extents against the closed range" |
| 8 | `boxesKey` đổi khi giá trị đổi ≥ 1e-6, không đổi khi chỉ đổi thứ tự thuộc tính | "changes when any value or op changes by at least 1e-6", "does not depend on the order of object properties" |

Tiêu chí 4 được kiểm mạnh hơn bản gốc: test kiểm dấu của yaw (30°, không chỉ mod π/2).

## Lệnh kiểm tra và kết quả

Chạy trên `22474a8d` (code cuối). Chỉ các lệnh trong mục "Tests required" của plan; không chạy full suite.

- `cd frontend && ./node_modules/.bin/vitest run tests/region-box-model.test.ts` → **38/38 pass**, exit 0.
- `npm run typecheck` (`next typegen && tsc --noEmit`) → **exit 0**, không có lỗi ở file mới.
- `./node_modules/.bin/eslint src/features/studio/region/box-model.ts tests/region-box-model.test.ts` → **exit 0**.
- `graphify update .` → exit 0.

Bằng chứng RED (mỗi test thấy fail trước khi có code):
- Step 1: `Failed to resolve import "@/features/studio/region/box-model"`.
- Step 2: 12 fail, `TypeError: (0, dragFace) is not a function`.
- Step 3: lần đầu 7 fail, và 1 test pass giả vì `toThrow()` khớp cả `TypeError`. Đã siết thành `toThrow("cần mảng xyz")`, lúc đó 8 fail.
- Step 4: 4 fail, `TypeError: (0, boxesKey) is not a function`.
- Nhánh hoán trục: test mới pass ngay vì nhánh đã đúng. Để kiểm test có nhạy hay không, tạm đảo lựa chọn yaw → 3 test fail; khôi phục từ HEAD → 38/38.
- Bỏ kẹp trong fit: RED `expected 20 to be close to 22.5`; sau sửa → GREEN.

## Quyết định lệch hoặc bổ sung so với plan

1. **`RegionBox` khai báo cục bộ** trong `box-model.ts`, đúng tên trường của architecture §7.3. Plan giả định mirror đã có trong `api.ts` từ T-004, nhưng `api.ts` không có `RegionBox` và T-004 còn `planned`. Roadmap ghi T-014 không có phụ thuộc. Chi phí nếu sai: đổi một import, chỉ là kiểu, không ảnh hưởng runtime.
2. **Lề cộng vào cả ba nửa kích thước, đáy đặt đúng min z.** Vì vậy đỉnh cao hơn max z `2·marginM`. Plan viết "đáy z = min z, thêm lề" nhưng không nói lề có áp cho z không. Chi phí nếu sai: đỉnh lệch 2 cm.
3. **Trục x của box fit là trục có extent dài hơn**; yaw đưa về (−π/2, π/2]. Tiêu chí 4 cho phép sai mod π/2 nên đây là lựa chọn tự do. Chi phí: chỉ đổi nhãn x/y.
4. **Đầu vào là `Float32Array` xyz phẳng.** Plan không quy định bố cục. Mảng rỗng hoặc độ dài không chia hết cho 3 thì ném lỗi.
5. **`fitBoxToPoints` không kẹp nửa kích thước** (đổi trong `22474a8d`). Fit ngoài [0,005; 20] được `validateBoxes` báo lỗi thay vì cắt âm thầm thành box không bao được điểm. Caller phải gọi `validateBoxes` trên box fit; T-016 cần biết điều này. Chi phí nếu sai: vật lớn hơn 40 m hiện thông báo lỗi thay vì một box bị cắt.
6. **`clampToFloor`:** nếu đỉnh cách sàn dưới `2·MIN_HALF_M` thì giữ MIN và nâng đỉnh. Plan im lặng ở nhánh này. Chi phí: đỉnh nâng tối đa 1 cm, nhiều hơn chỉ khi cả box nằm dưới sàn.
7. **`boxesKey` lượng tử hoá 1e-7** và không đưa `id` vào khoá, vì preview chỉ phụ thuộc hình học. Chi phí: thay đổi dưới 1e-7 không đổi khoá.
8. **`dragFace` dịch tâm theo phần đổi nửa kích thước sau khi kẹp**, không theo delta thô. Chi phí: chỉ khác khi kéo vượt giới hạn.

**Quy ước yaw** (cố định bởi tiêu chí 2): quay phải quanh +Z, trục x cục bộ = (cos yaw, sin yaw, 0). Phía server (T-004) phải dùng cùng quy ước; xem câu hỏi 2.

## Lệch quy trình

- **Không tạo worktree.** `.ai/README.md` mục 6 cấm tạo branch mới, và cây làm việc đang được agent khác dùng chung. Thay vào đó stage đúng đường dẫn và kiểm staged set trước mỗi commit.
- **Không dùng subagent.** Quy tắc hệ thống chỉ cho spawn agent khi người dùng yêu cầu. Vì vậy final review là **self-review** theo checklist của `code-reviewer.md`, không phải reviewer độc lập. Self-review đã tìm ra hai vấn đề và đã sửa (`59488592`, `22474a8d`). Chưa có đánh giá độc lập; người duyệt quyết định có đủ không.
- **Ledger ở scratchpad, không ở `.superpowers/sdd/`.** Thư mục đó đặt theo basename của plan, là `plan.md` cho mọi task T-0xx, nên sẽ trùng nhau.
- **Không dùng `task-start` / `task-done`.** Plan dạng Steps, không có tiêu đề "Task N".
- **Không chạy full test suite**, theo yêu cầu.

## Việc còn dở

- **Minor, hoãn:** thông báo `validateBoxes` ghi cứng "0,005 m đến 20 m"; cần đồng bộ nếu đổi hằng.
- **Chưa có UI.** T-015 và T-016 dùng module này. T-014 không có thao tác thị giác nên không cần kiểm tra bằng mắt.
- **Thay đổi của người khác không bị đụng tới.** `.ai/status.md` đã được agent khác commit cùng công việc của họ (T-001 accepted, T-003 changes-requested). Các mục `tasks/CFG-*` ở root, `BRAINSTORM.md`, `MASTER_PITCH.md`, `tasks/CFG/` là untracked của người khác; không stage.

## Câu hỏi cho Architect (không chặn T-014)

1. **Biên của server.** architecture §7.3 ghi `half_extents_m > 0.005` (mở), còn T-014 dùng khoảng đóng `[0.005, 20]`, theo cách plan kẹp tại 0.005. Nếu server giữ biên mở thì `MIN_HALF_M` phải nhích lên một chút hoặc biên server phải đổi. Cần chốt trước T-004 và T-010.
2. **Dấu yaw phía server.** Cần T-004 xác nhận server dùng cùng quy ước quay phải quanh +Z.
3. **Chuyển `RegionBox` về `api.ts`** khi T-004 làm, để không có hai định nghĩa.
4. **Lề z.** Đỉnh cao hơn max z `2·marginM` (ruling 2). Xác nhận có chấp nhận không.
5. **`CONTAINS_TOLERANCE_M`** được ghi là "khớp quy tắc server". Hiện mới theo plan; chưa đối chiếu với mã server vì T-004 chưa có.
