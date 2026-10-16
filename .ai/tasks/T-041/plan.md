# T-041: Deploy production thử trọn một lần và ghi lại mọi chỗ vấp

## Goal
Chạy đủ 8 bước của `deploy/studio/OVERVIEW.md` trên hạ tầng thật một lần: Supabase (PostgreSQL), Cloudflare R2,
Railway (API), Vercel (Studio), GPU thuê dùng image của T-039. Kết quả: một Studio production dùng được, 5 scene mẫu có
trên đó, một job mới chạy từ upload tới thẻ Giá trị, và tài liệu deploy sửa theo đúng những gì đã vấp.

## Context
- Tài liệu: `deploy/studio/OVERVIEW.md` (thứ tự và chỗ dễ vấp), `deploy/studio/README.md` (chi tiết từng nhà cung cấp,
  import gói đã kiểm vào production, tạo Reviewer đầu tiên), `deploy/studio/production.env.example` (một file gốc),
  `python -m scripts.studio.deploy_env check/render`.
- Chưa từng chạy thật: PostgreSQL thật (ghi chú T-035: nhánh PostgreSQL của ground truth T-030 mới có test), R2 thật,
  Railway, Vercel, đo RAM/CPU theo giới hạn container trên pod (AUD-26.S4).
- Sau T-040 không còn bước chép manifest tay.
- Isaac validation (L3) **ngoài phạm vi**: scene production tối đa L2 ở lần này.

## Cần chủ dự án làm/duyệt (agent không tự tạo tài khoản, không tự trả tiền)
1. Tài khoản và project: Supabase, Cloudflare (R2 + Pages), Railway, Vercel, Vast.ai; quyền cho agent qua CLI/token
   **chỉ trong phiên**, không ghi vào repo.
2. Ngân sách tối đa cho lần thử (Railway, Vercel thường miễn phí ở mức này; GPU theo giờ). Agent báo trước mỗi bước tốn
   tiền.
3. Tên miền (nếu có) và origin chính thức để đặt CORS R2 và cookie.
4. Trọng số EgoBlur: chủ dự án đã có file; agent chạy `scripts.gpu.egoblur_weights upload` khi được đồng ý. Không có thì
   giữ `PRODUCT_PRIVACY_MODE=self_attested`.
5. Danh sách scene được phép công khai trong thư viện mẫu (5 scene trong `data/demo/library`).

## Steps
1. **Chuẩn bị file gốc** ngoài repo (`/secure/production.env` hoặc thư mục tạm của phiên), điền từ tài khoản ở trên;
   `deploy_env check` sạch. Ghi vào report từng lỗi `check` báo và cách đã sửa (không ghi giá trị).
2. **Supabase + R2.** Tạo DB, chạy migration bằng đường chính thức (API khởi động lần đầu, hoặc lệnh trong README). Kiểm
   `schema_version` = `LATEST_SCHEMA_VERSION`. R2: bucket, CORS đúng origin (`GET`, `HEAD`, `PUT`, expose `ETag`).
3. **Chạy test PostgreSQL thật.** Fixture `runtime_database_url` (`tests/test_orchestration/conftest.py`) tạo và xoá
   database cho từng test, cần quyền `CREATE DATABASE` mà Supabase không cấp. Vì vậy chạy trên một PostgreSQL **cục bộ
   cùng phiên bản lớn với Supabase** (đọc phiên bản trong dashboard), ví dụ `docker run -d --rm -p 15432:5432
   -e POSTGRES_PASSWORD=<tạm> postgres:<bản>`, rồi
   `R2S_TEST_POSTGRES_URL=postgresql://postgres:<tạm>@127.0.0.1:15432/postgres .venv/bin/python -m pytest tests -q -k postgres`.
   Ghi số pass/skip/fail; đặc biệt các test ground truth T-030 và migration. Tắt container sau khi xong. Trên Supabase
   chỉ kiểm migration chạy hết và `schema_version` đúng. Lỗi → task sửa riêng, không vá trong T-041.
4. **GPU worker.** Thuê pod theo digest image T-039, nạp `worker.env`, chế độ `worker`. Kiểm worker đã công bố runtime
   (T-040) và `preflight` PASS.
5. **API trên Railway.** Volume, `api.env`, deploy, `/health` 200. Tạo Reviewer đầu tiên.
6. **Studio trên Vercel** (`REAL2SIM_API_URL`), build `npm run build:editor && npm run build`. Đăng nhập được, cookie
   giữ qua `/api/v1/*`.
7. **Landing** lên Cloudflare Pages (nếu chủ dự án muốn ở lần này).
8. **Dữ liệu mẫu.** Import 5 scene của `data/demo/library` theo mục "Importing a verified package into production"
   của README. Mở từng scene trên Studio production: preview, Walk, thẻ Giá trị đọc được.
9. **Job thật.** Upload `Aisle_CW_0_1091__left.mp4`, chạy tới object geometry ready, Walk, mở panel Benchmark nhập một
   đoạn thước và một khe giả định, xem thẻ Giá trị và `/benchmark`, tải CSV. Ghi thời gian từng bước và chi phí GPU.
10. **Thử đổi pod.** Trả pod, thuê pod GPU **khác loại**, không đụng API: job mới phải chạy (kiểm T-040).
11. **Dọn**: tắt pod GPU. Giữ hay tắt Railway/Vercel/Supabase do chủ dự án quyết.
12. **Tài liệu.** Sửa `OVERVIEW.md`, `README.md`, `production.env.example` theo mọi chỗ vấp thật; thêm mục "Đã deploy thử
    ngày …" với phiên bản, digest image, chi phí và thời gian từng bước. Commit.

## Acceptance criteria
1. Studio production mở được, đăng nhập được, 5 scene mẫu xem được.
2. Một job mới chạy từ upload tới object geometry ready trên GPU thuê, thẻ Giá trị có phút máy, phần cứng, chi phí.
3. Đổi pod khác loại GPU không cần sửa API.
4. Test PostgreSQL thật đã chạy, số thật trong report.
5. Tài liệu deploy khớp với những gì đã làm; không còn bước nào chỉ có trong đầu người làm.
6. Không secret nào trong repo, report hay log commit.

## Tests required
Bước 3 (PostgreSQL thật). Còn lại là kiểm tay theo Steps, ghi output vào report.

## Commit
Commit tài liệu; commit report + status. Bản sửa code phát hiện trong lúc deploy: mỗi lỗi một task riêng do Architect
lập, trừ sửa tài liệu/ví dụ env. Không Co-Authored-By.
Cần T-039 và T-040 accepted.
