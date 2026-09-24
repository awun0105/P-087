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
  trước normalize. Mount hiện có `calibrations.txt` ở root, còn `Aisle_CW/`
  chứa `image_left/` và `frame_times.txt`; các layout `global/` hoặc
  `traversals/` trong ví dụ không phải input thật.
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
- Product RGB và held-out RGB ở hai boundary khác nhau; manifest ghi relative
  path/data class/checksum cho từng file được chọn, cùng source frame ID và
  timestamp. Không lộ private mount path trong output hay lỗi.
- Split frozen đặt tại `derived/Aisle_CW/benchmark_split.json` theo quyết định
  owner và ví dụ `DATASET_PLAYBOOK.md` §12; artifact này vẫn mang
  `evaluation_only` data class, không được product reader nạp chỉ vì nó nằm
  trong `derived/`. Held-out ảnh vẫn ở `evaluation_only/`.

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
   `evaluation_only/` khỏi product input. Fail rõ ràng cho missing/duplicate/
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

## 10. Tests

- Dataset layout/parser unit tests.
- Raw immutability và checksum negative test.
- Small traversal preparation smoke; output manifest validates.
- Existing-output/partial-output refusal và wrong-layout failure test.
- Real output refs resolve; generated checksums match actual bytes; train và
  held-out không dùng chung product-readable folder.

Phân biệt local/mock proof với real tool/GPU smoke trong Result.

## 11. Definition of Done

- [x] Selected traversal chuẩn bị được từ raw source bằng command versioned trong repo.
- [x] `raw/` không bị mutate; normalized/derived/evaluation-only tách đúng.
- [x] Split, calibration, timestamp và provenance có checksum.
- [x] Manifest output versioned; mọi selected RGB/metadata/split có relative
      refs và checksums resolve được; nguồn source IDs/timestamps khớp 1-to-1.
- [x] Hold-out bị cô lập khỏi product input; raw/source mount bất biến;
      không nhận false privacy/real reconstruction proof từ REC-01.
- [x] Focused tests và required handoff proof pass; evidence/limitations được ghi.

## 12. Result / Evidence

DONE (2026-09-24). Strategy: project-owned offline parser/copier/validator tại
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
