# Giới hạn công nghệ, dữ liệu và phần có thể triển khai

Date: 2026-10-07. Đây là capability note, không phải bằng chứng rằng mọi công
nghệ trên thế giới đã được khảo sát hoặc không tồn tại lời giải.

## Các phần không đưa vào implementation cam kết

| Problem | Giới hạn đúng | Behavior/mitigation cho project |
|---|---|---|
| Blind RGB–LiDAR rig calibration cho input bất kỳ, không calibration/overlap/reference | Có self-calibration research. Thiếu overlap/constraints hoặc scene suy biến có thể không xác định duy nhất 6-DoF; project chưa có solver được qualified | Sensor-package path dùng calibration/metadata phù hợp và QA AUD-13; independent 3D maps dùng geometric registration AUD-19. Không gán map fit thành verified rig extrinsic |
| Full dynamic reconstruction → time-varying physical collider chính xác cho mọi moving object | Dynamic/4D rendering đã có. Rendering quality không là contact, mass, motion hoặc collision fidelity proof cho industrial simulation | Input static hiện tại; phát hiện/ghi nghi ngờ motion, yêu cầu static capture hoặc mask có provenance; không coi ghosted geometry là object vật lý hợp lệ |
| Khôi phục chính xác geometry chưa được camera/LiDAR/CAD quan sát | Dữ liệu không đủ xác định một geometry thật duy nhất. Generative completion là suy đoán | Mark inferred/unobserved regions; thêm capture/LiDAR/CAD/reference được kiểm; visual inpainting không tự tạo verified collision geometry; path acceptance không đi qua vùng thiếu evidence |

Không có sprint xây arbitrary blind-calibration solver, full 4D physics engine
hoặc generative collider được bảo đảm là sự thật. Các guard/diagnostics khả thi
được ghi trong AUD-12/13 và preflight/validation integration; không gọi chúng là
đã giải quyết các bài toán tổng quát ở bảng.

## Automatic map registration là cải tiến khả thi

[AUD-19](tasks/AUD-19-automatic-rgb-lidar-registration.md) và
[ADR 0020](../../../decisions/0020-automatic-rgb-lidar-map-registration.md) bổ sung
registration giữa reconstructed RGB geometry và registered LiDAR map cùng cảnh.
Hai maps có đủ overlap/structure/units có thể dùng geometric search ngay cả khi
không có camera↔LiDAR rig extrinsic. Đây không phải general blind calibration của
sensor hoặc lời giải thiếu mọi correspondence/observations; không dùng limits
ở bảng trên để loại supported independent-map mode.

Floor-constrained BEV candidates + robust ICP có thể giảm manual landmarks.
Known metric scale và floor đủ tin cậy giảm search còn yaw/x/y; nếu RGB scale chưa
chắc phải thêm scale estimation và new canonicalization trước rigid alignment.
Floor fitting/ICP không tự chứng minh exact metric hoặc độc nhất transform khi
repetitive warehouse/symmetry/partial coverage. Pipeline có QA/ambiguity/fallback.

[BVMatch](https://arxiv.org/abs/2109.00317) nghiên cứu LiDAR BEV relative pose;
[Open3D global registration](https://www.open3d.org/docs/release/tutorial/pipelines/global_registration.html)
phân biệt global initialization và local ICP refinement. Plan dùng các nguyên tắc
này và yêu cầu qualified RGB–LiDAR data riêng, không suy production accuracy từ
demo của paper. Current MoGe relative uncertainty không gồm systematic bias;
không promise universal 0,1%, 2 cm, millimeter hoặc 100% no-failure alignment.

## Nguồn primary và diễn giải

- [LCCNet official implementation](https://github.com/IIPCVLAB/LCCNet) có
  self-calibration pipeline và evaluation trên KITTI. Điều này bác bỏ nhận định
  “không có phương pháp”; không chứng minh solver đáng tin cho mọi rig/warehouse.
- [4D-GS, CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Wu_4D_Gaussian_Splatting_for_Real-Time_Dynamic_Scene_Rendering_CVPR_2024_paper.html)
  nghiên cứu dynamic scene rendering. Từ scope/output của paper, plan suy ra
  chưa có physics/contact acceptance cho Real2Sim; không tuyên bố dynamic CV là bất khả thi.
- Hình học vùng không quan sát là giới hạn observability của input: nhiều bề mặt
  khác nhau có thể tạo cùng measurements hiện có. Đây là lập luận về dữ liệu,
  không phải tuyên bố một model cụ thể không thể sinh hình ảnh/mesh.

## Khả thi nhưng cần quality gate

- Radius/statistical outlier removal: [Open3D documentation](https://www.open3d.org/docs/release/tutorial/geometry/pointcloud_outlier_removal.html).
  Filter có thể loại cả obstacle thật; AUD-12 bắt buộc obstacle retention proof.
- RANSAC floor và clustering: fit có degeneracy/noise cases; AUD-14 trả confidence
  và không chọn tường làm floor, không tự rotate lại SceneIR canonical.
- Projection QA: cần intrinsics/distortion/frame timing và sufficient observations;
  calibration mismatch/time mismatch/motion có thể lẫn nhau. AUD-13 báo uncertain
  hoặc remediation, không claim đo chính xác 1°/5 cm từ mọi overlay.
- Fast Preview/performance: có thể làm preset/progressive artifacts/cache; không
  hứa cố định 5 phút hoặc chạy nhanh trên GPU bất kỳ. AUD-15/16 đo cùng input/config.
- LiDAR odometry: [KISS-ICP official repo](https://github.com/PRBonn/kiss-icp)
  là odometry adapter candidate. [FAST-LIO official repo](https://github.com/hku-mars/FAST_LIO)
  dùng LiDAR + IMU; không thay bằng adapter scan-only khi thiếu IMU/timing.
  AUD-17 làm opt-in odometry, drift diagnostics; loop closure/global SLAM chưa cam kết.
- Face/plate anonymizer: detector/redaction và temporal tracking làm được, nhưng
  missed detections vẫn cần QA/manual remediation. AUD-18 không nâng “0 detections”
  thành VERIFIED_ANONYMIZED. License của code, model weights và data cần chốt;
  ví dụ [Ultralytics license](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)
  không tự động áp dụng cho một face/plate model bên ngoài.

## Conditions để mở lại research scope

Một prototype có dataset/reference độc lập, measured failure envelope và
downstream physics proof có thể tạo task/ADR mới. Ghi supported sensor/input
conditions, uncertainty, fallback và acceptance. Không sửa limits note thành
“Solved” chỉ vì một demo render tốt hoặc một traversal có 0 blocked positions.

## Client video compression compatibility

AUD-23 khả thi; codec/browser/device memory differences là support/qualification
constraints, không bài toán công nghệ thế giới chưa giải. WebCodecs không require
mọi codec. Capability check và bounded queues/storage, explicit unsupported input
và measured browser acceptance cần trước rollout. Nén local không tự tạo server
copy của original; higher-quality reconstruction có thể cần reselect source.
Giảm FPS/rotation cần source-time/pixel mapping, không là blind calibration solver.

## Unified input resolution

AUD-24 nhận file rời/ZIP trong một khung và tự resolve supported recipe; detection
và orchestration khả thi, không là giới hạn công nghệ. Không thể xác nhận mọi
units/map frame/capture/clock relation chỉ bằng extension, file count hoặc bytes
không chứa metadata đó. Resolver báo missing/ambiguous và hỏi ngay trong cùng UI.
Một static cloud có thể geometric-register khi đủ evidence, không cung cấp cả
trajectory đa scan. TUM có pose timestamps nhưng không tự là RGB clock offset.
Nhiều metadata không tự bảo đảm accuracy; malformed inputs không silently bị bỏ.

## Imported 3DGS continuation và SOG

AUD-25/ADR0025 Deferred theo yêu cầu owner ngày 2026-10-07 vì độ phức tạp. Không
implement continuation hoặc source adapter trong active scope; nội dung kỹ thuật
bên dưới là tham khảo nếu owner mở lại. Import/view PLY/SOG ở AUD-06/24 vẫn active.

Xử lý tiếp imported Gaussian PLY/SOG là khả thi: typed source adapter,
metric/floor setup, coarse geometry, geometric/manual objects/colliders và shared
SceneIR/export/validation. Real bound cameras/images hoặc LiDAR mở thêm capabilities.
Bare source không tự có observed frames, metric units, floor, complete geometry
hoặc physical properties; thiếu facts thì hỏi/ghi uncertainty, không tạo dummy receipts.

SOG view import nằm trong active plan; processing continuation/profile qualification đã hoãn.
[SOG specification](https://developer.playcanvas.com/user-manual/gaussian-splatting/formats/sog/)
dùng lossy quantization; lossless WebP giữ quantized values, không khôi phục PLY
trước nén. Decoded Gaussian/PLY cần source hash/decoder/version/field coverage;
SH đã bỏ, splats đã xóa hoặc vùng chưa quan sát không thể khôi phục chính xác từ
SOG đơn. Đây là giới hạn dữ liệu, không lý do từ chối mọi SOG continuation.
Viewer-readable SOG khác qualified geometry decoder; unbundled/LOD/model dialect
chưa hỗ trợ báo rõ. Mesh sạch hoặc ICP residual thấp không tự là industrial physics proof.
