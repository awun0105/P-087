TASK: CFG-13-SCENARIO-WIZARD-UI

STATUS: DONE — wizard, advanced groups, real scene-flow wiring and regression checks verified.

## Implementation and verification (2026-10-13)

- Added four accessible native radio groups for capture type, environment, subject scope and capacity target. No scenario is shown as applied until the backend returns a valid suggestion. The applied badge includes scenario and capacity target.
- The real caller is `UnifiedInputFlow.tsx`; it now passes the scenario command and displays the selected scenario in the confirmation summary. The existing three-step flow, uploads and attestation fields remain intact.
- Suggestions validate against the loaded schema, apply values/evaluation together, abort stale requests, and preserve manual edits. Editing a parameter clears the scenario badge. Clicking a checked scenario choice reapplies its preset after manual edits.
- Reused the suggestion's evaluation rather than issuing an extra evaluation for the same values. Manual edits and explicit retries still use the existing debounce/evaluation path.
- Scenario choices survive moving back through form steps. The wizard does not apply a default on mount or overwrite restored parameter drafts.
- Expanded advanced settings to all six groups. Existing dropdown/slider/number renderers now expose matching mode, collision mesh, fill sizes, scene/provider controls and simulation controls. Read-only mode hides the wizard and disables every parameter input.
- Additional required paths: `frontend/src/features/studio/UnifiedInputFlow.tsx`, `frontend/tests/unified-input-flow.test.tsx`, `frontend/tests/ux-processing-form.test.tsx`. Also corrected an outdated assertion in `frontend/tests/object-review.test.tsx`: the current failure notice reports the backend detail instead of promising a fixed retry count. No objectify runtime behavior was changed.

### Executable checks

- Focused component/form/flow run: 34 passed. Remediation run including object review: 65 passed. Logs: `CFG13-COMPONENT-CHECKPOINT.log`, `CFG13-REMEDIATION-TESTS.log`.
- Final `pnpm exec vitest run`: **536 passed across 65 files**, no failed or skipped tests (`tasks/reports/CFG13-FRONTEND-REGRESSION.log`). Initial full run found the redundant evaluation and stale object-review assertion; both were corrected before this final run.
- `pnpm typecheck`: route type generation and tsc --noEmit passed (`CFG13-TYPECHECK.log`). ESLint on changed source/tests: clean (`CFG13-ESLINT.log`). `git diff --check`: clean.
- Chrome DevTools: real `/new` flow with a generated 3-second video, browser preparation, upload and assembly resolution against an isolated temporary database. Outdoor + loop choices produced matching=sequential_vocab_tree, external fill=0, floor fill=1.6 and ground plane=disabled. Selecting Mặt voxel produced mesh=faces, removed the applied badge and displayed custom mode. Forward/back navigation preserved all four choices and mesh=faces. Suggest/evaluate HTTP requests returned 200; console error/warning list was empty.
- Screenshot: `tasks/reports/CFG13-WIZARD-DESKTOP.jpg`, inspected at 1920×908. Local QA used auth-disabled mode and a fixture runtime manifest; no reconstruction worker or new scene job was run. This proves local browser/configuration interaction, not GPU, Isaac or production acceptance.
- graphify AST graph refreshed after source changes.

### Pre-flight (GUIDE.md Rule 13)

- codegraph: ProcessingSettings, useProcessingForm and actual callers; contract/client paths from CFG-12; ObjectifyNotice inspected before correcting the old assertion.
- impact: real create-scene configuration/summary, sample read-only settings, hook request lifecycle and related frontend tests.
- understand: UNVERIFIED — understand-anything unavailable; current source, task contracts and backend audit used for flow tracing.
- minimal-code: reused existing parameter renderer, form hook, ApiResult client and native radios/details; no new dependency.
- checks: TypeScript/ESLint clean, full Vitest 536 passed.
- DevTools: local QA /new wizard and advanced controls verified, request statuses 200, console clean. Browser audit CFG-14 still follows this task.

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
