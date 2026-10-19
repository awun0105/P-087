# Review T-017

Verdict: ACCEPTED

Review **code**: đọc trọn `shell-glow.ts` (320 dòng) và toàn bộ diff `MetricSceneView.tsx`, `ObjectReviewView.tsx`,
`RegionEditor.tsx`, `region-session.ts`; đối chiếu `objectify._publish_draft`, `useRegionPreview`, `scene-overlay.setObjects`,
`representation_composition.resolve_representation`. Chạy lại 5 file test liên quan: 178/178 PASS.

## Acceptance criteria
1. Pass. Vỏ là con của `objectEntity(id)`. Đã kiểm entity cha **bật** trong Draft: CANDIDATE có `isPlaced = true`, IGNORED đi
   nhánh `source` đặt `visible = shown`; Hide tắt entity nên vỏ ẩn cùng vật (đúng). `geometry_ref` Draft là GLB vỏ 0,05 m
   object-local (`_publish_draft`), khớp khung của entity (Move bị khoá trong Draft).
2. Pass. `setShell` gỡ vỏ cũ (entity, vật liệu, asset, blob URL) trước khi nạp; vỏ bị thay giữa lúc nạp được bỏ qua khi `load`.
3. Pass. Mỗi loại một mesh điểm, `depthTest=false`; đóng panel → `showPreview(id, null, false)` xoá điểm và trả vỏ gốc.
   `loading` của `useRegionPreview` bật ngay khi box đổi, nên không có nhấp nháy "đóng → mở" giữa hai lần xem trước.
4. Pass. Draft: mọi `ObjectGaussians` có `url: null`; Ready giữ hành vi cũ, `shells = []`.
5. Pass. Giảm chuyển động: không nhịp, không `requestFrame`, vỏ đang nhịp trả về độ mờ gốc.
6. Pass. `destroy` gỡ hết và gỡ đăng ký `update`; gọi lại an toàn. Trong `onApp`, lớp vỏ bị huỷ trước overlay.

## Quyết định về lệch plan
- **Cỡ điểm 1 px: chấp nhận tạm.** Không viết shader `gl_PointSize` (không kiểm được, và WebGPU không có point size).
  Chủ dự án nhìn bằng mắt; nếu điểm khó thấy → task nhỏ tiếp theo vẽ mỗi điểm là một khối nhỏ cỡ thế giới
  (~1 cm, gộp một mesh tam giác, ≤ 20.000 × 2), không cần shader riêng.
- `MetricSceneView` sở hữu `ShellGlowLayer`, thêm `setTone`, prop `shells`, `showPreview`: chấp nhận, hợp lý hơn plan.

## Suggestions (không chặn)
1. Vật Draft có `provenance.shell_error` đang có vỏ là **hộp giữ chỗ** nhưng tô cùng màu xanh như vỏ thật. Nên vẽ tone `warning`
   để người dùng biết vật nào sẽ làm build lỗi trước khi bấm "Tạo mesh".
2. Lỗi nạp vỏ bị nuốt (`catch(() => undefined)`); chấp nhận được, có thể ghi console.warn để dễ gỡ lỗi.
3. Cache GLB xem trước theo checksum nếu thấy giật khi kéo box.
