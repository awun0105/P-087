# 0007 Pipeline v2: video → scene 3D theo vật chỉnh sửa được → USD lai cho Isaac Sim

Date: 2026-09-30

## Status

Accepted (hướng kiến trúc) — Tech Lead / owner (Quân) chốt ngày 2026-09-30 sau khi audit repo
tham chiếu và tra cứu tài liệu Isaac Sim. Phương pháp cụ thể cho chặng 5–7 (Gaussian Grouping
hay ObjectGS, TSDF hay SuGaR/Frosting cho mesh nền) **chưa khoá**: chọn theo số liệu của pha A
(chạy thử). Bổ sung ADR 0006 (tách vật) — SAMPro3D-trên-hộp trở thành đường tạm, không bị xoá.

## Context

- Bài toán owner đặt: chuyển **video** thành **scene 3D chỉnh sửa được** — thêm, xoá, sửa vật
  thể, vá chỗ vật từng che, gán nhãn, có khối lượng/thuộc tính vật lý — rồi **xuất sang Isaac
  Sim** để mô phỏng. Train lại hay không chỉ là chi phí, không phải tiêu chí thiết kế.
- Hiện trạng (VERIFIED, 2026-09-30): 3DGS hệ mét, collision mesh voxel và hộp vật thể **chỉ
  cùng hệ toạ độ** (Gaussian→mesh trung vị 0,22 m trên `job-ac2`), **không ghép theo vật**.
  SAMPro3D có tính tập Gaussian của từng vật nhưng chỉ giữ hộp; ẩn/xoá vật chỉ đổi SceneIR và
  màu hộp, hình 3DGS và mesh không đổi. Gói USD hiện có: collision mesh môi trường khoét vùng vật,
  collider hộp, GroundPlane; chưa có hình ảnh, khối lượng, vật liệu vật lý, nhãn ngữ nghĩa.
- Isaac Sim nhận gì (tra cứu 2026-09-30, nguồn ở cuối):
  - vỏ scene là OpenUSD; mesh/URDF/MJCF được chuyển sang USD khi import; `.usdz` phải được
    tham chiếu từ stage `.usd`/`.usda`, không mở làm stage gốc rồi thêm asset;
  - **hình ảnh** nhận cả mesh + vật liệu lẫn **Gaussian 3DGS** (NuRec/`ParticleField3DGaussianSplat`,
    Isaac Sim ≥ 5.0); NVIDIA khuyến nghị ParticleField cho asset mới (NuRec sẽ bị thay);
    chuyển PLY → USD bằng 3DGRUT (Apache-2.0);
  - **Gaussian không có va chạm**; va chạm cần `UsdPhysics` collider. Triangle mesh chỉ dùng
    cho vật **tĩnh**; rigid body động dùng convex decomposition hoặc SDF (triangle mesh bị rơi về
    convex hull);
  - SimReady: mỗi asset có đơn vị (mét, kg), Collider, **Mass (kg)**, **Physics Material**
    (ma sát tĩnh/động, restitution, mật độ), RigidBody ở prim gốc; nhãn qua
    `UsdSemantics.LabelsAPI` (Isaac ≥ 5.0);
  - Occupancy Map Generator chỉ thấy hình học **có bật collision** — vật cản không có collider
    thì robot không thấy khi lập bản đồ;
  - LiDAR RTX có trúng Gaussian không: tài liệu chính thức không nói (**UNKNOWN**).
- Audit repo tham chiếu (2026-09-30): xem
  [`docs/execution/audits/10_pipeline_v2_methods.md`](../execution/audits/10_pipeline_v2_methods.md).

## Decision

1. **Dạng đích = scene theo vật, xuất USD lai.** Nền và mỗi vật là một khối riêng:

   ```
   /World (Z-up, metersPerUnit = 1, kilogramsPerUnit = 1)
   ├── Environment: Visual = Gaussian nền đã vá (ParticleField)
   │                Collision = triangle mesh tĩnh + mặt sàn; Labels (floor/shelf/wall…)
   └── Objects/<id> (Xform): Visual = Gaussian của riêng vật (ParticleField)
                             Collider = convex decomposition (hoặc SDF)
                             RigidBody + Mass (kg) + Physics Material; Labels (pallet/box…)
   ```

   Hình ảnh dùng Gaussian (đúng hướng real-to-sim của NVIDIA); mesh dùng cho vật lý và bản đồ
   dẫn đường. Mesh có texture là **tuỳ chọn** (engine không đọc được Gaussian, hoặc nếu LiDAR
   cần mesh proxy).
2. **Mười chặng** (phương pháp chính, dự phòng trong ngoặc):
   1. frame + lọc chất lượng — giữ; 2. camera COLMAP — giữ, sửa scene vỡ nhiều mảnh (loop
   closure/GLOMAP); 3. tỉ lệ mét + trọng lực — giữ; 3b. **bản xem nhanh Brush** — giữ để người
   dùng thấy scene sau vài phút;
   4. **mask vật theo video**: SAM2 lan mask, mỗi vật một ID qua các frame;
   5. **3DGS có nhãn vật**, train trong hệ mét, ràng buộc độ sâu/pháp tuyến (MoGe) — Gaussian
   Grouping (ObjectGS);
   6. **hình học + collider**: nền = TSDF từ độ sâu render → triangle mesh tĩnh (so với
   SuGaR/Frosting trong pha A); vật = TSDF riêng → khép kín → CoACD phân rã lồi; thể tích →
   khối lượng;
   7. **vá nền sẵn** cho mọi vùng vật che: render nền không có vật → LaMa → fine-tune Gaussian
   nền; vá lỗ mesh sàn/kệ; chạy một lần lúc dựng để thêm/xoá/sửa vật là tức thì;
   8. **nhãn + vật lý**: gợi ý nhãn (CLIP) so với danh mục asset Isaac, người dùng xác nhận;
   bảng mật độ/ma sát theo nhãn có nguồn; khối lượng = mật độ × thể tích, sửa tay được; tuỳ chọn
   thay vật bằng asset Isaac cùng loại (`asset_ref`);
   9. **Studio theo vật**: nền và từng vật là các khối Gaussian riêng trong PlayCanvas; chọn,
   ẩn, xoá, dịch/xoay/co giãn (gizmo), nhân bản, thêm từ thư viện/hình khối, đổi nhãn/khối lượng,
   hoàn tác, đo khoảng cách; mỗi thao tác là một revision SceneIR ở backend;
   10. **xuất + kiểm**: USD lai (ParticleField qua 3DGRUT), preflight mở rộng theo SimReady,
   validation Isaac (SIM-06..09): nạp, vật lý ổn định, occupancy map, đường đi robot.
3. **Frosting không nằm trong đường chính.** Vật trong kho là vật cứng: dịch/xoay là đổi Xform của
   khối Gaussian, không cần Gaussian gắn mesh. Frosting không tách theo vật. Giữ SuGaR/Frosting
   làm **ứng viên mesh nền** trong pha A và cho vật biến dạng/có khớp (ngoài phạm vi hiện tại).
4. **Contract:** giữ `SceneIR`/`SceneObject` (đã có `visual_ref`, `collider`, `semantic_class`,
   `asset_ref`); bổ sung trường vật lý có kiểu (khối lượng, vật liệu) và các artifact mới (Gaussian
   theo vật, Gaussian nền đã vá, mesh collider vật). Thay đổi shared contract có versioning và
   review producer/consumer theo TEAM_EXECUTION_CONTRACT.
5. **Tính toán:** chặng 4–7 chạy trên GPU thuê (ước tính 16–24 GB, INFERENCE), cùng máy thuê để
   host/xử lý backend theo ADR 0003. GPU 4 GB cục bộ chỉ dùng phát triển với video ngắn.
6. **Phạm vi PRD:** owner kéo vào phạm vi hiện tại các mục đang là P1/P2 của PRD: xoá vật kèm vá
   nền (3D inpainting), gợi ý nhãn, thay vật bằng asset. PRD cập nhật tương ứng.
7. **Lộ trình:** A chạy thử (script chặng 4–7 + 10 trên đoạn 37 s `job-123`, GPU thuê) → B backend
   (stage, artifact, contract v2, image GPU worker) → C Studio v2 → D bộ xuất USD lai + preflight v2
   + validation Isaac trên máy RTX → E deploy (phần còn lại ADR 0003).

## Alternatives Considered

1. **Chỉ lưu tập Gaussian của SAMPro3D, không train lại** — rẻ nhưng ranh giới vật phụ thuộc
   3DGS chưa có nhãn, không có vá nền; không đáp ứng bài toán thêm/xoá/sửa trọn vẹn.
2. **Mesh có texture làm hình chính (kiểu game truyền thống)** — Isaac nhận được, nhưng mặt khuất
   và texture bake từ video kém hơn Gaussian; giữ làm tuỳ chọn xuất.
3. **Frosting/SuGaR làm lõi (Gaussian gắn mesh)** — giá trị chính là biến dạng mesh kéo theo hình,
   không cần cho vật cứng; không tách theo vật; giữ làm ứng viên mesh nền.
4. **NuRec (`OmniNuRecFieldAsset`)** — chất lượng hiển thị được báo tốt hơn ParticleField nhưng
   NVIDIA sẽ thay bằng ParticleField; chọn ParticleField, so hai định dạng khi có máy Isaac.

## Consequences

Positive:

- Studio sửa đúng thứ được xuất; thêm/xoá/sửa vật tức thì vì nền đã vá sẵn.
- USD lai khớp hướng real-to-sim của NVIDIA và yêu cầu vật lý/nhãn/bản đồ dẫn đường của Isaac.
- Giữ được chặng 1–3b, orchestration, revision SceneIR, duyệt/phát hành, đăng nhập, khung UI.

Tradeoffs:

- Lõi dựng 3D, viewer và bộ xuất phải làm lại; cần GPU thuê và runtime Python/CUDA mới.
- Chất lượng video vẫn là giới hạn trên: mask sai hoặc Gaussian nhoè làm vật bị cắt xấu, vá nền
  lộ vết. Vùng vá chưa từng được quay là hình suy đoán, phải gắn nhãn rõ trên UI.
- Mặt khuất của vật và ánh sáng "dính" trong hình; vật dời chỗ mang theo sáng tối chỗ cũ.

## Follow-Up

- Pha A: chạy thử và đo (tách vật, mesh so LiDAR TorWIC, PSNR nền sau khi xoá vật, thời
  gian/VRAM/chi phí, USD mở được trong Isaac); chọn phương pháp chặng 5–7.
- Xác minh: phiên bản Isaac Sim trên máy RTX (≥ 5.0, tốt nhất 6.0); LiDAR có trúng Gaussian
  không; validator SimReady (`NVIDIA/simready-foundation`) có chạy được trên USD của mình không.
- Tuỳ chọn chờ owner: xem trước vật lý trên web (PlayCanvas + ammo.js) trước khi sang Isaac.
- Owner cấp task ID cho các việc mới (không tự tạo ID theo AGENTS.md).

Nguồn: [NVIDIA — Reconstruct a scene in Isaac Sim using only a smartphone](https://developer.nvidia.com/blog/reconstruct-a-scene-in-nvidia-isaac-sim-using-only-a-smartphone/),
[Isaac Sim 6.0 — Neural Volume Rendering](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/assets/usd_assets_nurec.html),
[NVIDIA forum — NuRec vs ParticleField](https://forums.developer.nvidia.com/t/question-on-two-3dgs-rendering-pipelines-nurec-vs-particlefield-and-expected-quality-tradeoff-in-isaac-sim-6-0/373260),
[3DGRUT](https://github.com/nv-tlabs/3dgrut),
[NVIDIA forum — triangle mesh collision trên rigid body động](https://forums.developer.nvidia.com/t/collider-and-rigid-body-preset-error-physicsusd-parse-collision-triangle-mesh-collision/244203),
[SimReady — Physics best practices](https://docs.omniverse.nvidia.com/simready/latest/simready-asset-creation/physics-best-practices.html),
[Isaac Lab — sim utils (`add_labels`)](https://isaac-sim.github.io/IsaacLab/main/source/api/lab/isaaclab.sim.utils.html),
[Isaac Sim — Occupancy Map](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/py/source/extensions/isaacsim.asset.gen.omap/docs/index.html).
