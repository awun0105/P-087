# Audit #4a — `playcanvas/splat-transform`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Repository:** [`playcanvas/splat-transform`](https://github.com/playcanvas/splat-transform)  
> **Version:** 3.6.4  
> **Commit audit:** `7d1904463aa4a1bfce5f60e1384b76f36697ee2e` (2026-09-23)  
> **License:** MIT  
> **Ngày audit:** 2026-09-24  
> **Trạng thái:** Hoàn tất Audit #4a (Core Utility Deep Dive)

---

## Kết luận trước

> **`splat-transform` nên được xem là một Core Utility Candidate rất mạnh của Real2Sim Studio, không chỉ là dependency phụ của SuperSplat.**

Nó không thay COLMAP, Brush, OpenMVS, SAM2 hay Isaac. Thứ nó làm rất tốt là **cầu nối giữa Brush 3DGS → artifact chuẩn hóa → Web → QA → optional collision fallback**.

Phân loại đề xuất:

```text
playcanvas/splat-transform

Tier-0 Core Utility Candidate

EX-REC          HIGH
EX-SCENE        MEDIUM
EX-SIM          MEDIUM / fallback
EX-PRODUCT      VERY HIGH
QA/Artifact     VERY HIGH
```

---

## 1. Các vấn đề giải quyết thực tế

Codebase hiện có:
- Đọc, kiểm tra cấu trúc (Read / Validate / `readFileInfo`).
- Chuyển đổi và chuẩn hóa hệ tọa độ (Transform / Coordinate adaptation).
- Lọc nhiễu, làm sạch dữ liệu (Filter NaN/Inf, `filterFloaters`, `filterCluster`).
- Gom nhóm và giảm tải (Merge, Decimate uniform & adaptive).
- Sinh phân cấp chi tiết (LOD generation, Streamed SOG, Morton spatial sorting).
- Đo đạc thống kê chất lượng (Statistics, `fillRatio` overdraw metric).
- Render 3DGS headless trên GPU (WebP frames, camera paths, walkthroughs).
- Voxel hóa và xử lý không gian di chuyển (Voxelization, capsule carve, floor fill).
- Trích xuất mesh va chạm (Marching Cubes, watertight voxel faces → `collision.glb`).
- Hỗ trợ định dạng phân phối Web (SOG, Streamed SOG, compressed PLY).

---

## 2. Hỗ trợ trực tiếp metadata của Brush

`splat-transform` đọc hiểu trực tiếp metadata của Brush:
```text
comment SplatRenderMode:
    default
    mip
    2dgs
```
và bảo toàn metadata khi ghi lại PLY. Đường kết nối `Brush → visual.ply → splat-transform` có test coverage và mã nguồn cụ thể trong `read-ply.ts` và `splat-model.ts`.

---

## 3. Ứng dụng #1: Validate VisualArtifact (`ST-GS-VALIDATE`)

Hàm `readFileInfo(...)` cho phép đọc metadata cấu trúc mà không cần decode toàn bộ scene:
- Xác nhận file thực sự là Gaussian (`gaussian = true`).
- Kiểm tra số lượng splats (`numGaussians`), số cấp LOD (`numLods`).
- Số dải SH bands, danh sách layers, extra columns.

Áp dụng sau `REC-04` Brush:
```text
Brush PLY → readFileInfo() → Structural validation → Reject malformed/non-Gaussian artifact
```

---

## 4. Ứng dụng #2: Thống kê & Quality Gate (`fillRatio`)

Hệ thống streaming statistics tính toán min, max, mean, stdDev, NaN count, Inf count, histogram và đặc biệt là **`fillRatio`** (ước lượng số lớp overdraw trung bình).

Chỉ số `fillRatio` giúp phát hiện các scene bất thường (pathological scenes: scale hạt quá lớn, overdraw cực cao có nguy cơ làm treo GPU trình duyệt) trước khi phát hành artifact sang Web Studio.

---

## 5. Ứng dụng #3: Dọn dẹp NaN/Inf và Lọc nhiễu (`filterFloaters`)

- Cung cấp `--filter-nan` loại bỏ tự động các điểm không hợp lệ (non-finite position, zero-norm rotation, invalid scale).
- Hàm GPU-based `filterFloaters()`: Voxel hóa trên GPU và kiểm tra mức độ đóng góp (opacity/extent contribution) của từng Gaussian để loại bỏ các hạt trôi nổi/nhiễu ngoài biên một cách thông minh.

---

## 6. Ứng dụng #4: Phân phối Web tối ưu (SOG & Streamed SOG LOD)

- **Morton spatial sorting**: Sắp xếp không gian theo mã Z-order tối ưu bộ nhớ đệm.
- **Adaptive Decimation**: Giảm số lượng Gaussian có kiểm soát sai số cục bộ (giữ chi tiết vùng quan trọng, nén mạnh vùng phẳng).
- **SOG / Streamed SOG**: Nén và chia nhỏ scene thành cây phân cấp không gian (`lod-meta.json` + multiple SOG chunks) cho các kho bãi quy mô lớn (hàng chục triệu hạt).

---

## 7. Ứng dụng #5: Fallback Collision Mesh cho EX-SIM

`splat-transform` sở hữu pipeline voxel hóa hoàn chỉnh:
```text
Gaussian ellipsoids
        ↓ (GPU voxelization)
SparseVoxelGrid / Sparse Octree
        ↓ (Marching Cubes hoặc Voxel Faces)
scene.collision.glb
```

Kèm các cờ xử lý môi trường trong nhà (indoor warehouse):
- `--filter-cluster` & `--seed-pos`: Giữ cụm voxel liên thông chính, loại bỏ các ốc đảo rời rạc.
- `--voxel-carve`: Dùng capsule di chuyển từ seed point để khoét khoảng trống lưu thông (navigable cavity).
- `--voxel-floor-fill`: Vá các lỗ hổng nhỏ trên mặt sàn do khuyết điểm tái tạo.

**Quy tắc bất biến**: Mesh va chạm từ 3DGS này **chỉ dùng làm Fallback hoặc Baseline đối chứng** khi OpenMVS geometry gặp sự cố; không thay thế OpenMVS làm primary physical truth.

---

## 8. Cảnh báo quan trọng: Hệ tọa độ (Coordinate Convention)

`splat-transform` có quy ước chuyển đổi riêng (ví dụ `Transform.PLY` xoay 180° quanh trục Z: `(x, y, z) → (-x, -y, z)`).

**Tuyệt đối không để quy ước của `splat-transform` trở thành canonical coordinate của Real2Sim Studio**. Phải thực hiện chuyển đổi tại adapter boundary:
```text
Real2Sim Canonical Coordinate → SplatTransformAdapter → PLY / PlayCanvas convention
```

---

## 9. Cảnh báo: Định dạng Canonical vs. Delivery Derivative

- File `master.ply` sinh ra từ Brush là **immutable canonical artifact**.
- File `scene.sog` và `lod/` là **delivery derivatives** phục vụ Web rendering, không được ghi đè lên file PLY gốc.

---

## 10. Kiến trúc Đề xuất: `SplatArtifactProcessor`

Dự án nên bọc công cụ này qua một abstraction:

```python
class SplatArtifactProcessor:
    def validate(self, artifact_ref: ArtifactRef) -> ValidationResult: ...
    def inspect(self, artifact_ref: ArtifactRef) -> SplatStats: ...
    def clean(self, artifact_ref: ArtifactRef) -> ArtifactRef: ...
    def build_web_derivative(self, artifact_ref: ArtifactRef, lod: bool) -> ArtifactRef: ...
    def build_collision_fallback(self, artifact_ref: ArtifactRef) -> ArtifactRef: ...
```

Thực thi thông qua tiến trình Node.js độc lập (`real2sim-splat-worker`, Node >= 22) theo nguyên tắc ranh giới tiến trình (process boundary).

---

## 11. Phân biệt Bản chất: Occupancy Extraction vs. Surface Reconstruction

Audit source-level của `splat-transform` (GPU voxelizer, `filterAndFillBlocks`, `voxel-carve`, Marching Cubes) khẳng định:
1. **`splat-transform` không làm Surface Reconstruction:** Thuật toán tính Mahalanobis distance từ Gaussian ellipsoids tới từng voxel, tích lũy mật độ $\text{finalOpacity} = 1 - \exp(-\Sigma \text{density})$, rồi gán SOLID nếu $\ge \text{threshold}$ (mặc định 0.1, voxel 0.05m). Đây là **Occupancy Extraction từ Gaussian Density**, không phải stereo matching quang học.
2. **`--voxel-carve` tối ưu cho Robot kho:** Nhận chiều cao/bán kính capsule của robot, khoét khoảng không lưu thông (`navigable cavity`), trả lời chính xác câu hỏi: *"Với kích thước robot này, đâu là free space và đâu là vùng bị chặn?"*.
3. **Hai Safeguards cốt tử giải quyết triệt để rủi ro hình học:**
   - **Safeguard 1 (Mặt sàn):** Không bao giờ dùng mesh 3DGS làm mặt sàn robot! Tách sàn thành **`USD Analytic Ground Plane`** (hoặc flat box phẳng tuyệt đối). Triệt tiêu 100% rủi ro nảy bánh xe hay ma sát bất thường trong Isaac Sim.
   - **Safeguard 2 (Vật thể mỏng / Chân kệ):** Nếu voxel 5cm làm biến dạng chân kệ hoặc pallet, kỹ sư sử dụng tính năng Studio **"Replace Collider with Box/OBB"** (Human-in-the-Loop).

---

## 12. Code Reuse Matrix cho `splat-transform`

| Tính năng | Track ứng dụng | Quyết định | Ghi chú tích hợp |
| :--- | :--- | :--- | :--- |
| Đọc Brush PLY & preserves metadata | `EX-REC` (`REC-04`) | **REUSE-HIGH** | Input cho toàn bộ post-processing |
| `readFileInfo()` cấu trúc | `EX-REC` (`REC-04`) QA | **REUSE-HIGH** | Structural validation trước publication |
| Thống kê & `fillRatio` | `EX-REC` / QA Quality Gate | **ADAPT-HIGH** | Đo overdraw, chặn cảnh bất thường |
| Lọc NaN/Inf | `EX-REC` Post-processing | **REUSE-HIGH** | Clean artifacts tự động |
| Sắp xếp Morton & Decimation | `EX-PRODUCT` Tối ưu hóa | **REUSE-HIGH** | Chuẩn bị dữ liệu web |
| SOG / Streamed SOG LOD | `EX-PRODUCT` Web Delivery | **REUSE-HIGH** | Derivative format chính cho Viewer |
| Voxelization + Marching Cubes | `EX-SIM` (`SIM-02`) Primary P0 | **ADAPT-CORE** | Tạo environment `collision.glb` (kết hợp USD Plane sàn) |
| Indoor capsule carve & floor fill | `EX-SIM` Navigation space | **REUSE-CORE** | Khoét không gian di chuyển cho AGV/AMR |
| Headless WebP rasterizer | QA / Walkthrough video | **ADAPT** | Hỗ trợ smoke test không cần UI |
| Thay thế OpenMVS mesh trong MVP | `EX-REC` / `EX-SIM` | **QUALIFY-ADOPT** | Thay thế thành công nếu Spike Aisle_CW pass |

---

## 13. Kế hoạch Qualification Spike trên `Aisle_CW`

Thực hiện bài test 1-2 tiếng với file Brush PLY thực tế của cảnh `Aisle_CW` trên 3 cấu hình voxel (`0.10m`, `0.05m`, `0.025m`):
1. **Ghost blocker check:** Lối đi (aisle) có bị mảng voxel ma nào chặn đứng không?
2. **Clearance check:** Chiều rộng lối đi có bị phình/hẹp vượt quá sai số an toàn ($10-20\text{cm}$) của robot không?
3. **Obstacle existence:** Các dãy kệ và pallet chính có tồn tại và cản được va chạm không?
4. **Isaac Sim dynamic test:** Khi nạp sàn USD Plane riêng biệt, xe AMR chạy các path thử nghiệm có báo `CLEAR / BLOCKED` chính xác không?

> **Tiêu chuẩn nghiệm thu:** *"Visual của mesh va chạm không cần đẹp; miễn là hành vi va chạm (collision behavior) trong Isaac Sim đúng ➔ PASS và chính thức loại OpenMVS khỏi P0."*

