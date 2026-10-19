# T-029: Bộ đếm phút công người + sự kiện Walk (frontend)

## Goal
Trình duyệt tự đo thời gian kỹ sư thực sự thao tác trên trang scene và gửi về API của T-027; Walk gửi một phiên khi kết thúc.

## Context
§15.3 quy tắc 1. Route ở T-027. Trang scene: `ScenePage.tsx` (tab progress/studio/review/results). Walk bật/tắt trong
`MetricSceneView` / `PlayCanvasScene` (`toggleWalk`), vật lý ở `usePhysicsPlay`.

## Files
- Tạo: `frontend/src/features/studio/value/useOperatorTime.ts`, `frontend/src/lib/api/value.ts`
- Sửa: `ScenePage.tsx` (gắn hook, `surface` theo tab), nơi bật/tắt Walk (gửi `walk_session`)
- Test: `frontend/tests/operator-time.test.ts(x)`, test Walk liên quan

## Interfaces
```ts
useOperatorTime({ jobId, surface, enabled }): void
// active = document.visibilityState === "visible" && lần thao tác cuối (pointerdown/keydown/wheel/pointermove có nút) ≤ 60 s.
// Mỗi giây cộng 1 s nếu active. Gửi lô khi ≥ 30 s đã trôi, khi đổi surface, khi tab ẩn (fetch keepalive), khi unmount.
// session_key: crypto.randomUUID() mỗi lần mount. Không gửi lô active_seconds = 0.
postOperatorTime(jobId, batch): Promise<void>   // lỗi: bỏ qua lô, không thử lại vô hạn (tối đa 1 lần thử lại)
postWalkSession(jobId, { scene_revision, started_at, ended_at, outcome })
```
Chỉ bật khi người xem có quyền sửa job (`canMutateJob`); chế độ xem mẫu/video mẫu không gửi.

## Steps
1. API client + hook với đồng hồ giả trong test (vi.useFakeTimers): rảnh 61 s thì ngừng cộng; tab ẩn thì ngừng và gửi lô;
   lô không chồng nhau, không vượt 300 s. Commit.
2. Gắn vào `ScenePage`, `surface` theo tab hiện tại. Test: đổi tab gửi lô của tab cũ. Commit.
3. Walk: lưu `started_at` khi bật, gửi khi tắt hoặc rời trang; `outcome = completed` nếu Walk chạy ≥ 5 s, ngược lại `aborted`. Commit.

## Acceptance criteria
1. Không gửi gì khi người xem không có quyền sửa job.
2. Thời gian rảnh > 60 s và thời gian tab ẩn không được tính.
3. Mỗi lô thoả luật máy chủ (≤ 300 s, active ≤ wall, không chồng).
4. Lỗi mạng không làm phiền người dùng (không toast), không lặp gửi vô hạn.

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run <file test mới và test Walk đã sửa> && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
