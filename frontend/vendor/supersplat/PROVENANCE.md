# SuperSplat vendor copy

- Upstream: https://github.com/playcanvas/supersplat
- Version: 3.4.2, commit `f76e676` (copy nguyên source, bỏ `.git`, `.github`, `renovate.json`)
- License: MIT (xem `LICENSE`, giữ nguyên notice)
- Lý do: Studio MVP nhúng editor Gaussian (chọn/xóa/di chuyển/đo/export) thay vì viết lại.
- Mọi chỉnh sửa cho Real2Sim nằm ở các commit riêng sau commit vendor gốc; xem
  `git log -- frontend/vendor/supersplat`.
- Build: `npm run build:editor` trong `frontend/` → `frontend/public/editor/` (không commit output).
