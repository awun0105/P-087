# Handoff — EX-REC coordinate audit (opencode → Codex)

| | |
| --- | --- |
| **Ngày** | 2026-09-27 |
| **Giờ** | 09:49 – 10:47 (+07) |
| **Tác giả commit** | Lâm Quang Anh Quân `<quanlam0105@gmail.com>` |
| **Agent thực hiện** | opencode, làm theo yêu cầu owner trong phiên chat |
| **Track** | EX-REC — `@awun0105` (track owner) |
| **Branch** | `feat/ex-rec-pipeline` |
| **Base commit trước phiên** | `45db57e` |
| **4 commit phân tích** | `c1fe3f6` → `5713976` |
| **Commit của chính file handoff này** | commit kế tiếp sau `5713976`, docs-only |
| **Phạm vi** | Read + audit + chạy real tool. **Không sửa code.** Không push/merge/đổi branch. |

## Mốc thời gian trong phiên

| Giờ | Việc | Commit |
| --- | --- | --- |
| 09:45 | Chạy prefusion 20 scan (frame 100–119) | — |
| 09:46 | Xác minh checksum, replay byte-identical | — |
| 09:49 | Ghi evidence REC-07 + plan | `c1fe3f6` |
| 10:00 | Chốt up-axis 2 phép đo; ghi lỗ hổng camera chain | `a713d7e` |
| 10:20 | Tra dataset repo local, tìm ra nguyên nhân (ảnh đã undistorted) | — |
| 10:29 | Giải camera chain; chốt up-axis 3 nguồn | `4078686` |
| 10:37 | Owner chốt handedness | `5713976` |
| 10:47 | Viết handoff này | commit của file này |

## Nguồn của các quyết định trong phiên

| Nội dung | Ai quyết |
| --- | --- |
| Chạy prefusion 20 frame thay 5 frame | **Owner** yêu cầu |
| Up-axis = +Z, đơn vị = mét | Agent đo, **owner review** |
| `image_left/*.png` đã undistorted | Agent đo và chứng minh bằng 11 frame |
| Ouster OS1-128 thuận tay, không đảo trục | **Owner xác nhận** (không phải agent verify) |
| Giữ nguyên `Status` các task, không nâng | Agent, theo harness lifecycle |

> **Đây là snapshot một lần, KHÔNG phải nguồn status sống.** Trạng thái chính
> thứ vẫn nằm ở `tasks/REC-*.md` (mục `Status` + `Result/Evidence`) và
> `docs/plans/active/2026-09-24-ex-rec-track.md`. Khi hai chỗ lệch nhau, hai chỗ
> đó thắng. File này chỉ để một agent mới nắm nhanh bối cảnh phiên vừa rồi.

## 0. Trạng thái repo lúc bàn giao

### Owner instruction mới nhất — hoàn thành EX-REC trước integration

- Tiếp tục EX-REC trên `feat/ex-rec-pipeline`; **chưa làm integration UI/backend**.
- Khi EX-REC hoàn thành: merge nhánh pipeline vào `feat/ex-rec`, verify commits/
  thay đổi đã được giữ, rồi xóa `feat/ex-rec-pipeline` (không force-delete unmerged).
- Sau đó mới tạo nhánh integration **từ `feat/ex-rec`** và ghép EX-PRODUCT.
  Không dùng đề xuất trước đó tạo integration trực tiếp từ pipeline branch.
- Test REC+PRODUCT local trước; owner thuê Vast.ai/SSH nếu local không đáp ứng.
  EX-SCENE/EX-SIM integration ở giai đoạn sau; shared artifact contracts vẫn phải
  được giữ ngay từ bây giờ. Không tự push, thuê cloud hoặc claim DONE để mở merge.

### Recovery checkpoint — canonical visual + preview + metric bundle bridge

Branch vẫn `feat/ex-rec-pipeline`; không push/merge/switch. Commits đã tạo:
`04bdf63` job identity guard → `2b2da87` canonical Gaussian PLY/SOG publication
→ `427ab83` prepared preview worker + attempt namespace → `a6e40c8` final RGB
metric bridge cùng REC-06/10 evidence. Combined bridge/preview/REC-10/11 regression
**64 passed (137.11s)**; Ruff EX-REC source/tests **104 files pass**, AST limits pass.
Full EX-REC native CPU rerun (REC05_TEST_GPU=0) còn chạy tại checkpoint này; chưa
ghi kết quả cuối hoặc claim whole track green. Không có heavy training đang chạy.

**Đã triển khai:**
- Canonical visual consumer kiểm exact confirmation/pose/raw-master lineage,
  full s/R/t, native codec inventory; SOG ref trỏ bytes thật, không trỏ manifest JSON.
- Prepared preview CLI chạy REC-03→04 với pinned runtime qua env settings;
  giữ cùng job, mỗi retry là attempt mới, request/events/result create-only.
  Kết quả preview complete vẫn `job_status=RUNNING`, metric `UNCONFIRMED`.
  Không có full video/InputManifest dispatcher hoặc PRODUCT queue wiring yet.
- `BundleMetricVerifier` ghép canonical visual loader + canonical poses + geometry
  GLB/provenance + independent measurement/tolerance với exact reviewed bundle.
  Default deployment scope product, no default review authority; fixture mode
  chỉ composition test chủ động. Record immutable và authority rechecked lúc load.
  `verify_bundle` là port cho REC-10, không là physics/Isaac acceptance.
  Chưa wire authenticated reviewer vào bundle CLI (thuộc PRODUCT integration).
- Một fixture chain chạy producer→canonical artifacts→metric proof→REC-10 bundle
  →EX-SCENE consumer, không remap output refs hoặc sửa bundle bằng tay. Stub
  COLMAP/Brush/voxel/authority được ghi rõ; không gọi đó là real-data acceptance.

**Next executable work, không lặp lại phần đã làm:**
1. REC-05 strict seed/capsule occupancy validation. Đã đọc pinned native
   `carve` 3.6.6/afbc281: blocked seed được `findNearestFreeCell` và **không có log
   relocation thành công**, nên thêm regex vào `require_carve` không giải quyết.
   Cần validate seed trên cùng pre-carve occupancy/rounded dilation kernel hoặc
   controlled upstream adapter; không vendor/patch generated npm bundle.
2. REC-05 publication/retry: `GeometryPublisher` vẫn fixed job/rec05 URI và mới
   publish GLB + voxel JSON; binary occupancy `.voxel.bin` chưa published. Hoàn
   thiện portable metadata+binary refs/consumer checks khi nối occupancy viewer.
3. REC-07→08 reviewed coordinate bridge còn thiếu. Legacy
   `build_request_from_rec07_manifest` cố ý fail closed. Dùng owner decisions
   đã ghi (unit/axes/floor), nhưng không biến raw SfM origin thành LiDAR origin
   chỉ bằng distance scale; preserve immutable preparation/provenance.
4. Mixed canonical geometry/alignment verification và optional sensor-depth
   path cần verifier riêng. Final RGB bridge hiện chỉ canonical RGB geometry,
   không tự nhận native LiDAR/depth đã canonical; REC-09 gate vẫn bắt buộc ở REC-10.
5. Worker full input/privacy/frame-prep → preview → HITL → canonical/collision
   → alignment/bundle; PRODUCT owns authenticated decisions, queue/JobManifest,
   API và PlayCanvas/SOG browser integration. Không merge PRODUCT khi chưa được yêu cầu.
6. Real Aisle_CW metric correspondence/independent tolerance và GPU qualification
   vẫn pending. Không dùng 0.67 sanity estimate, floor offset hoặc fixture threshold
   làm scale/acceptance mặc định cho mọi video.

**Local-first testing:** owner đã chốt local integration smoke trước, Vast.ai qua
SSH nếu local không đáp ứng, nhưng integration chỉ bắt đầu sau EX-REC completion.
Chưa khởi động training hay thuê GPU. Host `nvidia-smi` ngoài
sandbox xác nhận T2000 / 580.178.04 / 4096 MiB; trong sandbox có thể báo driver
unavailable nên không kết luận driver hỏng từ lỗi sandbox. GPU browser render
vẫn nằm ở máy client dù worker training đặt trên cloud.

### Recovery checkpoint — Codex resume từ 56f987b

**Owner update:** sau integration sẽ chạy GPU trên **Vast.ai**, không khởi động
training 30k trên local ở checkpoint này. Không tự thuê/provision máy.
`nvidia-smi` local đã nhận Quadro T2000 / driver 580.178.04 / 4096 MiB. Vulkan
inventory ngoài sandbox, explicit NVIDIA ICD, exit 0 và báo Quadro T2000 discrete.
Ghi chú “driver không chạy” bên dưới đã outdated; đây mới là device enumeration,
chưa qualification config training 30k/960px/SH3/max_splats400k trên 4 GiB.

**Launcher:** `/tmp/opencode/hs/rec04_run.sh` không còn. Script hiện hữu
`data/rec04_runtime/run-smoke.sh` vẫn dùng smoke-config.json và ép Intel ICD trong
REC04_BRUSH_ENVIRONMENT, nên PRIME offload bên ngoài không override được. Khi
deploy phải inject Brush/Splat/COLMAP settings + config/timeout + new workspace
rõ ràng; không copy nguyên launcher cũ hoặc dùng lại attempt 10c.

- Đã đọc addendum 2/3 và WIP agent bàn giao; giữ nguyên guard `_require_job_identity`
  ở `metric.py` cùng tests. Không viết lại hoặc bỏ các quyết định owner về world
  floor, handedness, capsule, seed validation hay demo LiDAR assistance.
- Canonical visual producer WIP đã chạy native codec trên fixture và publish PLY/
  SOG bytes; cần commit sau current validation. Đây không phải final metric verifier.
- **Phân biệt smoke với demo:** inspected `rec04_smoke_artifacts_10c/visual.json`
  thực tế ghi 10 iterations, 128px, refine_every=200, 6.202 Gaussian. Nó là
  Gaussian technical smoke, không phải chất lượng demo đã nghiệm thu. Không có
  densification không tự chứng minh “không phải 3DGS”; không suy mọi lỗi alignment
  chỉ do sparse output. Record native inspection có `gaussian: true`.
- **UI integration:** cached `origin/feat/product` 012f349 có backend/UI nhưng
  routes job còn mock-worker; viewer chỉ parse ASCII PLY, package hiện dùng
  Three/R3F, chưa có PlayCanvas/SOG runtime theo baseline. Không merge/sửa PRODUCT
  trong lượt này. SceneObject defaults cũng lệch giữa branches (semantic_class/tags).
- **Thứ tự có thể thực hiện:** REC-11 preview dispatch qua frame → poses → Brush,
  nối PRODUCT worker + real SOG renderer, hiển thị visual với metric UNCONFIRMED.
  Preview không phải physics-ready và không cần chờ REC-06 final/REC-05 collider;
  chính preview phục vụ Editor chọn anchor. Sau đó mới nối canonical publication,
  approved distance protocol, seed clearance, collision/alignment và final bundle.
- Không tự chạy training dài/đổi driver/thuê GPU; owner đã dừng training vì nóng.
  `train-config.json` tồn tại không chứng minh 30k run thành công. Estimate thời
  gian/chi phí GPU ở addendum trước chưa phải cloud qualification đo được.
- Quota recovery rule theo owner: khi có tín hiệu remaining quota ≤3%, chốt phần
  dở ở boundary an toàn, lưu test result, commit intended changes và cập nhật file
  này với exact HEAD/worktree/next commands. Agent không có quota API thì phải nói
  rõ giới hạn đó, không giả định nhìn được phần trăm quota; checkpoint từng chunk.

### Addendum 3 — phát hiện REC-04 chưa train thật + việc còn lại (2026-09-27 ~16:30)

> **Bối cảnh:** owner yêu cầu chạy demo `upload video → frame → 3DGS → UI`. Khi
> truy ngược chuỗi để tìm tỉ lệ metric (REC-06) mới phát hiện ra vấn đề gốc ở
> REC-04. Addendum này ghi lại phát hiện đó **và danh sách việc còn lại**.

#### PHÁT HIỆN GỐC: `visual.ply` hiện tại KHÔNG phải 3DGS

Đọc `visual.json` + `brush-train.log` của attempt `rec04_smoke_artifacts_10c`:

```json
"total_train_iters": 10,     ← chỉ 10 bước
"max_resolution": 128,       ← ảnh nhỏ xuống 128px
"sh_degree": 0,
"refine_every": 200          ← refine mỗi 200 bước
```

| | |
| --- | --- |
| COLMAP `points3D` | 6.202 điểm |
| Brush `num_gaussians` | **6.202 — y hệt** |
| `fill_ratio` | 1,0265 (chỉ +2,7%) |
| `sh_bands` | 0 |
| Thời gian chạy | **2 giây** (01:40:18 → 01:40:20) |

Vì `refine_every: 200` mà chỉ chạy 10 bước → **densification chưa bao giờ chạy**.
Brush mặc định `--total-steps 30000`; giá trị 10 là số của smoke test.

**Hệ quả đo được:** reconstruction chỉ là COLMAP sparse cloud được tô màu, không
có cấu trúc bề mặt. Điều này giải thích mọi thất bại của bước thí nghiệm metric:

- COLMAP đặt điểm 3D trên **kệ**, không phủ sàn → không ghép được điểm sàn
- Scale phụ thuộc chiều dài baseline (Pearson **+0,528**, 4.528 cặp thử ở frame 110)
- Demo 3DGS trên UI sẽ trông như point cloud thưa

**Lưu ý:** `tasks/REC-04.md` đang ghi `Status: DONE` và `visual.json` ghi
`qualification: "real Brush technical smoke; not Primary Demo or metric geometry
acceptance"`. Mức smoke là đúng, nhưng **không được dùng làm 3DGS cho demo/AC-11**.

#### Đã đo được để chạy Brush thật

| Phép đo | Kết quả |
| --- | --- |
| 200 bước @ 1280px | 166,4 s — `num_gaussians` **vẫn 6.202** (refine 200 chưa tới) |
| 1.000 bước @ 1280px | 689,8 s — `num_gaussians` **7.903** → **densification hoạt động** |
| Tốc độ | 0,69 s/bước (chưa tính splat tăng) |

Ước lượng 30.000 bước: @1280px 5,7–11,5 giờ · **@960px 3,2–6,5 giờ** · @640px 1,4–2,9 giờ.
Đã tạo `data/rec04_runtime/train-config.json` (30.000 bước, 960px, sh_degree 3,
max_splats 400k, refine_every 200).

**CHƯA CHẠY XONG — owner báo máy nóng, đã dừng.** Lý do kỹ thuật chưa rõ:
chạy nền báo `brush-train failed (exit -6)` = SIGABRT, không có stderr Brush trong
log wrapper. Chạy foreground 240 s thì vẫn tiến (`Refine iter 201, 6555 splats`
→ `Refine iter 401, 6938 splats`) nên **không phải crash sớm** — nghi do SIGABRT khi
tiến trình bị `pkill`/session kết thúc, hoặc OOM khi splat dày lên. Cần chạy lại
và theo dõi `Refine iter` + `num_gaussians` để xác nhận.

#### Ràng buộc môi trường phát hiện được

| | |
| --- | --- |
| **Có Quadro T2000 trong máy** (`01:00.0 NVIDIA TU117GLM`) nhưng **driver không chạy** — `nvidia-smi` fail, Vulkan không thấy | Không dùng được |
| Vulkan chỉ thấy Intel UHD 630 + llvmpipe | Brush chạy trên iGPU |
| Ổ đĩa từng chỉ còn 5,1 G (98%) | Phải dọn trước khi chạy dài |
| RAM 30 G | |

→ **Thuê GPU host là hướng hợp lý**, nhưng rẻ hơn nhiều nếu cài driver cho
Quadro T2000 sẵn có. Đây là quyết định của owner, agent không tự cài driver hệ thống.

#### VIỆC CÒN LẠI — theo thứ tự nên làm

Demo mục tiêu: `upload video → tách frame → 3DGS → hiển thị UI, xoay tương tác`.

| # | Việc | Chặn cái gì | Cần owner? |
| --- | --- | --- | --- |
| **1** | **Train Brush thật** (30.000 bước @960px) | Không có 3DGS thật; và đo metric cũng cần | Quyết GPU: máy hay thuê |
| **2** | **REC-11 worker dispatch** | UI không chạy được pipeline | Không |
| **3** | **PRODUCT-08** nối `transition_job` vào worker thật | Hiện là mock-worker | Không |
| **4** | **PRODUCT-06 splat renderer** | UI chỉ parse PLY **ASCII**; artifact thật là `binary_little_endian` và `scene.sog` | Không |
| **5** | Mở 3 chỗ chặn `coordinate_status` | REC-08 ingest fail-closed | Đã có quyết định, cần code |
| **6** | A/B points + `tolerance_m` | REC-06 `CONFIRMED` | **Có** — sau #1 |
| **7** | Canonical visual publication (WIP của Codex) | REC-06 final verify | Không |

Chi tiết #2–#4:

- **#2** `src/services/reconstruction/worker.py` hiện chỉ có
  `execution_scope: Literal["verified_bundle_publication"]` và một stage
  `_execute_metric_canonicalize`. Không đọc `InputManifest`/`JobManifest`, không
  chạy chuỗi REC-01→11, không retry.
- **#3** `src/api/routes_product.py:143` trên `feat/product` tự ghi
  *"affordance **mock-worker**: trong P0 chưa có worker thật nên client đóng vai
  người báo tiến độ"*.
- **#4** `frontend/src/features/viewer/ply.ts` trên `feat/product` tự ghi
  *"Chỉ hỗ trợ `format ascii 1.0`. PLY binary cố ý **không** được parse"*, và
  `package.json` không có PlayCanvas/splat-transform. REC-04 đã xuất
  `scene.sog` (WebP nén, đúng format cho browser) — thiếu mỗi renderer.
  Theo `AGENTS.md` §8: mesh/point-cloud mock **không được** báo làm
  Brush/3DGS acceptance.

#### Ước lượng

| Việc | Công |
| --- | --- |
| #2 + #3 (worker + nối API) | 1–2 ngày |
| #4 (splat renderer) | 1–2 ngày |
| #1 (train) | 3–6,5 giờ máy, hoặc ~30–60 phút trên GPU thuê |

#### Trạng thái test lúc ghi addendum này

`pytest tests/test_reconstruction/ -q` → **380 passed, 21 skipped** (111,36s).
`ruff check src/ tests/ scripts/torwic` → pass, 186 files.
WIP của agent khác (`canonical_visual.py`, `REC-06.md`,
`test_rec06_canonical_poses.py`) **để nguyên unstaged**, không đụng vào.

#### Evidence gitignored

```
data/rec06_scale_experiment_20260927/   ảnh + result.json thí nghiệm metric
data/rec07_axis_evidence_20260927/      ảnh up-axis, camera chain, dataset figure
data/rec07_prefusion_sub100_119/        prefusion 20 scan (133.039 điểm)
```

### Resume addendum 2 — opencode audit WIP sau 99f2399 (2026-09-27 ~13:00)

**Không sửa gì.** Chỉ đọc và đo để báo cáo trạng thái. Worktree lúc audit này **KHÔNG
sạch** — có WIP của agent khác, giữ nguyên.

**Codex đã commit 3 việc sau `41ca8eb`:**

| Commit | Nội dung |
| --- | --- |
| `84d93c5` | `src/services/reconstruction/rgb/canonical_poses.py` (119 dòng) + `test_rec06_canonical_poses.py` (102) — publish/resolve canonical camera poses với exact lineage |
| `d6883b4` | `metric_verification.py` (sửa ~100 dòng) + `test_rec06_final_verification.py` — verifier chỉ báo `PENDING_FINAL_VERIFICATION`, không false `CONFIRMED` |
| `99f2399` | docs only — cập nhật readiness và **bỏ các nghiệm thu chưa có proof** (dọn claim sai) |

Hai việc này **đúng vào 2 khoảng trống tôi đã nêu** ở snapshot: canonical pose
publication và chặn false final verification.

**WIP chưa commit — canonical visual publication (đúng khoảng trống thứ 3):**

| File | Dòng | Ghi chú |
| --- | --- | --- |
| `src/services/reconstruction/rgb/canonical_visual.py` | 223 | service `CanonicalVisualService`: `execute/_context/_convert/_check_codec/_publish/load` |
| `src/services/reconstruction/rgb/canonical_visual_models.py` | 52 | `CanonicalVisualRequest`, `CanonicalVisualManifest` (checksum-bound, `delivery_ref()` trỏ thẳng SOG bytes) |
| `tests/test_reconstruction/test_rec06_canonical_visual.py` | 160 | **10 passed, 1 skipped** |
| `docs/.../REC-06.md` | +15 | mô tả kế hoạch bước này |

Thiết kế đáng chú ý: reuse `SplatTransformSimilarityAdapter` pinned + `SplatArtifactProcessor`
SOG encode, **không** viết Gaussian codec mới; giữ shared `VisualArtifact` ở stage
`ST-VISUAL-RECON` theo contract, chỉ record conversion ở `ST-METRIC-CANONICALIZE`.

**Trạng thái test đo được lúc audit (không opt-in GPU/native):**

```
pytest tests/test_reconstruction/ -q  →  2 failed, 376 passed, 21 skipped (98.12s)
ruff check src/ tests/ scripts/torwic →  All checks passed!
```

**2 test ĐỎ — đây là TDD red hợp lệ, chưa phải regression:**

`tests/test_reconstruction/test_rec06_canonical_poses.py` vừa thêm
`test_confirmation_job_identity_is_required` (parametrize `job_id=None` /
`"another-job"`), kỳ vọng `ValueError` khớp `"confirmation job identity"` → **DID NOT RAISE**.

Xác minh nguyên nhân: `canonical_poses.py:51-62` (`build`) không validate
`confirmation_ref.job_id`, và dòng 102 dùng thẳng
`job_id = artifact.confirmation_ref.job_id` để dựng URI. Nếu `job_id` là `None` thì
URI thành `artifact://jobs/None/rec06/...`. Guard **chưa được implement** — test viết
trước, đúng thứ tự.

**Một vi phạm chuẩn code phát hiện được:**

`canonical_visual.py` — hàm `_publish_blob(context, spec, payload, ...)` có
**4 tham số**, vượt giới hạn ≤3 trong `AGENTS.md` §8 Python. Nên gộp `spec` +
`payload` thành một typed model. Không sửa hộ, chỉ báo.

**Còn thiếu, chưa ai động tới:**
1. **A/B points** — vẫn phải do người chọn (xem `tasks/REC-06.md` mục "2026-09-27 —
   thử tự suy A/B"; `data/rec07_axis_evidence_20260927/ab_candidates.png` để bạn
   chọn 2 vị trí nhận dạng được).
2. **`tolerance_m`** — vẫn chờ đo trên đúng cặp người chọn; `0.05` ở
   `metric_verification.py` chưa phải authority.
3. **Production metric verifier** — `d6883b4` đã chặn false CONFIRMED nhưng chưa có
   verifier production, nên worker CLI vẫn fail-closed.
4. **Full worker dispatch** (`InputManifest`/`JobManifest`) + retry.
5. **Real alignment** (REC-09 same-scene thật) + native LiDAR coordinate promotion.

### Resume addendum 3 — job identity guard + xác minh lại addendum 2 (2026-09-27 ~13:40)

**Sửa một claim sai của addendum 2:** `canonical_visual.py::_publish_blob` **không** có
4 tham số. AST check cho `self, context, spec, payload` → **3 non-self params**, đúng
giới hạn ≤3 của `AGENTS.md` §8. Không có vi phạm cần gộp typed model. Addendum 2 đếm
nhầm.

**Đã làm:** guard `_require_job_identity` trong `rgb/metric.py::load` — confirmation ref
phải có `job_id` và URI trỏ đúng job đó. Đóng 2 test đỏ TDD mà addendum 2 nêu
(`test_confirmation_job_identity_is_required[None|another-job]`), vì `CanonicalPoseService.build`
từng lấy thẳng `confirmation_ref.job_id` dựng URI. Guard đặt ở loader để
canonical poses, canonical visual và metric verification cùng hưởng, theo convention
đã có ở `metric_verification.py:89-92`. Thêm negative test ở `test_rec06_confirmation.py`.

**Trạng thái đo được lượt này:**

```
pytest tests/test_reconstruction/ -q                 →  380 passed, 21 skipped (89.10s)
pytest tests/test_reconstruction/ -q (codec+GPU)     →  401 passed, 0 skipped (112.44s)
ruff check / ruff format --check (191 files)         →  pass
AST 7 file (≤30 dòng, ≤3 non-self params)            →  0 vi phạm
```

Codec thật dùng cho lượt này: `splat-transform` **3.6.6** tại
`data/rec04_runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs`
(+ `bin/cli.mjs` cho voxel). `test_native_metric_ply_and_sog_publication` chạy thật, đọc
SOG bytes thật (`PK`) — vẫn **không** phải browser QA.

**Còn thiếu (không đổi so với addendum 2):** A/B points do người chọn, `tolerance_m`,
production metric verifier, full worker dispatch + retry, real alignment REC-09. REC-06
giữ `IN_PROGRESS`. `.venv` vẫn thiếu `numpy` nên full `pytest tests/` vẫn vướng EX-SIM.

### Resume addendum — Codex sau 41ca8eb (không sửa snapshot lịch sử bên dưới)

- Đã đọc 7 commits sau 45db57e: docs/evidence only. Kiểm lại byte SHA-256 của
  prefusion 20 scan và manifest tại
  `data/torwic_slam/derived/aisle_cw/rec07_prefusion_sub100_119/`: khớp checkpoint.
- Owner origin/capsule decisions ở 01305c9 và failed automatic A/B ở 41ca8eb
  xảy ra **sau** snapshot này; không dùng danh sách unknown cũ thay task hiện tại.
- §9 dưới đây **không phải readiness assessment hiện hành**: cached
  `origin/feat/product` 012f349 có UI/backend. Routes job còn mock-worker,
  MetricScalePanel chỉ hiển thị. EX-PRODUCT có thể tích hợp song song qua contracts;
  không cần đợi thứ tự tuyến tính REC → SCENE → SIM → PRODUCT.
- Việc P0 không bắt buộc CUDA không có nghĩa GPU host không hữu ích cho Brush/
  voxel hoặc EX-REC đã ready chạy cloud E2E. Chưa qualification trên cloud; phần
  thiếu hiện tại gồm canonical visual, final metric proof, strict seed/clearance,
  real alignment và full worker dispatch — thêm GPU không tự hoàn thành chúng.
- `84d93c5`: publish/resolve actual canonical camera poses với exact lineage.
  `d6883b4`: verifier chỉ báo PENDING_FINAL_VERIFICATION, không false CONFIRMED.
- Test lại: EX-REC **381 passed/5 skipped** với GPU/native opt-ins; contract /
  integration **94 passed/2 existing SceneIR checksum failures**; full collection
  vướng NumPy ở EX-SIM. Chi tiết và next step nằm trong active plan/REC-06.

- Worktree **sạch**. **Không sửa một dòng code nào** trong phiên này.
- Baseline chạy lại lúc bàn giao:
  - `pytest tests/test_reconstruction/ -q` → **338 passed, 20 skipped** (119,85s)
  - `ruff check src/ tests/ scripts/torwic` → pass
  - `ruff format --check src/ tests/ scripts/torwic` → **186 files**

### Cảnh báo môi trường

`.venv` **thiếu numpy** → `pytest tests/` collect được 494 test rồi **đứng** vì
`tests/test_simulation/test_colliders.py:5` lỗi `ModuleNotFoundError`. Đây là
vấn đề môi trường, **không phải lỗi code**, và nằm ngoài ownership EX-REC. Cần
vá trước khi chạy full suite.

## 1. Commit của phiên này (4, đều docs-only)

| Commit | Nội dung |
| --- | --- |
| `c1fe3f6` | Chạy prefusion 20 scan + đo trục up/unit |
| `a713d7e` | Chốt up-axis Z bằng hai phép đo; **ghi lỗ hổng** camera chain (chưa giải) |
| `4078686` | **Giải camera chain** — ảnh đã undistorted; chốt up-axis 3 nguồn; tra dataset docs |
| `5713976` | Owner chốt handedness (thuận tay) |

File sửa: `tasks/REC-07.md` (+133), `tasks/REC-09.md` (+107),
`../../plans/active/2026-09-24-ex-rec-track.md` (+100). Tổng **+340 dòng, 0 xoá**.

## 2. File tạo mới (đều gitignored, không có trong git)

`.gitignore:32` ignore `data/`. Agent sau **phải tự sinh lại**, đừng tìm trong git.

### `data/rec07_prefusion_sub100_119/`

| File | Size | SHA-256 |
| --- | --- | --- |
| `registered_lidar.ply` | 3,2 MB | `4d7cce292587d0d22cf0925ad28c57085c9c10f5007bd1b7dad202d66e6ded4c` |
| `preparation_manifest.json` | 9,4 KB | `f920d2459e1910ff06804e2cbd6f9c9a3d9989a8237fca3ed23fca699146ed83` |

Manifest content checksum: `sha256:d9a14b8b3716187f4e36a73183f0a45d9b6566b85418b452beccfda702d57987`

Lệnh sinh lại (không sửa code, dùng env có sẵn trong `tests/test_reconstruction/rec07_smoke.py`):

```bash
REC07_SMOKE_START_FRAME=100 \
REC07_SMOKE_FRAME_COUNT=20 \
REC07_SMOKE_OUTPUT_RELATIVE=derived/aisle_cw/rec07_prefusion_sub100_119 \
data/rec07_runtime/bin/python -m tests.test_reconstruction.rec07_smoke
```

### `data/rec07_axis_evidence_20260927/`

| File | SHA-256 | Nội dung |
| --- | --- | --- |
| `up_axis_proof.png` | `05c77d10b9726147d014f5b0b335f078c282cdbf46da15cbe05a86d6c03e7d0b` | 6 panel: 3 góc nhìn trực giao XY/XZ/YZ, lát cắn đậm nhất theo trục, zoom lát cắn sàn, cao độ cảm biến theo thời gian |
| `scan110_hypotheses.png` | `bb0085a058fbdeb7b42a58266c53485db6ecdd98f24fcb58eacf64b2780678e5` | 5 giả thuyết chồn lên ảnh thật (giai đoạn camera chain chưa giải) |
| `camera_chain_final.png` | `97dcbf2e242cc5b64434fa36789470183a26e94c1c666e808c163369a123664c` | raw scan `000110` chồn ảnh thật; chuỗi đúng dừng đúng ở vạch sàn vàng, biến thể sai rõ ràng |
| `dataset_official_sensor_frames.png` | `7e803b2ed82a026969b1756edba50e0d435fe32c9b586f45469a745a0ad6cc9b` | copy từ dataset repo `Figures/slam_sensor_frames.png` |

## 3. Phát hiện quan trọng nhất — cần hành động

> **`data/torwic_slam/normalized/aisle_cw/rgb_frames/*.png` ĐÃ LÀ ẢNH
> UNDISTORTED.** Hệ số `Camera1.D` trong `raw/global/calibrations.txt` **KHÔNG
> được áp** lên các ảnh này.

Chuỗi camera đúng:

```text
T_cam_from_os = inverse(T_os_from_cam)
  → frame camera theo OpenCV optical (x phải, y xuống, z trước)
  → KHÔNG áp distortion
```

Bằng chứng — residual chân trời (mặt sàn phải hội tụ về một đường ngang), đo trên
11 frame rải khắp traversal `100, 105, 110, 115, 119, 300, 450, 500, 700, 900,
1050`:

| | residual |
| --- | --- |
| Có áp distortion | 49,8 – 65,7 px (TB **57,8**) |
| Không áp | 5,0 – 7,1 px (TB **5,9**) |

Cải thiện **10×**, nhất quán cả 11 frame. Nghiêng suy ra từ sàn là `+2,93°`, khớp
`3,27°` mà extrinsic khai báo.

**Việc chưa làm, nên làm tiếp:** chưa có regression test khoá hành vi này. Bất kỳ
code chiếu/align LiDAR↔RGB nào áp `D` sẽ lệch hàng chục pixel. Đây là rủi ro
regression thật do phát hiện này mở ra.

Chi tiết đầy đủ: `tasks/REC-09.md` §"ĐÃ GIẢI 2026-09-27".

## 4. Đã xác nhận được

### Up-axis = +Z, đơn vị = mét

Ba nguồn độc lập, tất cả đặt mặt sàn cùng một cao độ:

| Nguồn | Frame | Giá trị sàn | Tỉ lệ điểm |
| --- | --- | --- | --- |
| Merged cloud 20 scan | world | z = **−0,218 m** | 27,9% (37.154) |
| Raw scan `000110.pcd` | os_sensor | z = **−0,468 m** | 44,9% (37.274) |
| `raw/global/groundtruth_map.ply` | world | z ≈ **−0,25 m** | 301.094 trong lát 0–0,3 m |

Cộng cao độ cảm biến `+0,218 m` (1092 pose, biên độ chỉ 7,6 cm) → sàn world
≈ `−0,238 m`. Ba cách đo khớp nhau trong 1–2 cm. Nếu sai trục hoặc sai dấu thì
không thể trùng nhau.

Trục Z là up còn xác nhận thêm bằng: lát cắn z đậm nhất **1,75 cm / 11,8%** điểm,
mỏng và đậm hơn X (6,7 cm / 6,9%) và Y (15,1 cm / 4,1%); 1092 pose nghiêng khỏi
mặt ngang max 2,17° / mean 1,12° / p99 1,86° (heading 359,6° là yaw bình thường).

### Chuỗi pose + scan tự nhất quán, khớp GT map

40.000 điểm thuộc scan `000110` (frame 110), giới hạn dưới 2,5 m, khoảng cách tới
bề mặt `raw/global/groundtruth_map.ply`:

| Biến thể | median | p90 | <0,10 m | <0,25 m |
| --- | --- | --- | --- | --- |
| **H0 khai báo, không đảo** | **0,0592 m** | 0,6003 m | **76,6%** | **82,7%** |
| H1 mirror x | 0,0692 m | 0,8608 m | 68,9% | 76,1% |
| H2 mirror y | 0,0814 m | 0,7516 m | 60,7% | 76,2% |
| H3 mirror z | 0,8410 m | 0,9484 m | 5,7% | 14,7% |
| H4 180° quanh y | 0,8360 m | 0,9430 m | 3,7% | 12,4% |

Chuỗi khai báo khớp nhất, kém hơn biến thể mirror-z tới **14×**. Test này **có
phân biệt được** (khác với test chân trời, mù với handedness vì mặt phẳng sàn vẫn
cho một đường chân trời dù đảo trục nào).

### Prefusion 20 scan chạy thật, deterministic

133.039 điểm (gấp **2,42×** bản smoke 5 scan trước đó: 54.957). Replay vào
thư mục khác cho PLY và manifest **cùng checksum byte-for-byte**; thư mục replay đã
xoá sau khi so.

Chọn frames 100–119 vì REC-03/04 đã dựng COLMAP/Brush trên frames 100–200
(`derived/aisle_cw/rec03_smoke_workspace_sub100_200/images/`), cùng dải để REC-09
same-scene correspondence dùng được. Số 20 theo khuyến nghị DATASET_PLAYBOOK.
20 frame này phủ 1,6 m đường đi (toàn traversal 81,1 m) — là lát cắt sắc nét theo
playbook, **không** phải bản đồ toàn cửa hàng.

Runtime: Open3D 0.19.0 + NumPy 2.5.3 trong `data/rec07_runtime`.

## 5. Nguồn đã tra (dataset repo local)

Owner cấp `private/TorWICDataset` @ `5e1839f`:

| Nguồn | Nội dung dùng được |
| --- | --- |
| `Figures/slam_sensor_frames.png` | Azure Kinect **xanh = phải, lục = xuống, đỏ = trước** ⇒ optical/OpenCV. Ouster **xanh = lên** ⇒ Z-up. |
| `README:235` | *"The poses (of the mounted Ouster OS1-128 LiDAR) were obtained by **aligning the 3D scans against the ground-truth 3D map**"* — đây là nguồn gốc giả thuyết `os_sensor` mà `DATASET_PLAYBOOK` ghi là *"hypothesis mạnh từ projection/map, chưa được SLAM backend xác nhận trực tiếp"*. |
| `README:219` | *"The robot always starts at the origin of our map frame"* — kết hợp sàn đo được ở `z ≈ −0,24 m` ⇒ **z=0 của map frame không phải mặt sàn**. |
| `README:161` | `depth_left/right` là **RGB-aligned depth**; checkout hiện tại **không có** thư mục depth. |
| `TorWIC_Dataset.pdf` | Mô tả kịch bản localization (rào, thùng), **không** mô tả convention. |

### Cảnh báo: `utils/calibration.py` là scenario KHÁC

File đó là cho **localization scenario** khác: `base_link`, RealSense D435i, Hokuyo
UAM501, 640×360, `D = [0,0,0,0,0]`, intrinsics `fx=461,10` / `cx=325,48`. **KHÔNG**
phải bộ calibration của dữ liệu SLAM mà ta có (`os_sensor` / `azure_left_camera`,
1280×720, `fx=621,40` / `cx=649,64`, `D≠0`). Tuyệt đối không lấy nhầm.

### Owner đã chốt

Ouster OS1-128 dùng convention `x` forward, `y` left, `z` up ⇒ **thuận tay**, trùng
canonical convention của project (meter, Z-up, right-handed). Hệ quả: **không cần
đảo trục nào** khi chuyển native frame sang canonical `world`; chỉ còn phép tịnh
tiến để đặt gốc.

**Mức độ tin cậy — quan trọng:** đây là **owner attestation, KHÔNG phải agent
verify**. Đã thử nhiều URL datasheet Ouster và đều 404, không đoán URL; README/PDF
của dataset không nêu handedness; figure phối cảnh không phân định được thuận/ngược
tay. Khi khóa `coordinate_status`, **ghi nguồn là owner decision, đừng ghi
"VERIFIED từ tài liệu"**. Nếu sau này có datasheet hoặc raw ROS bag / `tf_static` của
chính dataset thì đối chiếu lại và cập nhật nguồn.

## 6. Trạng thái task — không đổi trong phiên này

| Task | Status |
| --- | --- |
| REC-01, REC-02, REC-02A, REC-03, REC-04 | `DONE` |
| REC-07 | `VALIDATING` |
| REC-05, REC-06, REC-08, REC-09, REC-10, REC-11 | `IN_PROGRESS` |

Không task nào được nâng status. `coordinate_status` vẫn `UNVERIFIED`,
`assistance_class` vẫn `GT-assisted`, `confirmed_rgb_alignment` vẫn `false`.

## 7. Việc tiếp theo

### Làm được ngay, không cần owner

1. Vá `.venv` thiếu numpy → mở full suite.
2. Viết regression test khoá hành vi "không áp `D` lên ảnh đã undistorted".

### Chặn, cần owner quyết

3. **Quy tắc gốc `world`** — sàn ở `z ≈ −0,24 m`. Đặt sàn = z 0, hay giữ nguyên
   và khai báo rõ?
4. **2 cặp điểm A/B** trên LiDAR đã căn chỉnh — một cặp để tính scale, một cặp
   khác để kiểm chứng độc lập (ADR 0001: không dùng chung một measurement).
5. **`tolerance_m`** — hiện hardcode `0.05` tại
   `src/services/reconstruction/rgb/metric_verification.py:24`; PRD §11.4 câu 4
   vẫn `TBD`.
6. **Capsule robot** — `tasks/REC-05.md` chỉ có số demo `radius=0.35 m`,
   `height=1.20 m`, chưa phải số khóa.

Xong 3–6 → mở REC-06 → REC-05 real metric spike → REC-10/11 production verifier.

### Ba chỗ code đang chặn promote (chưa đụng)

- `scripts/torwic/build_registered_lidar.py:31` — `coordinate_status="UNVERIFIED"` cứng
- `src/services/reconstruction/lidar/models.py:31` — `Literal["UNVERIFIED"]`, type không cho giá trị khác
- `src/services/reconstruction/lidar/ingest.py:136` — `build_request_from_rec07_manifest` raise vô điều kiện

Cần owner duyệt trước khi mở. Đây là thay đổi behavior, không phải refactor.

## 8. Sai lệch docs cần biết

1. **DoD checkbox sai.** Sáu task file đã tick `[x]` hết ở các commit
   `feat(rec): hoàn thành` (2026-09-26); đợt audit chỉ revert `Status` về
   `IN_PROGRESS` mà **không bỏ tick DoD**. Đọc `Status` + `Result/Evidence`,
   **đừng dùng DoD checkbox làm bằng chứng**.
2. **Plan stale.** `docs/plans/active/2026-09-24-ex-rec-track.md` cuối file còn ghi
   *"REC-02 through REC-11 have all been completed"* + "274 passed" — mâu thuẫn
   checkpoint ở đầu `## Outcome`. Phần cuối đó là lịch sử, không phải trạng thái.
3. **Lỗi ngoài EX-REC.** `tests/test_contracts/test_identity.py` fail 2 case
   (SceneIR checksum). Cả file test lẫn `src/models/contracts/identity.py` chỉ
   bị sửa bởi commit foundation `49f2456`, **không** do EX-REC. Ngoài ownership.

## 9. Bối cảnh sản phẩm để khỏi đề xuất sai

- **`frontend/` chưa tồn tại.** `src/api/routes.py` chỉ có 2 route: `/chat`,
  `/status` — không có route reconstruction nào.
- **EX-PRODUCT: 13/13 task `TODO`.** UI là PRODUCT-05/06, tức task cuối.
- **EX-SIM: 2 `DONE` / 8 `TODO`.** Isaac validation chưa bắt đầu.
- **`tests/e2e/` rỗng** — chưa có test E2E nào.
- Thứ tự đúng: `REC → SCENE → SIM → PRODUCT`.
- **P0 không cần CUDA.** REC-03 COLMAP có toggle CPU/GPU; REC-04 Brush đã chạy
  thật trên Intel UHD 630; REC-05 voxel dùng WebGPU và đã chạy ở index 0. Chỉ
  AI auto-scale (ADR 0001 §P1) và Isaac Sim mới cần NVIDIA — **đừng thuê GPU host
  vì lý do EX-REC**.

## 10. Cách tái lập các phép đo trong handoff này

Mọi script phân tích nằm ở `/tmp/opencode/` và **không tồn tại sau restart**. Nếu
cần tái lập hoặc kiểm chứng lại:

- Đọc PLY không cần Open3D: file `binary_little_endian 1.0`, offset =
  `raw.index(b"end_header\n") + len(b"end_header\n")`, shape `(N, 3)`, dtype `<f8`.
- Cần NumPy + Open3D thì dùng `data/rec07_runtime/bin/python` (Open3D 0.19.0,
  NumPy 2.5.3, scipy 1.18.1, matplotlib, PIL). `.venv` thiếu numpy.
- Đọc GT map bằng `open3d.io.read_point_cloud` (1.065.059 điểm); **không** parse
  thủ công — header `end_header` không có newline cuối và offset thủ công dễ sai.
- Camera: parse `calibrations.txt` tách cả dòng số **và** `Camera1.D` ( là list,
  không parse được bằng `float()`).

## Validation của chính phiên này

- `pytest tests/test_reconstruction/ -q` → 338 passed, 20 skipped
- `ruff check src/ tests/ scripts/torwic` → pass
- `ruff format --check src/ tests/ scripts/torwic` → 186 files
- `git diff 45db57e..HEAD -- src/ tests/ scripts/` → **rỗng**, xác nhận không sửa code
- Không push, không merge, không đổi branch
