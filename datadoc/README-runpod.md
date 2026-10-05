# Hướng Dẫn Chạy Gói Data & Web Studio Trên RunPod

> File này tóm tắt cách dùng gói dữ liệu `r2s-studio-data.zip` trên máy chủ **Cloud GPU (RunPod)** thay vì chạy Docker cục bộ trên máy tính cá nhân.
> Chi tiết đầy đủ xem tại: [`docs/RUNPOD_GUIDE.md`](../docs/RUNPOD_GUIDE.md).

---

## Điểm Khác Biệt Quan Trọng So Với `README-team.md` (Docker Cục Bộ)

1. **Không chạy `docker compose`:**
   Trong Pod của RunPod không có Docker daemon (`dockerd`). Bạn không cần chạy Docker Compose.
   
2. **Bung dữ liệu trực tiếp bằng Python:**
   Dữ liệu `r2s-studio-data.zip` được giải nén trực tiếp bằng thư viện chuẩn Python trong 5 giây:
   ```bash
   python scripts/studio/data_package.py --root . unpack r2s-studio-data.zip
   ```

3. **Tải file trực tiếp lên RunPod (Không tốn mạng máy cá nhân):**
   ```bash
   pip install gdown
   gdown "https://drive.google.com/drive/folders/1NqZmn3iJO6UuA4YCPq295jwMNMXDdr-f" --folder -O /workspace/real2sim/
   ```

4. **Khởi động ứng dụng trực tiếp:**
   ```bash
   # Terminal 1: Backend API
   source .venv/bin/activate
   uvicorn src.main:app --host 0.0.0.0 --port 8000

   # Terminal 2: Web Studio
   cd frontend && npm run dev -- -p 3000
   ```

5. **Kết nối và mở Web từ Laptop:**
   - Kết nối vào RunPod bằng extension **VS Code Remote - SSH**.
   - Dùng tab **PORTS** trong VS Code để forward cổng **`3000`** và **`8000`**.
   - Mở trình duyệt trên máy bạn: `http://localhost:3000`.
   - Đăng nhập tài khoản Reviewer: `reviewer@real2sim.com` / `password12345`.
