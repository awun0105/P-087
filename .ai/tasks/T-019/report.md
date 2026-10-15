# T-019 — Full regression, deep review và handoff

Ngày: 2026-10-16. Branch: `mvp-pipeline-v2`. Baseline HEAD: `69611ea9c117b537cf4b90672565123400b666d1`.

## Outcome

Đã bổ sung test public simulation package cho scene shell; sửa palette regression và guard ngăn partial build trên Draft;
viết [deep review](review.md) và [handoff](../../../docs/plans/active/2026-10-16-geometry-review/HANDOFF.md).

Review còn **2 P1 và 4 P2**, có source, probe, tác động, hướng sửa và acceptance test. GR-01/GR-02 cần xử lý trước nghiệm thu
scene thật. Không tuyên bố production/GPU/browser/Isaac pass. Task ở `implemented`, chờ review; không tự đặt `accepted`.
Full backend baseline có 1 failure đã sửa và kiểm lại. Performance gate ở focused runs vẫn chưa ổn định và được giữ mở.

## Thay đổi thực tế

- `src/services/orchestration/scene/object_geometry_build.py`: từ chối `object_ids` trên Draft trước khi tạo artifact; chỉ
  partial rebuild trên Ready. Không thay cách dựng mesh, quality gate, mass hoặc tham số provider.
- `frontend/src/features/viewer/region-overlay.ts`, `shell-glow.ts`: đọc màu qua `themeColor` và palette token, có fallback.
- `tests/test_scene/test_object_geometry_build.py`: Gaussian fixture đủ field và visual PLY local thực; thêm test partial
  Draft bị từ chối mà head/artifact không đổi.
- `tests/test_scene/test_shell_geometry_walk_usd.py`: Draft → build CoACD thật → Confirm một vật, giữ một ứng viên → public
  package builder/USD runtime thật → kiểm collider/shell inventory, checksum và cache không sinh revision thừa.
- `.ai/tasks/T-019/plan.md`, `review.md`, `report.md`, `evidence/`, `.ai/status.md`: bổ sung phạm vi review, kết quả và chứng cứ.
- `docs/plans/active/2026-10-16-geometry-review/HANDOFF.md`: bàn giao mới; handoff membership-correction cũ thêm mục
  “Superseded by geometry review”.

Không thay các file `tasks/CFG*`, `tasks/reports/*`, `BRAINSTORM.md`, `MASTER_PITCH.md` đã có thay đổi trước task. Không tạo
commit, không stage, không đổi branch/push/merge/PR. Giữ nguyên HEAD.

## Verification

### Full regression

| Lệnh | Kết quả |
| --- | --- |
| `.venv/bin/python -m pytest tests -q` | Baseline: **1 failed, 3502 passed, 28 skipped**, 15 warnings, 1433,17 s. Failure partial Draft đã sửa; 2 regression guard trên source cuối PASS |
| `.venv/bin/ruff check src tests scripts` | PASS — All checks passed |
| `.venv/bin/ruff format --check src tests scripts` | PASS — 746 files already formatted |
| `.venv/bin/python scripts/check_contract_mirror.py` | PASS — 5 enum, 8 model, không nới union thành string |
| `cd frontend && ./node_modules/.bin/vitest run` | Lần đầu: 3 failed, 836 passed. Sau sửa palette: 80 files, **839 passed**, 78,87 s |
| `cd frontend && npm run typecheck` | PASS sau sửa |
| `cd frontend && npm run lint` | PASS exit 0; 0 errors, 7 warnings ở file không sửa |

[Full backend baseline](evidence/backend.txt), [full frontend cuối](evidence/frontend.txt), [frontend lần đầu](evidence/frontend-initial.txt),
[static checks](evidence/static-checks.txt).

[Chỉ mục evidence và script tái hiện](evidence/README.md). Markdown links/fences và `git diff --check` cuối PASS; toàn bộ
status row có trước task vẫn được giữ. Branch/HEAD cuối trùng baseline.

Full backend được khởi chạy trên baseline trước khi sửa source/fixture. Những thay đổi sau đó được kiểm lại bằng focused
suites ở dưới; không gộp số test hai lần chạy thành số full-suite pass. Không chạy lại toàn bộ backend sau guard hai dòng;
đã kiểm lại builder, queue/regeneration/API, guard shell/ObjectGS và public package. Không gọi backend full suite cuối là xanh.
28 skip là skip của lần chạy này, không được cộng vào pass. 15 warning là deprecation của httpx ở test error-view.

### Focused và chẩn đoán

```bash
.venv/bin/python -m pytest \
  tests/test_scene/test_object_geometry_build.py \
  tests/test_scene/test_object_geometry_build_objectgs.py \
  tests/test_scene/test_object_region.py \
  tests/test_scene/test_shell_geometry_walk_usd.py -q
```

Lần đầu sau sửa fixture: **2 failed, 88 passed**, 381,42 s. Test package mới PASS; failure là guard partial Draft chưa có
và budget preview 300k = 1,563 s. [Log](evidence/geometry-initial.txt).

```bash
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py \
  tests/test_scene/test_object_geometry_build_objectgs.py tests/test_scene/test_object_region.py \
  -q -k 'not real_coacd'
```

Sau thêm guard/new regression: **1 failed, 81 passed, 2 deselected**, 150,79 s. Guard shell và test ObjectGS partial Draft
đều PASS; failure còn lại là preview 300k = 1,620 s. Hai case CoACD thật bị `-k` loại đã PASS trong lượt 90 test ở trên;
không báo hai case này là được chạy trong lượt recheck.

```bash
.venv/bin/python -m pytest tests/test_orchestration/test_scene_objectify_queue.py \
  tests/test_scene/test_membership_regeneration.py tests/test_api/test_scene_v2_routes.py \
  tests/test_api/test_role_matrix.py -q
```

**116 passed**, 38,26 s. Lần gọi trước nhầm queue path ở `tests/test_scene` không collect được test; đã sửa sang đường dẫn
trên và chạy lại, không tính lần “no tests ran” là pass.

- Chạy riêng `test_reviewed_shell_scene_builds_a_sealed_simulation_package -v` trên source cuối: **1 passed**, 47,65 s.
  [Log package](evidence/package.txt).
- Hai regression guard chạy riêng trên source cuối: **2 passed**, 2,06 s; [log](evidence/draft-guard.txt).
- Palette/region-overlay/shell-glow: **68 passed** sau sửa; full frontend cuối cũng kiểm lại toàn bộ.
- Recheck 3 file frontend từng fail: region-editor + unified-input-flow pass; palette vẫn fail trước khi sửa token.
- Preview 300k chạy riêng: **1 failed**, 1,873 s > 1,5 s. Giữ GR-05; không tăng threshold hoặc bỏ assertion.
- Probe reopen/claim/ignored-shell: **3 passed** trong 12,73 s để xác nhận lỗi; probe inpaint cô lập: **1 passed** trong 5,93 s
  xác nhận preflight FAIL rồi PASS khi count được sửa trong bản sao. Đây là probe hành vi lỗi, không phải fix đã pass.
- Preview 2M: 2 lượt cold/warm và profile; cold 3,5–7,0 s, warm 1,57–2,16 s; counts đúng, shell ≤100k hàng, QA pass. Floor
  fit bị stub, layout 7-field, BLAS/OMP 1 thread; máy có workload đồng thời. Xem GR-05 về phạm vi số đo.
- SuperSplat vendor không đổi trong task. `frontend/public/editor/index.html` mtime 15/10 17:12, sau source-selection 15:31;
  không rebuild editor. Đây là kiểm tra artifact local, không xác minh bản editor đang deploy.
- `git diff --check`: PASS tại các checkpoint; kiểm lại trước bàn giao.
- `graphify update .`: PASS exit 0 sau guard — 25.574 nodes, 79.508 edges, 832 communities. Output local bị gitignore theo
  repo. Có cảnh báo community labels đổi và file không có symbol; không gọi LLM label hoặc API semantic extraction.

### Giới hạn evidence

Test package có Gaussian PLY/artifact/SceneIR thật và CoACD/OpenUSD local thật. SAM2, GPU ObjectGS, inpaint và SOG codec vẫn
là test double trong fixture này; inpaint fixture chính thêm 0 hàng. Vì vậy test package xanh không phủ GR-01.

Chrome DevTools kết nối thành công, `list_pages` chỉ có `about:blank`. Không có phiên Studio đăng nhập, không chạy thao tác
box/Walk và không xác minh màu sau thay token. Không mở Isaac Sim. Không train capture mới.

## Lệch plan và lý do

1. Thêm deep review + benchmark 2M theo yêu cầu trực tiếp của người dùng. Các finding ngoài regression ghi backlog có
   acceptance trong review, chưa triển khai hàng loạt.
2. Test package mới ban đầu lộ fixture `visual_ref` chứa bytes placeholder và thiếu trường quaternion/scale/DC. Sửa fixture
   dùng layout Gaussian và PLY local hợp lệ; giữ validator/exporter nghiêm, giữ case có ứng viên chưa Confirm.
3. Sửa thêm guard service vì test existing fail ổn định và có thể publish Ready sai. Không thay test cũ sang mong đợi lỗi đó.
4. Giữ failure hiệu năng và số đo thật, không quy hết thành flaky. Hai frontend failure do timing pass ở rerun, được ghi
   riêng với palette regression đã sửa.
5. Không commit theo mục Commit trong plan vì chưa có yêu cầu Git tường minh; áp dụng giới hạn Git của AGENTS.md.
6. `.ai/architecture.md` §12 còn ghi full suite ở T-018; plan T-019, `.ai/README.md` và task người dùng giao đặt việc này ở
   T-019. Dùng phạm vi task cụ thể hiện tại, không sửa kiến trúc hoặc chạy thêm full suite trong task khác.

## Gate report

Pre-flight (GUIDE.md Rule 13)

- **codegraph:** đọc `build_object_geometry`, helper inpaint/CoACD, region resolution/apply, membership loader,
  representation integrity, queue process/request, package builder, RegionEditor/session/preview, overlay/shell và fixture.
- **impact:** builder được gọi từ queue geometry, region Ready rebuild, membership regeneration và focused tests. Overlay/
  ShellGlowLayer dùng bởi MetricSceneView; không đổi exported API. Fixture dùng bởi geometry, ObjectGS, region và Walk/USD.
- **understand:** immutable source rows → Draft region review → full build/partial Ready → background representation →
  Walk/USD. Ngữ cảnh lấy từ authority docs và source; không thay quyết định product hoặc provider.
- **minimal-code:** rung 2 — tái dùng `object_geometry_state` cho guard và `themeColor` cho màu; không thêm abstraction.
- **checks:** ruff check/format + mirror + TypeScript + eslint PASS; full Vitest 839 passed; backend/focused kết quả cụ thể
  ở trên. Còn performance gate GR-05. `npm run typecheck` là lệnh typegen + tsc của repo.
- **DevTools:** **UNVERIFIED — không có phiên Studio đăng nhập**; MCP có kết nối, chỉ `about:blank`. Đã dùng skill
  [chrome-devtools](/home/lqaq/.agents/skills/chrome-devtools/SKILL.md). Không tuyên bố UI acceptance.

## Còn lại

- GR-01/GR-02 trước nghiệm thu scene mới; GR-03..GR-06 có hướng sửa/test trong review.
- GPU mask/training quality, browser region/cancel/reload, memory/latency SH đầy đủ, Isaac physics/Walk feel.
- Dọn `objectify(correction=…)` và inventory trùng ref ở task riêng; không xoá trong T-019.
- T-019 chờ Architect/owner review; không tự đặt `accepted`.
