TASK: CFG-13-SCENARIO-WIZARD-UI

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Bảng cấu hình hiện tại của Web Studio chỉ hiển thị 2 nút Preset thô sơ và một danh sách thông số kỹ thuật khô khan. Người dùng phổ thông khi nhìn vào sẽ cảm thấy hoang mang vì không biết video của mình nên chỉnh thế nào để không bị vỡ mô hình.
  Họ cần một **Trợ lý chọn nhanh kịch bản (Scenario Wizard)** đặt ngay đầu bảng cài đặt với các ô chọn cấp cao trực quan:
  - Kiểu quay: *Đi bộ liên tục* | *Quay vòng 360°* | *Tập ảnh rời*.
  - Không gian: *Trong nhà (Indoor)* | *Ngoài trời (Outdoor)*.
  - Phạm vi: *Một đồ vật* | *Toàn bộ căn phòng*.
  - Tải máy: *Tối thiểu cho máy này* | *Cân bằng* | *Tối đa cho máy này*.
  Khi bấm vào các ô này, giao diện lập tức tự động áp dụng bộ Preset tương ứng, nhảy toàn bộ số liệu tối ưu và cập nhật thanh đo tài nguyên (RAM/VRAM/Disk), trong khi người dùng nâng cao vẫn có thể mở rộng danh sách chi tiết bên dưới để tinh chỉnh từng cờ nếu muốn.
- **Yêu cầu cốt lõi (What):** Nâng cấp `ProcessingSettings.tsx`:
  1. Thêm khối giao diện **Scenario Wizard** (các nhóm nút radio/chips trực quan để chọn loại video, không gian, phạm vi và mục tiêu máy).
  2. Tự động gọi API `suggestProcessingPreset()` khi người dùng chọn wizard để cập nhật bảng thông số.
  3. Mở rộng render các nhóm thông số chi tiết bên dưới gồm đầy đủ `geometry` (cho phép chọn `smooth` hoặc `faces`, chỉnh `external_fill`), `scene` (chỉnh `max_objects`), và `simulation`.

GOAL:
Nâng cấp giao diện bảng cấu hình `ProcessingSettings.tsx` trên Web Studio, tích hợp Trợ lý chọn nhanh kịch bản (Scenario Wizard với các ô chọn cấp cao) tự động đề xuất preset và cập nhật cấu hình tối ưu cho người dùng.

INPUT CONTRACT:
- `frontend/src/features/studio/ProcessingSettings.tsx`.
- `frontend/src/features/studio/useProcessingForm.ts`.
- Contracts từ `frontend/src/lib/contracts/studio.ts` (từ CFG-12).
- Hàm gọi API `suggestProcessingPreset` từ `frontend/src/lib/api/studio.ts`.
- Danh mục tham số và giải thích UI trong `docs/execution/CONFIG_CATALOG.md`.

OUTPUT CONTRACT:
- Khối điều khiển **Scenario Wizard** đặt ở phần trên của `ProcessingSettings.tsx`:
  - 4 câu hỏi trực quan dạng chip/radio cards:
    1. *Kiểu video:* Video đi bộ liên tục / Video quay vòng 360° / Tập ảnh rời.
    2. *Môi trường:* Trong nhà (Indoor) / Ngoài trời (Outdoor).
    3. *Mục tiêu:* Một vật thể (Single object) / Toàn bộ căn phòng (Full room).
    4. *Cấu hình máy:* Tối thiểu cho máy này / Cân bằng / Tối đa cho máy này.
  - Khi người dùng click, bảng thông số tự động nhảy toàn bộ giá trị phù hợp và hiển thị badge thông báo preset đang được áp dụng.
- Khu vực danh mục chi tiết (Advanced Settings Accordion/Group):
  - Hiển thị đầy đủ các nhóm: Lấy mẫu, COLMAP, Brush 3DGS, Lưới va chạm Voxel, Tách vật thể CoACD, Mô phỏng OpenUSD.
  - Render dropdown chọn `colmap.matching_mode` (kèm giải thích từng mode).
  - Render dropdown chọn `geometry.collision_mesh` (`smooth`: mượt mà cho robot / `faces`: khối voxel góc cạnh).
  - Render slider cho `geometry.external_fill_size_m` (kèm ghi chú: đặt 0.0 khi quay ngoài trời).
- Trạng thái `editable=false` vẫn xem được toàn bộ thông số ở chế độ Read-only.

OWNED FILES:
- `frontend/src/features/studio/ProcessingSettings.tsx`
- `frontend/src/features/studio/useProcessingForm.ts`
- `frontend/tests/processing-settings.test.tsx`

FILES YOU MAY MODIFY:
- `frontend/src/features/studio/`
- `frontend/tests/`

FILES YOU MUST NOT MODIFY:
- `src/` (Backend code)

PRIMARY TOOL:
- React 19, Tailwind CSS, Lucide icons, Vitest / Testing Library.

IMPLEMENT:
1. Thiết kế state cục bộ cho `ScenarioPreferences` trong `ProcessingSettings.tsx`.
2. Tạo component con `ScenarioWizard` hiển thị các nhóm chip lựa chọn:
   - Dùng icon trực quan của `lucide-react` (Camera, RotateCcw, Home, Trees, Box, Maximize2, Sparkles).
3. Kết nối sự kiện thay đổi: khi user chọn một tiêu chí trong Wizard, gọi `suggestProcessingPreset` (hoặc tra cứu preset tương ứng) và cập nhật thông qua callback `onChange`.
4. Mở rộng rendering nhóm `geometry` và `scene` trong danh sách thông số chi tiết bên dưới.
5. Viết component test trong `frontend/tests/processing-settings.test.tsx`:
   - Test render các chip lựa chọn của Scenario Wizard.
   - Test click chuyển đổi kịch bản (ví dụ từ Trong nhà sang Ngoài trời) tự động cập nhật cờ `external_fill` và `matching_mode`.
   - Test thay đổi dropdown `collision_mesh` từ `smooth` sang `faces`.

TEST:
- `cd frontend && npx vitest run tests/processing-settings.test.tsx`
- `cd frontend && npx vitest run tests/ux-processing-form.test.tsx`
- `cd frontend && pnpm typecheck`

DONE WHEN:
- Giao diện Web Studio có trải nghiệm người dùng trực quan, hỗ trợ chọn kịch bản cấp cao tự động và tùy chỉnh sâu từng cờ kỹ thuật.
- Toàn bộ tests của frontend pass 100%.

EVIDENCE:
- File `frontend/src/features/studio/ProcessingSettings.tsx`
- Test log `cd frontend && npx vitest run tests/processing-settings.test.tsx`
