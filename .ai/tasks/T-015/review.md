# Review T-015

Verdict: ACCEPTED

Đã đọc `report.md`, diff `scene-overlay.ts` (phần tách cô lập pointer) và các đoạn chính của `region-overlay.ts`
(gắn vào entity vật, kéo mặt, gizmo, clamp sàn, `viewFrom`). Chạy lại: vitest `region-overlay`, `scene-overlay-gizmo`,
`scene-overlay-pick`, `object-review`, `metric-effective-collision` → 101 passed; `npm run typecheck` PASS.

## Acceptance criteria
1. Box đúng vị trí khi vật có transform ≠ identity: **pass**. Box là con của `objectEntity(id)`, entity này nằm dưới gốc đã xoay
   `DISPLAY_EULER.z_up`, nên toạ độ box là object-local Z-up đúng với box model.
2. Kéo `+x` → `onChange` nhận box đúng, không gọi khi đang kéo: **pass**.
3. Clamp sàn khi thả: **pass**.
4. Camera controller tắt khi kéo, bật lại khi thả/Esc: **pass**.
5. Chọn box khác chuyển tay nắm + `onSelect`: **pass**.
6. `destroy()` không rò entity/listener: **pass**.

## Phần sửa trong SceneOverlay (dùng chung)
Tách `isolatePointerGesture`/`isolateGizmoPointer` từ code gizmo Move/Rotate sẵn có, thêm accessor (`objectEntity`, `activeCamera`,
`sharedGizmoLayer`, `requestFrame`, `gotoPose`/`bindViewerGotoPose`). Đều là bổ sung; test gizmo và object-review cũ PASS nên hành vi
Move/Rotate hiện tại không đổi. **Chấp nhận**, kể cả việc Engineer không dừng hỏi: thay đổi là cộng thêm, dễ gỡ, và đã được kiểm.

## Quyết định Engineer (chấp nhận)
- `viewFrom` đi qua `gotoPose` của viewer và trả boolean: đúng, vì camera supersplat ghi đè entity mỗi frame.
- Tay nắm ~14 px trên màn hình thay vì 2,5 cm: đúng ý plan (plan ghi "luôn ~14 px").
- Esc huỷ kéo và trả camera ngay: đúng plan. Nếu còn giữ chuột, camera nhận cử chỉ tiếp: chấp nhận.
- Clamp sàn cho mọi thao tác khi thả: được.

## Bàn giao (đã ghi vào plan)
- T-016: nối `bindViewerGotoPose`, không `setBoxes` khi đang kéo, tạo lại overlay khi entity vật dựng lại.
- T-017 bước 5: Draft vẫn phải có `OverlayObject` (url null) cho mọi vật để có entity gắn box/vỏ. Plan cũ ghi "không đưa vật vào
  overlay" sẽ làm RegionOverlay không có chỗ gắn; đã sửa.

## Required changes
Không có.

## Ghi chú
- Kiểm tra bằng mắt (màu, nét đứt, độ dày viền, kích thước tay nắm, vòng Z, ba góc nhìn) là việc của chủ dự án, làm sau T-016 khi
  editor được nối vào Studio.
- Quy trình: chưa đặt `in-progress` lúc bắt đầu; lần sau đặt để agent khác biết task đang có người làm.
