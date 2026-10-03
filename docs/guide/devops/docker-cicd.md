---
title: "Docker & CI/CD"
description: "Setup Docker và GitHub Actions"
weight: 1
---

> **Phạm vi:** Các Dockerfile và service trong phần code block là ví dụ generic
> cho template AI20K. Với Real2Sim Studio P-087, image API/control-plane là
> `Dockerfile`, Compose canonical là `docker-compose.yml`, GPU override là
> `docker-compose.gpu.yml`, và dependencies được cài từ lockfiles. Xem
> `README.md`/`docs/guide/studio-distribution.md` trước khi chạy stack thật.

## Docker

### Multi-stage Dockerfile

```dockerfile
# Stage 1: Build
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Production
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
COPY . .
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Commands

```bash
docker build -t ai20k-app .
docker compose up -d
docker compose logs -f backend
docker compose down
```

## CI/CD (GitHub Actions)

CI tự chạy khi push lên GitHub:

1. **Lint** — `ruff check` đảm bảo code style
2. **Test** — `pytest` chạy tất cả tests
3. Pass → merge được. Fail → fix trước.

### Setup CI

File `.github/workflows/ci.yml` đã có sẵn trong template.

### Yêu cầu minimum

- ✅ CI pipeline phải chạy được
- ✅ Ruff lint pass
- ✅ Tất cả tests pass

## Environment Variables

```bash
# .env.example — commit được (template)
# .env — KHÔNG BAO GIỜ commit (actual values)
```

## Git Workflow

```
main (production)
  └── develop (daily work)
       ├── feature/agent-flow
       ├── feature/api-routes
       └── feature/ui
```

### Commit Messages

```
feat: thêm agent graph với nodes analyze + respond
fix: sửa lỗi CORS blocked trên frontend
docs: cập nhật architecture diagram
test: thêm test cho chat endpoint
refactor: tách analyze node thành file riêng
```
