# REC-05 — Coarse Voxel Geometry & Collision Mesh via splat-transform (OpenMVS as Fallback)

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-REC` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | `@awun0105` |
| Target milestone | `M1/M2` |

## 2. Goal

Tạo coarse voxel geometry & collision mesh artifact (`collision.glb`) từ Brush 3DGS thông qua `splat-transform` GPU voxelization và robot capsule carving, phục vụ trực tiếp cho collider downstream trong MVP. OpenMVS giữ vai trò Secondary Fallback.

## 3. Why This Task Exists

Cung cấp hình học va chạm tĩnh và phân tách không gian lưu thông cho robot mà không cần gánh nặng build native C++/CUDA và rủi ro bản quyền AGPLv3 của OpenMVS. Vẫn bảo toàn nguyên tắc bất biến `Visual ≠ Geometry ≠ Physics`.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md), [Audit #4a](../../../audits/04a_splat_transform.md).

## 4. Dependencies

- REC-04 output: Brush `visual.ply`.
- REC-06 pha xác nhận anchor/transform sang canonical meter đã hoàn tất; không
  đợi final verification/DONE của REC-06 (xem Integration §3.3).
- REC-03 COLMAP model cho OpenMVS fallback.
- `splat-transform` (v3.6.6) Node.js/GPU environment.
- Locked OpenMVS Docker environment (làm fallback nếu spike không đạt).

## 5. Input Contract

- REC-04 Brush `visual.ply` (đã qua structural validation).
- Confirmed metric transform/anchor record và checksummed source refs; tạo working
  derivative theo mét, không sửa master PLY và không coi arbitrary SfM unit là mét.
- Robot footprint config: capsule height, capsule radius cho indoor carving.
- Voxel resolution config: mặc định `0.05m` (5cm).

Không đọc evaluation-only data hoặc private temp folder ngoài contract đã nêu.

## 6. Output Contract

- `GeometryArtifact` trỏ tới `collision.glb`.
- Voxel metadata: resolution, bounding box, flood fill seed position.
- Provenance của metric derivative và transform đã áp dụng để REC-06 tránh double scaling.
- Geometry/runtime/config provenance và SHA-256 checksum.

Output quan trọng phải có schema/version phù hợp, checksum, provenance và resolvable artifact refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/reconstruction/adapters/`
- `src/services/reconstruction/rgb/`
- `tests/test_reconstruction/`

Không sửa implementation của EX-SCENE/EX-SIM/EX-PRODUCT. Shared contract change cần producer + consumer review.

## 8. Tool / Repository Strategy

**Primary P0 Strategy (`playcanvas/splat-transform` v3.6.6):**
- Trích xuất GPU Voxelization từ Gaussian density field:
  - `--filter-cluster` & `--seed-pos`: Loại bỏ các cụm voxel trôi nổi (floaters), chỉ giữ cụm liên thông.
  - `--voxel-carve`: Dùng capsule robot kho khoét khoảng không di chuyển (`navigable cavity`).
  - `--collision-mesh smooth`: Marching Cubes kết hợp coplanar face merge tạo `collision.glb` watertight.
- **Hai Safeguards bắt buộc:**
  - ❌ **Không dùng mesh làm sàn robot:** Mặt sàn sẽ do `SIM-01` tạo bằng `USD Analytic Ground Plane` phẳng tuyệt đối.
  - ❌ **Chân kệ / vật thể mỏng:** Hỗ trợ cơ chế thay thế bằng Box Collider (`SIM-02` / Studio HITL).

**Secondary Fallback Strategy (`cdcseacave/openMVS`):**
- Nếu bài test Spike trên `Aisle_CW` không thỏa mãn điều kiện di chuyển của robot, kích hoạt fallback containerized OpenMVS (`InterfaceCOLMAP` $\rightarrow$ `DensifyPointCloud` $\rightarrow$ `ReconstructMesh`).

## 9. Qualification Spike trên `Aisle_CW`

Trước khi chấp nhận primary geometry; giữ OpenMVS fallback nếu spike không đạt:
1. Chạy 3 cấu hình voxel resolution trên file Brush PLY của `Aisle_CW`:
   - Config A: `0.10m`
   - Config B: `0.05m` (Baseline)
   - Config C: `0.025m`
2. Kiểm tra 4 tiêu chí cốt lõi:
   - Aisle không bị ghost-block.
   - Chiều rộng lối đi không bị phình/hẹp quá sai số an toàn robot ($10-20\text{cm}$).
   - Kệ hàng và pallet chính tồn tại đúng vị trí.
   - Chạy test động trong Isaac Sim với sàn USD Plane: kiểm tra các path `CLEAR / BLOCKED`.
3. **Quy chuẩn thông số Voxel Carving (theo ADR 0001):**
   - Tọa độ điểm hạt giống đục rỗng lối đi (`navigation_seed_world`): Được trích xuất tự động từ tọa độ Camera ở khung hình đầu tiên (Frame 0) trong quỹ đạo camera (trajectory), đảm bảo nằm chắc chắn trong lối đi trống mà không cần phỏng đoán.
   - Hình trụ ảo đại diện cho robot AMR: Bán kính $r = 0.35\text{ m}$, chiều cao $h = 1.20\text{ m}$.
4. Nghiệm thu: Hành vi va chạm đúng trong Isaac Sim ➔ **PASS**.

## 10. Tests

- Command/config builder unit tests cho `splat-transform`.
- Missing/invalid PLY negative tests.
- Missing/unconfirmed anchor phải chặn metric voxelization; test scale propagation
  và double-scaling với REC-06.
- Synthetic/small PLY to `collision.glb` smoke test và topology verification.
- Fallback OpenMVS adapter smoke test.

## 11. Definition of Done

- [ ] Geometry/Collision artifact `collision.glb` được tạo bằng `splat-transform` adapter.
- [ ] Format/coordinate metadata/checksum/provenance đầy đủ theo `GeometryArtifact`.
- [ ] Spike trên `Aisle_CW` được thực hiện và ghi nhận kết quả rõ ràng.
- [ ] Artifact đủ để EX-SIM (`SIM-02`) consume làm primary environment collider.
- [ ] Focused tests pass; evidence/limitations được ghi đầy đủ.

## 12. Result / Evidence

Pending implementation.
