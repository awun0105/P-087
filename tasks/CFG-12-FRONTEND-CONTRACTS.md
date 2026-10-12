TASK: CFG-12-FRONTEND-CONTRACTS

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Frontend TypeScript hiện tại đang gò bó nghiêm ngặt các kiểu dữ liệu (`ParameterSpec.group` chỉ là `"sampling" | "colmap" | "brush"`, `ProcessingOptions.presets` chỉ có 3 keys). Nếu không cập nhật file hợp đồng `studio.ts` và API client `frontend/src/lib/api/studio.ts`, TypeScript compiler (`tsc --noEmit`) sẽ báo lỗi đỏ toàn bộ dự án khi nhận các nhóm cấu hình mới và frontend không thể gọi hàm gọi API gợi ý preset `/processing/suggest`.
- **Yêu cầu cốt lõi (What):** Mở rộng type definitions trong `frontend/src/lib/contracts/studio.ts` (thêm `ScenarioPreferences`, mở rộng `group` và `presets`), đồng thời bổ sung hàm gọi API `suggestProcessingPreset()` trong `frontend/src/lib/api/studio.ts`.

GOAL:
Đồng bộ các kiểu dữ liệu và hợp đồng TypeScript trong `frontend/src/lib/contracts/studio.ts` và API client `frontend/src/lib/api/studio.ts` để hỗ trợ các nhóm thông số mới, các presets kịch bản và hàm gọi API gợi ý preset tự động.

INPUT CONTRACT:
- `frontend/src/lib/contracts/studio.ts`.
- `frontend/src/lib/api/studio.ts`.
- Schema trả về từ API `/api/studio/processing/options` và `/api/studio/processing/suggest` (từ CFG-10).

OUTPUT CONTRACT:
- Mở rộng kiểu `ParameterSpec` trong `studio.ts`:
  `group: "sampling" | "colmap" | "brush" | "geometry" | "scene" | "simulation"`
- Định nghĩa kiểu mới `ScenarioPreferences`:
  ```typescript
  export interface ScenarioPreferences {
    input_type: "video_continuous" | "video_loop_360" | "photo_set";
    environment: "indoor" | "outdoor";
    subject_scope: "single_object" | "full_room";
    target_capacity: "minimum_quality" | "balanced" | "machine_maximum";
  }
  ```
- Định nghĩa kiểu mới `SuggestResponse`:
  ```typescript
  export interface SuggestResponse {
    preset_name: string;
    params: Record<string, ParamValue>;
    evaluation: ProcessingEvaluation;
  }
  ```
- Mở rộng `ProcessingOptions.presets`: `Record<string, Record<string, ParamValue>>`.
- Hàm API client trong `frontend/src/lib/api/studio.ts`:
  `suggestProcessingPreset(preferences: ScenarioPreferences): Promise<ApiResponse<SuggestResponse>>`.

OWNED FILES:
- `frontend/src/lib/contracts/studio.ts`
- `frontend/src/lib/api/studio.ts`
- `frontend/tests/studio-contracts.test.ts`

FILES YOU MAY MODIFY:
- `frontend/src/lib/contracts/`
- `frontend/src/lib/api/`
- `frontend/tests/`

FILES YOU MUST NOT MODIFY:
- `src/` (Backend code)
- `configs/`

PRIMARY TOOL:
- TypeScript, Vitest, PNPM typecheck (`pnpm typecheck`).

IMPLEMENT:
1. Sửa `ParameterSpec` trong `frontend/src/lib/contracts/studio.ts`:
   - Bổ sung `"geometry" | "scene" | "simulation"` vào union type của `group`.
2. Thêm `ScenarioPreferences` và `SuggestResponse` vào `studio.ts`.
3. Cập nhật `suggestProcessingPreset` trong `frontend/src/lib/api/studio.ts`:
   - Gọi `POST /api/studio/processing/suggest` và trả về kết quả đã parse.
4. Viết bài test hợp đồng trong `frontend/tests/studio-contracts.test.ts`:
   - Kiểm tra việc parse một payload mẫu từ API chứa các trường mới và gợi ý preset.
5. Chạy TypeScript compiler kiểm tra toàn bộ frontend.

TEST:
- `cd frontend && npx vitest run tests/studio-contracts.test.ts`
- `cd frontend && npx vitest run tests/ux-processing-form.test.tsx`
- `cd frontend && pnpm typecheck`

DONE WHEN:
- Toàn bộ type definitions trong frontend khớp hoàn toàn với Backend contract.
- `tsc --noEmit` không có bất kỳ lỗi type nào.

EVIDENCE:
- File `frontend/src/lib/contracts/studio.ts`
- Log kiểm tra `cd frontend && pnpm typecheck`
