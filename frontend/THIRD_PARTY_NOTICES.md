# PlayCanvas / SuperSplat integration

`src/features/viewer/inspection-history.ts` adapts the FIFO command queue and
history cursor discipline from `playcanvas/supersplat` (commit `f76e676`,
`src/command-queue.ts`, `src/edit-history.ts`). The inspection controller follows
the two-point measurement interaction of `src/tools/measure-tool.ts`, but does
not copy its local rescaling behavior: Real2Sim metric confirmation belongs to
the backend. PlayCanvas `Picker` and `supersplat-viewer` are used via their pinned
library APIs; renderer/selection algorithms are not reimplemented here.

Upstream: https://github.com/playcanvas/supersplat

Copyright (c) 2011-2026 PlayCanvas Ltd.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

## Vendored SuperSplat editor

`vendor/supersplat/` là bản copy của `playcanvas/supersplat` v3.4.2 (commit
`f76e676`) theo MIT License ở trên, được build thành `public/editor/` và nhúng
vào Studio. Chi tiết nguồn gốc và chỉnh sửa: `vendor/supersplat/PROVENANCE.md`.

## next-shadcn-admin-dashboard (UI nền Studio)

Component `src/components/shadcn/*`, hook `src/hooks/use-mobile.ts` (viết lại) và khung
sidebar/header của `src/features/shell/` lấy từ
[`arhamkhnz/next-shadcn-admin-dashboard`](https://github.com/arhamkhnz/next-shadcn-admin-dashboard)
commit `3502692` (2026-09-28), MIT License — Copyright (c) 2024 Mohammed Arham Khan. Đã đổi đường
dẫn import và theme; không chép các trang domain mẫu (PRODUCT.md §3.2).

`src/styles/shadcn-variants.css` chép từ gói npm `shadcn@4.21.0` (`dist/tailwind.css`), MIT License.
Dependency thêm: `radix-ui@1.6.7` (MIT), `tw-animate-css@1.4.0` (MIT).

`@rerun-io/web-viewer-react@0.24.1` + `@rerun-io/web-viewer@0.24.1` (MIT OR Apache-2.0, © Rerun Technologies AB):
viewer Rerun nhúng cho chế độ xem "Quá trình train" của bước 3DGS. Ghim đúng 0.24.1 vì phải khớp SDK Rerun mà
Brush 0.3.0 nhúng.
