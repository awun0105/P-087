# Review T-014

Verdict: ACCEPTED

Đã đọc `plan.md`, `report.md` và toàn bộ `frontend/src/features/studio/region/box-model.ts`. Chạy lại:
vitest `region-box-model.test.ts` 38/38 PASS, `npm run typecheck` PASS, eslint PASS.

## Acceptance criteria
1. `dragFace +x 0.1` yaw 0: half.x +0,05, tâm +0,05, mặt −x đứng yên: **pass**.
2. Cùng thao tác yaw π/2 dịch theo +y world: **pass** (trục x box = (cos, sin, 0)).
3. Kéo âm quá mức kẹp `MIN_HALF_M`, không đảo chiều: **pass** (tâm chỉ dịch bằng phần half thực đổi).
4. `fitBoxToPoints` hộp xoay 30°: **pass**; nhánh hoán trục có test riêng.
5. `clampToFloor` giữ đỉnh, đáy = floorZ: **pass**; trường hợp đỉnh sát sàn nâng đỉnh có giải thích.
6. `contains` có dung sai 1e-6, NaN bị từ chối: **pass**.
7. `validateBoxes` đủ 3 thông điệp: **pass**.
8. `boxesKey` đổi khi thay đổi ≥ 1e-6, không gồm id: **pass**.

## Các quyết định Engineer tự đưa ra (đều chấp nhận)
1. Khai báo `RegionBox` cục bộ vì T-004 chưa làm: hợp lý. T-004 bước 5 đã thêm việc đổi sang import từ `api.ts`.
2. Lề áp cả trục z, đáy bám điểm thấp nhất: đúng ý "đáy bám sàn".
3. `fitBoxToPoints` không kẹp, để `validateBoxes` báo lỗi: đúng tinh thần "không âm thầm sửa". T-016 đã thêm yêu cầu
   không gọi preview khi box không hợp lệ.
4. `boxesKey` lượng tử 1e-7, bỏ id: hợp lý.

Với câu hỏi "có cần dừng ở mọi chỗ lệch plan như vậy không": **không**. Lệch chỉ ảnh hưởng nội bộ task và đảo được dễ
thì cứ quyết và ghi vào report, như lần này. Chỉ dừng khi quyết định ảnh hưởng contract giữa module, dữ liệu đã lưu, hoặc khó đảo.

## Trả lời câu hỏi cho Architect
1. **Giới hạn half:** chốt khoảng **đóng [0.005, 20] m**. Đã sửa `architecture.md` §7.3 (trước ghi "> 0.005") và T-004 thêm tiêu chí 0.
2. **Dấu yaw:** chốt quay phải quanh +Z, trục x box = (cos yaw, sin yaw, 0), khớp client. Đã ghi rõ vào `architecture.md`
   và T-004.
3. **Dung sai 1e-6 và lề z:** dung sai chốt 1e-6 m cả hai phía. Lề z chỉ là chuyện khởi tạo của client, server không cần biết.
   Để chắc hai phía khớp, T-004 bước 6 tạo file ca kiểm dùng chung `tests/fixtures/region_box_cases.json`, cả pytest và vitest
   cùng đọc.

## Về quy trình
- Không dùng worktree, stage đúng đường dẫn: đúng.
- Tự review thay vì subagent: chấp nhận được, vì Architect review độc lập ở đây.
- Đặt `implemented` dù có câu hỏi không chặn: đúng cách.

## Required changes
Không có.

## Suggestions (không chặn)
- `clampToFloor` trả bản sao khi không cần kẹp (`{ ...box }`), nhưng `center`/`half` vẫn dùng chung mảng với đầu vào.
  Không sai vì mọi hàm đều không sửa mảng tại chỗ; nếu sau này có code sửa tại chỗ thì cần copy sâu.
