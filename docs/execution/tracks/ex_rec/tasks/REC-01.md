# REC-01 — TorWIC Preparation

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `DONE` |
| Owner | `@awun0105` |
| Target milestone | `M0/M1` |

## 2. Goal

Chuẩn bị một TorWIC traversal reproducible với `raw/` immutable, normalized product input, benchmark split và calibration/timestamp metadata.

## 3. Why This Task Exists

Tạo input nền cho EX-REC bring-up mà không trộn raw, derived và evaluation-only assets.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- Foundation Lock selects the bring-up traversal.
- No implementation task dependency.

### Task audit với nguồn authority (2026-09-24)

- `docs/PRD.md` §11 và `docs/execution/TEAM_EXECUTION_PLAN.md` §4.1.1 để
  Primary Demo range/split là một quyết định cần khóa, không suy từ sensor smoke.
  Owner đã chọn cả 1.092 frame `Aisle_CW` làm source sequence và ngày
  2026-09-24 đã chọn deterministic temporal block split khoảng 10%, trải ở
  đầu/giữa/cuối traversal, khóa trước khi xem metric.
- `docs/execution/INTEGRATION_PLAYBOOK.md` §2.1 bắt buộc kiểm **layout thật**
  trước normalize. Source dùng cho pipeline hiện nằm trong
  `data/torwic_slam/raw/global` và `raw/traversals/aisle_cw`; mount phẳng
  `calibrations.txt` + `Aisle_CW/` là bản download gốc, không còn là
  đường đọc chuẩn trong repo. Adapter hỗ trợ cả hai layout.
- `docs/execution/TRACK_IMPLEMENTATION_GUIDE.md` §2.5,
  `docs/DATASET_PLAYBOOK.md` §12–14 và
  `docs/execution/TEAM_EXECUTION_CONTRACT.md` Chương 5 yêu cầu tách
  `raw/normalized/derived/evaluation_only`, khóa split trước đánh giá và
  không feed ground truth vào RGB reconstruction. REC-02 sở hữu quality/privacy
  gate; REC-01 chỉ chuẩn bị dữ liệu offline và kiểm cấu trúc/metadata.
- Shared `InputManifest` với logical `artifact://jobs/...` là handoff job ở
  `TEAM_EXECUTION_CONTRACT.md` §3.3. Manifest dataset của REC-01 phải versioned,
  có relative refs giải được dưới output root, checksum/provenance và đường
  sang REC-02 rõ ràng; không tự nhận nó là shared `InputManifest`.

## 5. Input Contract

- TorWIC source traversal và checksums.
- P0 traversal `Aisle_CW`; `Aisle_CCW` là bổ sung/backup. REC-01B sensor evidence nằm trong `DATASET_PLAYBOOK.md`; không dùng frame `000500` làm Primary Demo range mặc định.
- Dataset preparation policy trong `DATASET_PLAYBOOK.md`.

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- Normalized RGB/data layout.
- Benchmark split manifest và calibration/timestamp metadata.
- Preparation provenance/checksums.
- Một physical RGB set tại `normalized/aisle_cw/rgb_frames/` gồm mọi usable
  frame; từng ảnh có `product_input` data class. Split logical tại
  `derived/aisle_cw/benchmark_split.json` định nghĩa reconstruction/held-out
  IDs, có `evaluation_only` data class. Generic product resolver không được
  auto-load split; EX-REC orchestration chỉ dùng reconstruction IDs, evaluator
  chỉ dùng held-out IDs từ cùng normalized RGB set.
- `derived/aisle_cw/preparation_manifest.json` ghi relative path/data class/
  checksum, frame ID và timestamp cho từng ảnh cùng provenance.
  `dataset_manifest.yaml` ở canonical dataset root là dataset-level index,
  không cạnh tranh với traversal preparation manifest. Không lộ private path.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `scripts/torwic/`
- `tests/test_reconstruction/`
- dataset manifests/fixtures đã được owner chấp nhận

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

`SELF-CODE` dùng FFmpeg/Open3D primitives; không gọi offline scripts từ product runtime.

Giữ tool/research repo ở process/adapter boundary; không kéo toàn bộ research dependency graph vào application.

## 9. Implementation Plan

2026-09-24: Codex đã đọc source anchors, scaffold, contract và source audit của
Antigravity; source gốc và checkout hiện tại chưa có REC-01 pipeline. Triển khai
trong `scripts/torwic/` và test trong `tests/test_reconstruction/`:

1. CLI nhận root dataset, traversal `Aisle_CW`, output root và lựa chọn frame/split
   tường minh; không có absolute path hoặc lựa chọn frame mặc định trong code.
2. Inventory/kiểm tra sequence RGB và timestamp, checksum source files; parse
   `calibrations.txt` theo cú pháp hỗn hợp `=` và `:` và chuẩn hóa frame/transform có kiểm tra
   chiều transform. Giữ `raw/` và source mount bất biến.
3. Publish normalized RGB, timestamp/calibration/coordinate metadata và split
   manifest cùng provenance/checksums và resolvable relative refs; tách
   evaluation role khỏi product input. Fail rõ ràng cho missing/duplicate/
   structurally invalid/mismatched inputs và selection lỗi. Full image decode,
   blur/motion và privacy thuộc REC-02.
4. Test parser/sequence/split/immutability/checksum (positive và negative),
   sau đó smoke với một subset nhỏ của traversal thật và verify mọi emitted
   reference/checksum. Không claim smoke là benchmark split đã khóa.

External audit: `TorWICDataset` commit
`5e1839f8db73dee784737c53103a4fb06a3fed1d`; `utils/` dành cho
TorWIC-Mapping/ROS1 và bị loại khỏi REC-01. Project tự viết offline adapter; không
copy upstream code. Không thêm Open3D cho REC-01 nếu không chứng minh nhu cầu.
Owner chọn toàn bộ 1.092 frame của `Aisle_CW` làm source sequence ngày
2026-09-24. Owner sau đó chọn sort theo timestamp, loại frame invalid theo rule
cố định trước split, held-out khoảng 10% bằng ba temporal blocks đầu/giữa/cuối,
freeze IDs/checksum và không thay split sau khi xem metric. REC-01 áp dụng rule
structural: timestamp phải hữu hạn/tăng nghiêm ngặt và mapping ID phải rõ;
ảnh thiếu hoặc PNG signature/resolution sai bị loại bằng danh sách ID/reason
có checksum; lỗi timestamp/mapping khiến preparation fail thay vì tự gán sai
frame. Full decode, blur, motion, privacy thuộc REC-02; một ảnh lặp bytes không
tự động là invalid ở REC-01. Với dữ liệu source hiện tại, split deterministic đã khóa
cho 1.092 frame hợp lệ: held-out `118-153`, `528-564`, `937-972` (109/1.092),
train là phần bù theo thứ tự timestamp. Đây là rule chốt trước metric; nếu
structural invalid xuất hiện, ghi excluded IDs và tính lại ba block theo cùng
percentile rule trước khi freeze, không chỉnh theo chất lượng metric.
2026-09-24: Codex duyệt strategy. Sau khi owner dừng Antigravity, Codex trực
tiếp audit/sửa code, bổ sung mode `complete`/`sample` và chạy full artifact.

2026-09-24 correction: source trong repo đã được sắp vào
`data/torwic_slam/raw/global` và `raw/traversals/aisle_cw`; script cũ chỉ
đọc layout phẳng từ ổ ngoài. Reopen REC-01 để thêm source-layout adapter,
kiểm source files từ data/ và tạo/validate artifact từ nguồn đúng. Giữ nguyên
scaffold `data/torwic_slam` và artifact cũ; không ghi đè dữ liệu user.

## 10. Tests

- Dataset layout/parser unit tests.
- Raw immutability và checksum negative test.
- Small traversal preparation smoke; output manifest validates.
- Existing-output mismatch/refusal, idempotent canonical output và wrong-layout
  failure test.
- Real output refs resolve; generated checksums match actual bytes; train và
  held-out cùng physical `rgb_frames/` nhưng role sets disjoint.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Selected traversal chuẩn bị được từ raw source bằng command versioned trong repo.
- [x] `raw/` không bị mutate; một normalized RGB set; split/configuration
      mang `evaluation_only` class và GT không vào product refs.
- [x] Split, calibration, timestamp và provenance có checksum.
- [x] Manifest output versioned; mọi selected RGB/metadata/split có relative
      refs và checksums resolve được; nguồn source IDs/timestamps khớp 1-to-1.
- [x] Held-out role bị cô lập bằng frozen split; raw/source bất biến;
      không nhận false privacy/real reconstruction proof từ REC-01.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

Previous evidence (external flat source only; correction in progress 2026-09-24).
Strategy: project-owned offline parser/copier/validator tại
`scripts/torwic/prepare_dataset.py`; không copy source hay thêm dependency từ
`Viky397/TorWICDataset` commit
`5e1839f8db73dee784737c53103a4fb06a3fed1d`. Audit trực tiếp thấy
`utils/data_loader.py` dùng layout TorWIC-Mapping `Scenario_*/RGB`, còn
`utils/calibration.py` hardcode RealSense/ROS1; cả hai không phù hợp TorWIC-SLAM
mount thật. Dataset terms: CC BY-NC 4.0 và điều khoản bổ sung ở
`License/ReadMe.md`. Source chỉ dùng làm reference về provenance.

Artifact thật: `Aisle_CW` trong thư mục `TorWIC SLAM Prepared/Aisle_CW` nằm
cạnh source trên ổ Elements/AI20K; output root đặt read-only sau validate.
`manifest.json` mode `complete`, schema `1.0`, 1.092 ảnh source và 1.092 ảnh
generated; `normalized/` chứa 983 train PNG, `evaluation_only/` chứa 109
held-out PNG. Split frozen ở `derived/Aisle_CW/benchmark_split.json`, tagged
`evaluation_only`; held-out IDs: `118-153,528-564,937-972`, không có frame
structural invalid. CLI từ dataset root với `--dataset-root .`,
`--traversal-id Aisle_CW`, `--frame-ids
0-117,154-527,565-936,973-1091`, `--held-out-ids
118-153,528-564,937-972` và output root riêng; không dùng `--sample`.
Smoke subset phải dùng `--sample`, manifest không thể đổi thành `complete`
chỉ bằng rehash nếu thiếu frame.

Checksums/evidence:

- Script SHA-256 `48ef5274bbc5323ae9925ca2366185b42cb6d151e8d955864560daf50b560486`.
- Manifest canonical checksum `sha256:26d6f86653e082158550520a5b9a119eb393ae0be12ddb1417db2732beeb5c94`;
  byte SHA-256 `sha256:2e4c093089e90bc27c921a2c23b1a4156d06b6ef5f5c335a2fbfa5c2f762d74e`.
- Split canonical checksum `sha256:2b87b3b5ee95b4382bf42a58ab932a5520f06b39f749ba407679764a592c0228`;
  byte SHA-256 `sha256:72155dbf67230ad63c5e0cc5e54363e8d3f5c718ac25abeb2800a23026b2d466`.
- SHA-256 của 1.094 source files (1.092 PNG, calibration, timestamps) trước/sau
  full preparation giống hệt nhau (`cmp` exit 0). Validator đọc lại toàn bộ
  source/generated refs và checksum tại cả `/tmp` và output bền vững, đều pass.
- `.venv/bin/ruff check src tests scripts/torwic` pass;
  `.venv/bin/ruff format --check src tests scripts/torwic` pass (90 files);
  `.venv/bin/pytest tests/test_reconstruction/test_rec01_dataset.py -q`:
  34 pass; `.venv/bin/pytest tests/test_contracts tests/integration -q`:
  96 pass; `git diff --check` pass. Negative tests gồm manifest bị rehash
  sau sửa split/timestamp/calibration/frame path/image bytes, path/class sai,
  invalid frame, output tồn tại và partial cleanup.

Giới hạn: REC-01 chỉ kiểm cấu trúc PNG/header và thứ tự timestamp. Full image
decode, blur/motion/privacy và `InputManifest` product handoff thuộc REC-02/
REC-02A; không claim reconstruction hay GPU acceptance từ artifact này.

### Canonical `data/` source correction (2026-09-24)

REC-01 được mở lại sau khi owner chỉ ra dữ liệu đã sắp trong `data/`. Codex thêm
`TorwicSourceLayout` cho `raw/global/calibrations.txt` và
`raw/traversals/aisle_cw/{frame_times.txt,image_left/}`; manifest source refs
luôn tương ứng layout thực, validator tự resolve lại source và không chấp nhận
refs layout khác. Layout phẳng cũ vẫn được test để giữ compatibility. Không
reuse/copy module TorWICDataset upstream; commit tham chiếu ở trên giữ nguyên.

Run đầy đủ dùng `--dataset-root data/torwic_slam`, traversal `Aisle_CW`, train
`0-117,154-527,565-936,973-1091`, held-out `118-153,528-564,937-972`,
output `data/torwic_slam_rec01/aisle_cw` (thư mục mới trong `data/`, không
ghi đè scaffold). `manifest.json` schema `1.0`, `selection_mode=complete`,
1.092 frames, 1.094 source refs và 1.097 generated refs; validator đọc lại
mọi checksum/relative ref trên output thật. Có 983 train PNG và 109 held-out
PNG; split checksum canonical vẫn là
`sha256:2b87b3b5ee95b4382bf42a58ab932a5520f06b39f749ba407679764a592c0228`.
Manifest canonical checksum mới:
`sha256:e5448ebf02f8c15b2aca7c0861b5fc2237b75ad041ec149b4d6beb064789f1a1`;
manifest byte SHA-256:
`25b94275f55f12eb01529fe53b6b45c4c23df8e5b96d3badb49a8babf4673f43`;
script SHA-256:
`50e1116eeda6b8ee029d5798c888e0e804f2b0a4328facd6acbbaa1b56817e24`.

SHA-256 của 1.094 file nguồn được kê trước/sau preparation và `cmp` pass.
Smoke ba frame từ source `data/` ở mode `sample` pass. Codex chạy
`.venv/bin/pytest tests/test_reconstruction/test_rec01_dataset.py -q`
(36 pass), `.venv/bin/pytest tests/test_contracts tests/integration -q`
(96 pass), Ruff check/format `src tests scripts/torwic` pass,
`git diff --check` pass. Output trong `data/` bị Git ignore theo policy. File
`data/torwic_slam/dataset_manifest.yaml` là scaffold rỗng có sẵn, không được
script này sửa; manifest chuẩn của preparation nằm tại output root nêu trên.
Evidence trước đó từ ổ ngoài chỉ là historical proof, không thay thế run này.

### Owner storage correction (2026-09-24)

Owner chốt một canonical dataset root tại `data/torwic_slam/`: tất cả 1.092
usable RGB nằm duy nhất trong `normalized/aisle_cw/rgb_frames/`, train/held-out
chỉ là role ID trong `derived/aisle_cw/benchmark_split.json`. Split vẫn có
`evaluation_only` data class và chỉ orchestration/evaluator được đọc theo
vai trò; generic product resolver không được auto-load. Traversal manifest
ở `derived/aisle_cw/preparation_manifest.json`; dataset-level manifest ở
`dataset_manifest.yaml`. Không dùng `data/torwic_slam_rec01` làm output nữa.
Các acceptance marks/evidence phía trên là lịch sử, chưa chứng minh layout mới;
task mở lại ở `IN_PROGRESS` theo lifecycle của harness. Trước edit đã thấy
1.092 PNG và hai JSON trong canonical dirs, nhưng JSON hiện vẫn giữ refs của
layout cũ (`normalized/000000.png`, `derived/Aisle_CW/...`) và YAML rỗng.
Phải audit và sửa reproducible publisher/validator trước khi DONE; không ghi
đè file hiện có mà chưa xác minh provenance/checksum.

### Canonical publication evidence (2026-09-24)

`CanonicalDatasetPreparer` trong `scripts/torwic/canonical_dataset.py` là
publisher cho source layout `raw/`: stage và verify trước, từ chối target RGB/
metadata khác bytes, chỉ migrate preparation manifest cũ khi source inventory
và frozen split khớp; `dataset_manifest.yaml` là dataset-level index có schema,
license/source reference, canonical roots và checksum trỏ đến traversal
manifest. JSON serialization trong `.yaml` là YAML 1.2 hợp lệ, tránh thêm
dependency. `prepare_dataset.py` từ chối `--output-root` thứ hai khi source
đã được sắp. Flat download compatibility chỉ là legacy adapter/test; không
được dùng làm canonical output của track.

Command thật:
`.venv/bin/python -m scripts.torwic.prepare_dataset --dataset-root data/torwic_slam --traversal-id Aisle_CW --frame-ids 0-117,154-527,565-936,973-1091 --held-out-ids 118-153,528-564,937-972`.
Canonical output: 1.092 PNG tại `normalized/aisle_cw/rgb_frames/`, không có
PNG trong `evaluation_only/aisle_cw/`; train/held-out IDs lần lượt 983/109
trong `derived/aisle_cw/benchmark_split.json`. Cả 1.092 generated RGB refs
đều `product_input`; split ref là `evaluation_only`. Traversal manifest
`derived/aisle_cw/preparation_manifest.json` schema 1.0 mode `complete`,
1.094 source refs và 1.096 generated refs. Validator re-read toàn bộ refs,
source/normalized bytes, timestamps, calibration, split, provenance và
dataset-level index, pass.

- Preparation canonical checksum:
  `sha256:3deaeab2906ea988896977c6b736c36f852ff277b62638c363ab16463a1f9208`;
  byte SHA-256 `10c917dd4442fd60dc8d8526ffcf2de72e8a170b58d2804881a2222ddff98ebb`.
- Dataset index canonical checksum:
  `sha256:e8b994165e21df766a5e9abbec236de3f27a5d64f10e8e581f62362e1cbb5691`;
  byte SHA-256 `c1f734a819664581660337e0ce5e7ad590530ce9d98189aef22ab3dab831239d`.
- Split canonical checksum unchanged:
  `sha256:2b87b3b5ee95b4382bf42a58ab932a5520f06b39f749ba407679764a592c0228`.
- Script SHA-256: `prepare_dataset.py`
  `24ff7f71c8ca3b271e6224bb17493d9b795f87aa412155d080e6af7d3ff1103e`,
  `canonical_dataset.py`
  `8294f09b4ebe759b362dd2fe627d00501d4d04786063fb93b2c904a346dc1377`.

SHA-256 list của 1.094 raw RGB/calibration/timestamps files trước/sau
giống nhau (`cmp` exit 0). Broken evaluation-only GT symlink hiện có được
chỉnh relative target thành `../../raw/global/groundtruth_map.ply` và resolve
đúng, không sửa raw GT bytes. `data/torwic_slam_rec01` đã không còn tồn tại
khi audit cuối; hai script migration có sẵn (nay ở `scripts/torwic/migrations/rec01_merge.py`,
`rec01_merge.sh`) được giữ nguyên, không stage. Các output cũ được đối chiếu
với raw và canonical generated refs; legacy preparation manifest được lưu
tạm ở `/tmp` trong lúc migration.

Canonical REC-01 gate PASS. Focused test `.venv/bin/pytest tests/test_reconstruction/test_rec01_dataset.py -q`:
41 pass, gồm canonical in-place, no second root, idempotence, forged held-out
path, changed RGB và changed dataset index. `.venv/bin/pytest tests/test_contracts tests/integration -q`:
96 pass. Ruff check/format `src tests scripts/torwic` pass, Python function
length/arity AST check pass. REC-01 không tạo runtime reconstruction resolver;
REC-02A/REC-03 phải dùng split reconstruction IDs khi đưa frame vào pipeline,
và evaluator thuộc owner khác chỉ dùng held-out IDs. REC-01 artifact tự nó
không chứng minh privacy, full decode, GPU reconstruction hoặc E2E handoff.

## Correction Task (2026-09-24)
1. Không tạo data/torwic_slam_rec01 nữa.
2. Merge valid REC-01 outputs vào canonical:
   data/torwic_slam/normalized/aisle_cw/
   data/torwic_slam/derived/aisle_cw/
   data/torwic_slam/evaluation_only/aisle_cw/
3. normalized/rgb_frames chứa toàn bộ 1092 usable frames.
4. benchmark_split.json giữ:
   train = 983 IDs
   held_out = 109 IDs.
5. EvaluationRunner và EX-REC resolve cùng physical rgb_frames, nhưng theo hai ID sets khác nhau.
6. Không duplicate held-out PNG.
7. Hoàn thiện dataset_manifest.yaml.
8. Migrate useful manifest/provenance từ torwic_slam_rec01.
9. Verify checksum + tests.
10. Xóa torwic_slam_rec01 sau khi audit không còn unique artifact.
