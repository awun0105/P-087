# SIM-03 — Physics Enrichment

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `DONE` |
| Owner | Đạt |
| Target milestone | `M2` |

## 2. Goal

Attach ColliderSpec/physics metadata to a new revision of the same SceneIR schema.

## 3. Why This Task Exists

Cross-track architecture forbids a competing PhysicsScene format.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-02 generated colliders; SIM-02A edit semantics.
- SCENE-09 SceneIR contract.

## 5. Input Contract

- SceneIR and generated/validated collider records.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Physics-enriched SceneIR revision with checksum/provenance.
- Revision invalidation record.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/`
- `src/models/contracts/scene.py` only with EX-SCENE/PRODUCT review
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE`; enrich the shared SceneIR schema, do not create `PhysicsScene.json`.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

1. Tạo package `src/services/simulation/enrichment/` với `service.py`.
2. Hàm `enrich_scene_physics`:
   - Map và gắn các `ColliderSpec` tương ứng vào từng `SceneObject` theo `object.id` và `parent_frame`.
   - Tự động sinh proxy collider an toàn cho các vật thể chưa có collider (`auto_generate_missing=True`).
   - Gắn Ground Plane collider phẳng chuẩn hóa độ dày 0.05m vào `scene.environment.collider_ref` (Safeguard 1).
   - Nâng số hiệu bản sửa đổi (`scene_revision`) tuần tự hoặc theo cấu hình.
   - Ghi nhận `provenance`: `producer_stage: ST-PHYSICS-ENRICH`, `previous_revision`, generator metadata.
   - Đóng dấu mã băm xác thực `scene_ir_checksum` bằng `canonical_content_checksum`.
3. Kiểm thử với `tests/test_simulation/test_enrichment.py`:
   - Xác thực schema, tính độc lập của checksum, tự sinh collider, bắt lỗi lệch frame/trùng ID, và tích hợp với Preflight (SIM-04).

## 10. Tests

- Enrichment/roundtrip/ref unit tests.
- Missing object/geometry and duplicate collider negative tests.
- EX-PRODUCT/Preflight direct consumer contract test.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [x] Physics revision validates same SceneIR schema.
- [x] All active required entities have traceable physics refs where policy requires.
- [x] Old candidate/reports are invalidated via revision increment and new content checksum.
- [x] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

- **Implementation:** `src/services/simulation/enrichment/service.py` & `src/services/simulation/enrichment/__init__.py`.
- **Validation:** `pytest tests/test_simulation/test_enrichment.py -v` (7 passed in 5.67s).
- **Full Track Suite:** `pytest tests/test_simulation/ -v` (39 passed in 1.62s).
- **Linter & Formatting:** `ruff check .` and `ruff format --check src/ tests/` (100% clean).
- **Proof:**
  - `test_enrichment_creates_valid_scene_revision_and_checksum`: `rev-001` -> `rev-002`, `scene_ir_checksum` verified against canonical content.
  - `test_enrichment_auto_generates_colliders_for_all_objects`: Mọi vật thể được cấp collider hợp lệ.
  - `test_enrichment_rejects_mismatched_parent_frame`: Bắt lỗi khi parent_frame != object.local_frame.
  - `test_enrichment_rejects_duplicate_colliders`: Bắt lỗi trùng lặp collider_id.
  - `test_enriched_scene_passes_deterministic_preflight`: Scene sau khi enrich chuyển từ Preflight `FAIL` sang `PASS`.


