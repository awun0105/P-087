# T-015: Box overlay + tay nắm + góc nhìn — báo cáo

**Trạng thái:** implemented. Không có câu hỏi thiết kế chặn việc giao T-015. Các điểm dưới đây thuộc tích hợp của T-016 và kiểm tra bằng mắt của chủ dự án.

**Branch:** `mvp-pipeline-v2`. Không tạo branch, không push, không merge.

## Đã làm

- `frontend/src/features/viewer/region-overlay.ts` (mới): lớp `RegionOverlay` đúng interface của plan (`setBoxes`, `setFloorZ`, `viewFrom`, `destroy`). Thêm các hàm thuần `edgeBars`, `rayLineParam`, `handleScale`, `viewPose` để test được không cần GPU.
- `frontend/src/features/viewer/scene-overlay.ts` (sửa): accessor tối thiểu (`isAlive`, `application`, `activeCamera`, `objectEntity`, `sharedGizmoLayer`, `requestFrame`, `bindViewerGotoPose`, `gotoPose`). Logic chặn pointer của gizmo được tách thành `isolatePointerGesture` và `isolateGizmoPointer`, dùng chung cho `attachGizmo` và overlay.
- `frontend/tests/region-overlay.test.ts` (mới): 36 test.

## Commit

| Commit | Nội dung |
| --- | --- |
| `e7ff696e` | Bước 1: accessor và helper chặn pointer dùng chung |
| `03cee461` | Bước 2: vẽ box theo vật, màu theo op, nét đứt, viền chọn |
| `c36ae0af` | Bước 3: tay nắm mặt, kéo theo tia, chọn box bằng click |
| `c8c4f54d` | Bước 4: gizmo xoay (chỉ trục Z) và dịch tâm |
| `b71fcc0c` | Bước 5: `setFloorZ` và kẹp sàn khi thả |
| `5c074e34` | Bước 6: `viewFrom` |
| `61883382` | Bước 7: `destroy` |
| `0ddff8d0` | Dọn code: đặt tên vật liệu, tách test sàn ra khỏi khối gizmo |
| (commit này) | `report.md`, `status.md` |

## Tiêu chí chấp nhận

| # | Tiêu chí | Test |
| --- | --- | --- |
| 1 | Box đúng vị trí khi vật có transform ≠ identity | "places each box at its object-local centre under a posed object" |
| 2 | Kéo `+x` 10 cm → `onChange` có half.x +5 cm, mặt −x đứng yên; không gọi khi đang kéo | "drags the +x face by the pointer distance and reports the box only on release" |
| 3 | Kéo xuống dưới sàn → thả xong đáy = floorZ | "keeps the bottom on the floor after a face drag pushes it below on release" (và bản cho translate) |
| 4 | Camera tắt khi kéo, bật lại sau thả hoặc Esc | "keeps pointer moves away from the camera while a face is dragged"; "…during a gizmo drag"; "cancels a drag on Escape…" |
| 5 | Chọn box khác → tay nắm chuyển sang đó, `onSelect` được gọi | "selects the box under the pointer and moves the handles to it" |
| 6 | `destroy` không còn entity hay listener | "takes every entity it added out of the scene graph"; "removes every pointer listener…"; "unregisters its frame handler…" |

## Lệnh kiểm tra và kết quả

Chạy trên code cuối (`0ddff8d0`), đúng khối "Tests required" của plan. Không chạy full suite.

- `vitest run tests/region-overlay.test.ts tests/scene-overlay-gizmo.test.ts tests/scene-overlay-pick.test.ts` → **48/48 pass** (3 file).
- `npm run typecheck` → **exit 0**.
- `eslint src/features/viewer/region-overlay.ts src/features/viewer/scene-overlay.ts tests/region-overlay.test.ts` → **exit 0**.
- `graphify update .` → exit 0.
- Trước bước 1, `scene-overlay-gizmo` và `scene-overlay-pick` đạt 12/12. Sau khi tách logic chặn pointer, vẫn 12/12.

Bằng chứng RED và đột biến:

- **Bước 2:** module được viết trước test, đây là sai thứ tự TDD. Bù lại bằng đột biến: đảo màu → test màu fail; tắt nét đứt → test nét đứt fail.
- **Bước 3:** 9 test fail trước khi có code. Sau đó sửa 2 lỗi harness (app root chưa bật nên entity không enabled; component render chưa gắn vào entity). Đây là lỗi của bản giả, không phải của overlay. Đột biến: `onChange` khi đang kéo → 2 test fail; bỏ huỷ khi Esc → 1 test fail.
- **Bước 4:** 6 test fail trước code. Đột biến: giữ vòng trục không phải Z → 1 fail; bỏ nhánh huỷ gizmo → 1 fail.
- **Bước 5:** 2 test fail trước code (`setFloorZ is not a function`). Test thứ ba (không có sàn) đã pass sẵn; đây là chủ ý, vì nó chốt hành vi cũ. Có một lỗi test của chính tôi: box đặt sát sàn, nên kẹp trả lại đúng box gốc và không có `onChange`. Đã sửa cho box lơ lửng 10 cm. Đột biến: bỏ kẹp khi thả → 1 fail.
- **Bước 6:** 6 test fail trước code. Đột biến: đảo hướng nhìn "top" → 1 fail.
- **Bước 7:** 5 test fail trước code. Đột biến: giữ listener pointerdown trên canvas → 1 fail; giữ handler khung hình → 1 fail.

## Quyết định (ruling)

A. **Kiểu host là `RegionHost = Pick<SceneOverlay, …>`**, không phải `SceneOverlay` như plan. `SceneOverlay` thoả kiểu này; test đưa bản giả vào. Chi phí nếu sai: không.

B. **`viewFrom` trả `boolean`**, không phải `void`. Trả false khi không có box chọn, chưa có camera, hoặc viewer chưa nối lệnh chuyển pose. Chi phí: caller bỏ qua kết quả thì không lỗi, nhưng sẽ không biết là không làm gì.

C. **`viewFrom` đi qua `gotoPose` của viewer**, không ghi pose vào camera entity. Lý do: camera của supersplat ghi lại entity mỗi frame (`vendor/supersplat/src/camera.ts`), nên ghi trực tiếp sẽ bị đè. `MetricSceneView.tsx` không nằm trong danh sách file của plan, nên việc nối `bindViewerGotoPose` để T-016 làm. Chi phí: `viewFrom` trả false cho tới khi T-016 nối.

D. **Tách logic chặn pointer của gizmo** thành `isolatePointerGesture` và `isolateGizmoPointer`, giữ nguyên hành vi. Test gizmo cũ xác nhận điều này. Chi phí: phần nội bộ của `attachGizmo` đổi chỗ.

E. **Gizmo xoay chỉ còn vòng Z.** `enableShape` tắt tương tác; ẩn hình qua `_shapes`, là phần nội bộ của PlayCanvas 2.22.4. Chi phí: phụ thuộc bản đã ghim.

F. **Gizmo tạo một lần cho mỗi overlay**, gắn hoặc gỡ theo box đang chọn, dùng layer gizmo chung. Chi phí: không.

G. **Chọn box bằng `pointerdown` ở pha bubble** trên canvas. Tay nắm và gizmo đã nuốt sự kiện ở pha capture nên không tới được đây. Chi phí: click lên box vẫn tới camera controller.

H. **Kẹp sàn áp dụng khi thả cho mọi thao tác** (kéo mặt, dịch, xoay). Với xoay, kẹp không đổi gì vì quay quanh Z không đổi đáy. Plan viết "clamp khi thả", không tách riêng xoay.

I. **Esc huỷ mọi cử chỉ đang kéo** và trả camera ngay, đúng plan. Chi phí: nếu chuột vẫn giữ, các chuyển động sau Esc sẽ xoay camera.

J. **`onChange` chỉ khi `boxesKey` đổi**, nên bấm mà không kéo thì im lặng. Chi phí: host muốn nhận mọi lần thả phải tự so sánh.

K. **Tay nắm luôn rộng khoảng 14 px trên màn hình.** Bỏ kích thước danh nghĩa 2,5 cm của plan. Chi phí: khi đứng sát, tay nắm nhỏ hơn 2,5 cm.

L. **Khoảng cách của `viewFrom` tính theo quả cầu bao box** (bán kính |half|, cộng 20 %), không theo từng trục. Chi phí: khung hơi rộng với box dẹt.

M. **Không làm hiệu ứng hover cho tay nắm.** Plan không yêu cầu.

N. **Không chuyển status sang `in-progress` lúc bắt đầu.** Đây là sai sót theo quy trình. Chuyển thẳng sang `implemented` lúc kết thúc.

## Việc giao cho T-016 (bắt buộc)

1. Nối lệnh chuyển camera: gọi `SceneOverlay.bindViewerGotoPose(controls.gotoPose)` ở nơi tạo overlay (`MetricSceneView.tsx`, `onApp`). Nếu không nối, `viewFrom` trả false.
2. Không gọi `setBoxes` lúc đang kéo. Lớp này giữ box gốc của lần kéo; gọi giữa chừng sẽ dựng lại hình nhưng lần kéo vẫn đi tiếp với box cũ.
3. Khi entity vật bị dựng lại (`setObjects`), tạo lại `RegionOverlay`. Khi gốc đã gỡ khỏi scene, mọi thao tác thành no-op.
4. Gọi `validateBoxes` trên box trước khi preview (đã có trong yêu cầu của T-016).

## Kiểm tra cần chủ dự án làm

- Trực quan trên browser: màu xanh và đỏ, nét đứt, độ dày viền khi chọn, cỡ tay nắm khoảng 14 px, vòng xoay chỉ trục Z, và hướng ba góc nhìn. Plan giao việc này cho chủ dự án, agent không chụp màn hình.

## Lệch quy trình

- Không tạo worktree: `.ai/README.md` cấm branch mới. Stage đúng đường dẫn và kiểm tra staged set trước mỗi commit.
- Không dùng subagent, theo quy tắc hệ thống. Final review là **self-review** theo checklist của `code-reviewer.md`; không có reviewer độc lập.
- Ledger ở scratchpad, cùng lý do như T-014.
- Không dùng `task-start` và `task-done`, vì plan dạng Steps.
- Không chạy full suite, theo yêu cầu.

## Việc còn dở

- Minor, hoãn: `FACE_AXIS` lặp bảng mặt của box model. Giữ cục bộ để không phải export phần nội bộ.
- Minor, hoãn: `_shapes` là nội bộ của PlayCanvas. Khi nâng phiên bản phải kiểm lại bước 4.
- Chưa có UI nối vào Studio. Việc này thuộc T-016.
