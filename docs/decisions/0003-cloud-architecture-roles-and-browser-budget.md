# 0003 Kiến trúc cloud client–server, vai trò người dùng và ngân sách trình duyệt

Date: 2026-09-29

## Status

Accepted — Tech Lead / Integration Owner (Quân) chốt ngày 2026-09-29 sau thảo luận
thiết kế. Cần thông báo Product Owner (Cường, EX-PRODUCT) và QA/Validation Lead
(Đạt) vì quyết định chạm API, frontend, deployment và review.

## Context

- Studio MVP (ADR 0002) chạy được luồng video → 3DGS, nhưng API, worker, SQLite và
  artifact store phải nằm chung một máy; tắt máy GPU thuê là mất web và dữ liệu.
- Owner yêu cầu kiến trúc client–server ngay, không đợi sau MVP: UI host riêng,
  mọi xử lý nặng qua server của nhóm, GPU chỉ thuê khi cần; người dùng vẫn truy
  cập và dùng bình thường, trình duyệt chỉ gánh phần vừa sức, không lag.
- PRD v1.12/v1.14 khóa **direct browser rendering** của 3DGS (WebGL2 baseline,
  WebGPU khi có, WebGPU không bắt buộc) và PRD §3.4 khóa quyền Editor/Reviewer.
  `ARCHITECTURE.md` §Deployment Architecture đã mô tả target Browser → API →
  runtimes → store. Quyết định này cụ thể hóa target đó, không đổi PRD.
- Ràng buộc đồ án sinh viên: chi phí thấp, ít bảo trì, 4 ngày tới mốc MVP.

## Decision

### 1. Bốn khối và trách nhiệm

| Khối | Dịch vụ | Trách nhiệm | Không làm |
|---|---|---|---|
| A. Web UI | Vercel (Hobby) | Giao diện Next.js | Không xử lý dữ liệu, không để file lớn đi qua |
| B. Server điều khiển | Railway (Hobby): FastAPI + Postgres | Nguồn sự thật: API, đăng nhập, quyền, hàng đợi job, audit, cấp link file có hạn | Không chạy xử lý nặng |
| C. GPU worker | RunPod Pod (Community Cloud, RTX 3090/4090) | COLMAP, Brush, SOG, tạo bản nhẹ (LOD), ảnh bìa/video xoay, áp chỉnh sửa lên bản gốc | Không giữ dữ liệu lâu dài; tắt đi không mất gì |
| D. Kho file | Cloudflare R2 (S3 API) | Video gốc, frame, 3DGS, export | — |

- Upload: trình duyệt xin link tạm (presigned, multipart) rồi gửi **thẳng lên R2**.
- Tải scene/file: trình duyệt tải thẳng từ R2 bằng link có hạn, không qua UI/API.
- Worker nhận job, báo tiến trình và commit kết quả qua server điều khiển; mọi
  handoff vẫn là logical `artifact://` URI + SHA-256 như Contract hiện hành.
- GPU tự bật khi có job (RunPod API) và tự tắt khi rảnh (mặc định 10 phút).

### 2. Ngân sách trình duyệt

- Trình duyệt **không tải bản 3DGS gốc**. GPU tạo 2–3 mức (nhẹ / vừa / đầy đủ);
  bản đầy đủ chỉ dùng để export phía server.
- Client đo khả năng (WebGPU/WebGL2, bộ nhớ, mobile) để chọn mức; FPS tụt thì tự hạ.
- Chỉnh sửa: người dùng thao tác trên bản nhẹ; hướng lâu dài là gửi **lệnh** (vd:
  xóa vùng hộp, transform) để server áp lên bản gốc và tạo lại LOD. Trong lúc chưa
  có, giữ chỉnh sửa trong trình duyệt trên bản nhẹ (ADR 0002).
- Export do server tạo; trình duyệt chỉ nhận link tải.
- Khi job xong, GPU render sẵn ảnh bìa và video xoay quanh scene: dùng cho danh
  sách scene và làm fallback cho thiết bị không render được 3D. Không làm pixel
  streaming.

### 3. Vai trò và đăng nhập

Chỉ hai role theo PRD §3.4; Reviewer có mọi quyền của Editor, thêm quyền duyệt.

| Hành động | Khách (không đăng nhập) | Editor | Reviewer |
|---|:-:|:-:|:-:|
| Xem/thử video mẫu, editor trên scene mẫu (không lưu) | ✓ | ✓ | ✓ |
| Upload video, chạy job (trừ hạn mức) | ✗ | ✓ | ✓ |
| Xem project/scene của nhóm | ✗ | ✓ | ✓ |
| Chỉnh scene, thêm/xóa object/robot, kịch bản Isaac | ✗ | ✓ | ✓ (tạo revision mới) |
| Gửi duyệt | ✗ | ✓ | ✓ |
| Duyệt / từ chối (từ chối bắt buộc có lý do) | ✗ | ✗ | ✓ |
| Mời tài khoản, đổi role, chỉnh hạn mức | ✗ | ✗ | ✓ |

- Kỹ sư thực địa / người dùng thử không phải role thứ ba: khách dùng video mẫu
  (không tốn GPU); muốn upload thì cần tài khoản Editor.
- Không đăng ký tự do: tài khoản tạo qua mã mời do Reviewer phát, mỗi mã gắn role.
  Reviewer đầu tiên tạo bằng lệnh khi deploy.
- Đăng nhập tự làm trong FastAPI: `users`, `invites`, `audit_log` trong Postgres;
  mật khẩu băm; cookie phiên httpOnly. Backend kiểm quyền trên từng route (403);
  UI chỉ ẩn nút.
- Reviewer sửa scene tạo revision nháp, phải validation lại mới duyệt được.
  Tự duyệt scene của chính mình được phép nhưng gắn nhãn "tự duyệt" (PRD §3.4
  không bắt buộc hai tài khoản trong MVP).
- Không gian chung của nhóm: người đã đăng nhập thấy mọi project.

### 4. Tiết kiệm chi phí và vận hành

- Lọc trước khi tốn GPU: server kiểm nhanh video (`ffprobe`: định dạng, thời lượng,
  dung lượng) trước khi xếp hàng.
- Tái sử dụng kết quả: cùng checksum video + cùng checksum cấu hình thì trả kết quả cũ.
- Báo trước thời gian/tài nguyên (mô hình ước lượng sẵn có); hạn mức job/ngày và
  dung lượng theo tài khoản.
- Tự dọn: frame và file trung gian xóa sau N ngày; giữ video gốc, scene cuối, export.
- Docker image GPU đóng sẵn và ghim version COLMAP/Brush/splat-transform.
- Hạn mức chi tiêu trên RunPod; cảnh báo khi worker mất heartbeat; sao lưu Postgres.

### 5. Database

Chuyển runtime DB sang Postgres. Không thêm Alembic/SQLAlchemy: mở rộng cơ chế
`r2s_schema.version` hiện có thành chuỗi migration có thứ tự v1→v2→…, mỗi bước
chạy được trên SQLite (dev/test) và Postgres, trong transaction, không drop/reset;
version lạ vẫn bị từ chối.

### 6. Metric scale

Giữ nguyên ba hướng của ADR 0001 (RGB + LiDAR registered; RGB + chọn hai điểm A/B
và nhập số mét; RGB auto-estimate sau này). Trong kiến trúc mới: xử lý LiDAR/
registration và tính scale chạy ở worker; trình duyệt chỉ chọn điểm A/B trên bản
nhẹ và gửi lên server.

### 7. Fallback demo

Làm được đến đâu dùng đến đó. Nếu kiến trúc mới chưa ổn trước ngày demo, demo bằng
stack một máy GPU hiện có (`scripts/gpu/run_stack.sh`), vốn đã chạy thật.

## Alternatives Considered

1. Render trên server (pixel streaming): mỗi người xem chiếm một phiên GPU, trễ theo
   mạng, chi phí theo số người xem; trái PRD direct browser rendering. Loại, chỉ giữ
   video xoay quanh scene làm fallback.
2. RunPod Serverless: scale-to-zero sẵn nhưng $0.69–1.10/giờ so với Pod
   $0.22–0.34/giờ (giá 2026-09-29); Pod + tự bật/tắt rẻ hơn cho lưu lượng thấp.
3. AWS S3: tính phí egress; R2 miễn phí egress và 10 GB đầu.
4. Dịch vụ đăng nhập ngoài (Clerk/Auth0/Supabase): thêm phụ thuộc cho nhu cầu hai
   role đơn giản.
5. VPS tự quản (vd: Hetzner): rẻ hơn nhưng tốn công vận hành, sao lưu, bảo mật.

## Consequences

Positive:

- Web và dữ liệu sống độc lập với máy GPU; GPU chỉ tốn tiền khi có job.
- Trình duyệt tải bản nhẹ nên máy yếu vẫn dùng được; máy không render nổi có video.
- Chi phí ước tính ~$10–20/tháng (INFERENCE: Railway $5–10, R2 ~$0 trong 10 GB,
  GPU ~$0.1/job giả định 15–20 phút trên 4090 — chưa đo trên RunPod).

Tradeoffs / risks:

- **COLMAP đang chạy qua Docker; pod RunPod không chạy Docker lồng** → phải cài
  COLMAP trực tiếp vào image.
- **Brush và nén SOG cần Vulkan trong container** → phải kiểm trên pod thật trước.
- LOD: chưa xác minh `splat-transform` có sẵn bước giảm Gaussian (UNKNOWN).
- Lấy danh sách thao tác chỉnh sửa từ SuperSplat để gửi lệnh: UNKNOWN, rủi ro cao.
- Phụ thuộc ba nhà cung cấp; giữ S3 API và Postgres chuẩn để dễ đổi.

## Follow-Up

- Plan triển khai: `docs/plans/active/2026-09-29-cloud-studio.md`.
- Cập nhật `ARCHITECTURE.md` (Deployment, Auth, Database) và PRD §3.4 (khách).
- Thông báo Cường/Đạt; các task PRODUCT liên quan cập nhật theo.
