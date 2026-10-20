# T-064 report: viewer không dựng lại, không vẽ thừa, tab ẩn thì nghỉ

## Đã làm
- `ObjectReviewView`: prop truyền cho viewer giữ nguyên tham chiếu khi dữ liệu 3D không đổi: mảng dấu bề mặt rỗng dùng chung
  (trước đây `?? []` tạo mảng mới mỗi render → overlay gỡ và dựng lại mesh dấu bề mặt rồi vẽ lại cả cảnh), `inspection`,
  `collisionDiagnostics` qua `useMemo`, bốn callback sửa bề mặt / dời vật qua `useCallback` gọi bản `run` mới nhất.
- `ObjectReviewView` chỉ dựng viewer khi danh sách camera đã về (kể cả lỗi); trước đó scene về trước làm viewer dựng hai lần và tải
  SOG môi trường hai lần.
- `viewer/runtime-publisher.ts`: thời gian quỹ đạo và tiến độ tải báo cho giao diện tối đa 4 lần/giây, luôn kết thúc ở giá trị cuối;
  trạng thái khác báo ngay.
- `viewer/viewerActive.ts` + `PlayCanvasScene`: rời tab Studio thì thoát Walk, đặt `timeScale = 0` và không vẽ; tab trình duyệt ẩn
  cũng nghỉ (không thoát Walk); hiện lại thì chạy tiếp và vẽ một khung. `ScenePage` cấp ngữ cảnh theo tab hiện tại.
- `shell-glow`: nhịp sáng của vỏ vật đang chọn cập nhật ~10 lần/giây thay vì mỗi khung (mỗi lần là một lần vẽ lại cả cảnh splat).

## Lệch so với plan (Ruling trong ledger)
- Dùng ngữ cảnh thay cho prop `active` + `setSuspended` công khai. Không bọc `StudioTab` bằng `React.memo`.

## Số từ test
| Đo | Trước | Sau |
|---|---|---|
| Prop dữ liệu đổi tham chiếu sau 5 lần render cha | `surfacePlanes`, `inspection`, … (mỗi lần) | 0 |
| Số lần dựng viewer khi scene về trước camera | 2 | 1 |
| Lần báo trạng thái cho 60 khung quỹ đạo trong 1 s | 60 | ≤ 5 |
| Lần yêu cầu vẽ do nhịp vỏ trong 1 s | 61 | ≤ 11 |

## Kiểm thử
`viewer-render-churn`, `viewer-mount-once`, `viewer-publish-throttle`, `studio-suspend`, `shell-glow`, `object-review`,
`preview-scene-camera`, `playcanvas-camera`, `collider-loading`, `ux-scene-flow`: xanh. Typecheck, eslint sạch.
Người dùng tự kiểm bằng mắt độ mượt khi xoay, phát quỹ đạo và chuyển tab.
