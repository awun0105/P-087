TASK: CFG-14-AUDIT-UI-UX

STATUS: PASS — Ready for Final E2E Verification.

## Implementation and evidence (2026-10-13)

- Audit report: `tasks/reports/AUDIT_03_UI_UX_REPORT.md`, with requirement-by-requirement evidence for transitions, read-only mode, debounce, errors, TypeScript and regression coverage.
- Added exact fake-clock verification for the 300 ms debounce and cancellation of old evaluation requests.
- Added actual create-scene component coverage for evaluation HTTP 500, retained edited values, blocked continuation and successful Retry.
- Found and repaired invented fallback values in historical read-only samples: absent recorded fields now explicitly say they were not recorded.
- Required source/test files: `frontend/src/features/studio/ProcessingSettings.tsx`, `frontend/tests/processing-settings.test.tsx`, `frontend/tests/ux-processing-form.test.tsx`, `frontend/tests/unified-input-flow.test.tsx`.
- Focused contract/component/hook suites: 19 passed. Full frontend run: 538 passed; the subsequently added UI recovery case passed in the 28-case actual-flow suite. TypeScript and ESLint clean.
- Chrome DevTools opened the actual aisle-cw sample and verified no wizard, all 21 recorded controls disabled, 24 unrecorded fields displayed honestly, and an empty console error/warning list. Local QA uses temporary database state, not production acceptance.
- graphify updated after source changes. No backend source changes.


## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Sau khi hoàn thành việc triển khai Frontend Contracts (CFG-12) và Scenario Wizard UI (CFG-13), giao diện Web Studio có rất nhiều trạng thái động (state transitions) phức tạp giữa UI và API:
  1. Khi người dùng click chọn chip Scenario Wizard, state phải tự động nhảy toàn bộ values và badge preset. Nhưng nếu họ chỉnh tay 1 ô slider sau đó, UI có tự động chuyển sang chế độ "Đang dùng thông số tùy chỉnh" không, hay vẫn báo là đang dùng preset kịch bản?
  2. Ở chế độ xem video mẫu (`editable=false`), nếu UI vô tình cho phép click vào các chip Wizard hoặc chỉnh sửa dropdown, dữ liệu mẫu sẽ bị sai lệch.
  3. Khi API tính toán tài nguyên bị lỗi mạng tạm thời, hook `useProcessingForm` có giữ lại được giá trị form của người dùng không, hay xóa sạch giá trị?
  4. Nếu không có cổng audit chuyên trách này, các lỗi giật lag UI, re-render vô tận (infinite loop), hoặc type errors tiềm ẩn sẽ lọt vào bản build cuối cùng.
- **Yêu cầu cốt lõi (What):** Đây là **Cổng kiểm soát chất lượng trung gian (Audit Gate 3)**. Agent đóng vai trò kiểm toán viên Frontend/UX: audit toàn diện logic state trong `useProcessingForm.ts` và `ProcessingSettings.tsx`, kiểm tra hành vi tương tác thực tế, kiểm tra khả năng phục hồi lỗi mạng, chạy kiểm tra nghiêm ngặt `pnpm typecheck` và toàn bộ test suite frontend.

GOAL:
Thực hiện audit và tự kiểm tra chất lượng độc lập cho toàn bộ giao diện Web Studio UI / UX và TypeScript State Hooks (sau khi hoàn thành CFG-12 và CFG-13), bảo đảm giao diện mượt mà, phản hồi chính xác, tuân thủ nghiêm ngặt quy tắc Readonly và không có lỗi runtime/type errors.

INPUT CONTRACT:
- Kết quả triển khai từ `CFG-12-FRONTEND-CONTRACTS` và `CFG-13-SCENARIO-WIZARD-UI`.
- Các file frontend:
  - `frontend/src/features/studio/ProcessingSettings.tsx`
  - `frontend/src/features/studio/useProcessingForm.ts`
  - `frontend/src/lib/contracts/studio.ts`
  - `frontend/src/lib/api/studio.ts`

OUTPUT CONTRACT:
- Báo cáo kiểm toán Milestone 3 (`tasks/reports/AUDIT_03_UI_UX_REPORT.md`):
  - Kết quả kiểm tra các chuyển đổi trạng thái (State transitions: Preset $\rightarrow$ Custom $\rightarrow$ Preset).
  - Kết quả kiểm tra chế độ chỉ đọc (`editable=false`).
  - Kết quả kiểm tra cơ chế debounce và khả năng chịu lỗi API evaluation.
  - Kết quả chạy `pnpm typecheck` (0 errors).
  - Kết quả chạy các bài test Vitest của frontend.
  - Kết luận rõ ràng: `PASS - Ready for Final E2E Verification` hoặc `FAIL - Blocked with remedial actions`.

OWNED FILES:
- `tasks/reports/AUDIT_03_UI_UX_REPORT.md`

FILES YOU MAY MODIFY:
- Các file thuộc phạm vi CFG-12 và CFG-13 nếu phát hiện lỗi hoặc bất cập cần sửa chữa.
- `tasks/reports/`

FILES YOU MUST NOT MODIFY:
- `src/` (Backend code)

PRIMARY TOOL:
- TypeScript (`tsc --noEmit`), Vitest, Testing Library, React 19.

AUDIT CHECKLIST & VERIFICATION:
1. **Kiểm tra tương tác Scenario Wizard & State Transitions:**
   - Click chọn chip Wizard: form cập nhật đầy đủ giá trị, active preset badge hiển thị đúng tên preset.
   - Chỉnh sửa thủ công 1 thông số (ví dụ đổi SIFT features): active preset badge tự động chuyển sang "Đang dùng thông số tùy chỉnh".
   - Click lại chip Wizard: form reset về đúng giá trị của preset được chọn.
2. **Kiểm tra chế độ Readonly (`editable=false`):**
   - Mở màn hình video mẫu: Badge "Chỉ đọc" hiển thị.
   - Toàn bộ chips của Scenario Wizard bị ẩn hoặc disabled.
   - Tất cả dropdowns, sliders, inputs bị khóa không thể tương tác.
3. **Kiểm tra Debounce & Error Resilience:**
   - Khi người dùng kéo slider liên tục, API `evaluateProcessing` chỉ được gọi sau khi dừng 300ms (debounce), request cũ bị abort.
   - Khi API trả về lỗi 500, form không bị reset trắng values mà hiển thị thông báo lỗi kèm nút "Thử lại".
4. **Kiểm tra TypeScript Compiler:**
   - Chạy `cd frontend && pnpm typecheck`.
   - Kết quả: Không có bất kỳ cảnh báo hoặc lỗi type nào (`0 errors`).
5. **Chạy toàn bộ Vitest Suites Frontend:**
   - `cd frontend && npx vitest run tests/ux-processing-form.test.tsx`
   - `cd frontend && npx vitest run tests/processing-settings.test.tsx`
   - `cd frontend && npx vitest run tests/studio-contracts.test.ts`

DONE WHEN:
- Toàn bộ checklist kiểm tra trên đạt 100%.
- `pnpm typecheck` pass với 0 lỗi.
- File báo cáo `tasks/reports/AUDIT_03_UI_UX_REPORT.md` được ghi nhận với kết luận `PASS`.

EVIDENCE:
- File `tasks/reports/AUDIT_03_UI_UX_REPORT.md`
- Terminal log thực thi của `pnpm typecheck` và Vitest.
