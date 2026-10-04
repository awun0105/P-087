# Hướng Dẫn Cấu Hình & Sử Dụng AI Usage Logging (Deliverable #4)

> **Dành cho thành viên Team P-087 — VinUni AI20K Build Phase**

---

## 1. Mục đích của AI Usage Logging là gì?

Hệ thống ghi nhận AI Log là **yêu cầu bắt buộc của khóa học AI20K Build Phase**:
* **Deliverable #4 (AI Logs & Traces)**: BTC và Hội đồng chấm thi sử dụng dữ liệu này để đánh giá tính minh bạch, kỹ năng prompt, workflow làm việc với AI assistants và mức độ đóng góp cá nhân (**PLO8 - AI Coding & Teamwork**).
* **Cơ chế hoạt động**:
  1. Khi bạn tương tác với các công cụ AI (Antigravity, Claude Code, Cursor, Copilot, Gemini CLI...), prompt và metadata tự động được ghi vào file `.ai-log/session.jsonl` trên máy bạn.
  2. Mỗi khi bạn thực hiện `git push` lên GitHub repo của đội, git hook `pre-push` sẽ tự động quét và gửi các log này lên **Phoenix Grading Server**.

---

## 2. Các bước thiết lập cho từng thành viên (1 lần duy nhất)

Mỗi thành viên khi clone repo về máy local của mình cần thực hiện các bước sau:

### Bước 1: Lấy `AI_LOG_API_KEY` cá nhân
1. Truy cập vào dashboard của khoá học: **<https://phoenix.note.transformerlabs.ai/api-keys>**
2. Đăng nhập bằng tài khoản GitHub (chính là tài khoản GitHub đã được mời vào organization của lớp).
3. Sao chép API key cá nhân của bạn (dạng chuỗi ký tự bảo mật).

### Bước 2: Điền vào file `.env`
1. Nếu chưa có file `.env`, hãy copy từ `.env.example`:
   ```bash
   cp .env.example .env    # Linux / macOS
   copy .env.example .env  # Windows CMD
   Copy-Item .env.example .env # Windows PowerShell
   ```
2. Mở file `.env` và thay thế giá trị:
   ```env
   AI_LOG_SERVER=https://ai-logs.note.transformerlabs.ai/api/ingest
   AI_LOG_API_KEY=phx_your_personal_key_here
   AI_LOG_DIR=.ai-log
   ```
   > ⚠️ **Lưu ý:** File `.env` đã được đưa vào `.gitignore`. Không bao giờ commit file `.env` lên GitHub!

### Bước 3: Cài đặt Git Pre-Push Hook

* **Trên Windows PowerShell**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\setup_hooks.ps1
  ```

* **Trên macOS / Linux / Git Bash**:
  ```bash
  bash scripts/setup_hooks.sh
  ```

* **Kết quả mong đợi**:
  ```text
  [ai-log] Git pre-push hook installed.
  [ai-log] Setup complete. Configure AI_LOG_SERVER in your .env file.
  ```

---

## 3. Cách ghi log khi sử dụng các công cụ khác nhau

### A. Tự động (Không cần thao tác gì thêm)
Template đã tích hợp sẵn cấu hình hook tự động cho 6 công cụ:
* **Antigravity IDE**: Tự động quét transcript hội thoại khi `git push`.
* **Claude Code**: Tự động hook qua `.claude/settings.json`.
* **Cursor**: Tự động hook qua `.cursor/hooks.json`.
* **GitHub Copilot**: Tự động hook qua `.github/hooks/hooks.json`.
* **OpenAI Codex CLI**: Tự động hook qua `.codex/hooks.json`.
* **Gemini CLI**: Tự động hook qua `.gemini/settings.json`.

### B. Ghi log thủ công (Dành cho ChatGPT Web, Claude.ai, Gemini Web)
Nếu bạn thảo luận kiến trúc, brainstorm prompt hoặc giải thuật trên giao diện Web:
```bash
# Cú pháp ngắn gọn:
python scripts/log_manual.py --tool chatgpt --prompt "Thảo luận thuật toán tách cụm 3DGS với SAM2"
python scripts/log_manual.py --tool claude-web --prompt "Soạn thảo schema trạng thái LangGraph cho Scene Audit"
```

---

## 4. Kiểm tra và xác nhận hệ thống hoạt động

1. **Kiểm tra file log local**:
   Xem file `.ai-log/session.jsonl` — bạn sẽ thấy các dòng JSON chứa thông tin prompt, model, timestamp và email tác giả.
2. **Kiểm tra khi push**:
   Khi bạn commit và gõ `git push origin develop`, terminal sẽ xuất hiện thông báo:
   ```text
   [ai-log] Submitted X entries → 200
   ```
   Nếu máy bạn chưa có mạng hoặc server bảo trì, log sẽ được lưu an toàn tại local và tự động gửi lại vào lần push tiếp theo mà không làm gián đoạn việc push code của bạn.

