# ReconstructionBundle fixture

`manifest.json` (RGB-only), `mixed_manifest.json` (RGB+LiDAR) và
`rgb_depth_manifest.json` (RGB+sensor depth) tuân `ReconstructionBundle`.
`camera_poses.json` và `artifact_store/` là payload nhỏ có SHA-256 thực để
`EX-SCENE` consume ngay. `rgb_depth_manifest.json` là contract capability cho
future/auxiliary input, không mở P0 product RGB-D profile. Depth frame payload là
metadata mock, không phải ảnh TorWIC hay ground-truth depth. Không fixture nào là
reconstruction, Brush compatibility hay Isaac acceptance proof.
Depth `uint16`/PNG/`0.001` trong fixture chỉ là một producer value. Mixed LiDAR
fixture mô phỏng input đã registered, không dùng trajectory GT; nếu có GT-assisted
preprocessing, `source_provenance.dependencies[]` phải ghi `origin: ground_truth`
và checksum nguồn, đồng thời giữ `ground_truth_assisted: true` qua bundle.
Mọi nested product ref khai báo `data_class: derived`; class này độc lập với
URI và không xóa GT-assistance lineage nếu producer sau này dùng GT.
`artifact_checksum` ở root bundle là canonical content hash loại trừ chính field
đó; nested refs và alignment payload dùng SHA-256 exact bytes. Checker xác minh
cả ba bundle profiles và mọi nested/direct evidence ref.
