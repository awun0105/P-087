# Hợp đồng dữ liệu Real2Sim Studio

## 0. Phạm vi và cách sử dụng

Tài liệu giải thích dữ liệu nào được bàn giao giữa các thành phần, cách nhận diện đúng phiên bản dữ liệu và các ràng buộc khi đọc, sửa hoặc phát hành. Nội dung được đối chiếu với code trên `develop`, HEAD `ac0be875`, ngày 20/10/2026.

Hợp đồng dữ liệu quy định cấu trúc và ý nghĩa dữ liệu mà hai bên cùng hiểu. Artifact là file/kết quả đã lưu; reference là bản ghi trỏ tới nó; checksum là mã dùng để đối chiếu nội dung. Lineage là chuỗi liên kết từ kết quả về đúng nguồn, cấu hình và lần chạy đã tạo ra nó.

Đây là bản chuẩn hóa chờ chủ dự án rà soát. Nó mô tả implementation hiện có; không tự thay đổi chính sách sản phẩm hoặc xác nhận một nhánh đã chạy thành công trên môi trường thật. [TEAM_EXECUTION_CONTRACT](execution/TEAM_EXECUTION_CONTRACT.md) vẫn được giữ trong giai đoạn chuyển đổi; authority map và các nơi đang tham chiếu sẽ được chuyển trong lượt chuẩn hóa toàn bộ bộ docs.

### 0.1 Ranh giới với các tài liệu khác

| Tài liệu | Nội dung thuộc tài liệu đó |
| --- | --- |
| [PRD](PRD.md) | Phạm vi sản phẩm, quyền người dùng và tiêu chí nghiệm thu |
| [ARCHITECTURE](ARCHITECTURE.md) | Module, nơi đặt code, lưu trữ và mô hình triển khai |
| [PIPELINE](PIPELINE.md) | Thứ tự chạy, nhánh xử lý, điểm chờ và cách tiếp tục |
| CONTRACTS | Định danh, ý nghĩa dữ liệu và điều kiện bàn giao hợp lệ |

Danh sách field, kiểu, giá trị mặc định và validator đầy đủ nằm trong [Pydantic contracts](../src/models/contracts/) và DTO tại API sở hữu endpoint. Khi tích hợp, phải đọc cả model lẫn bên đọc kiểm tra nó. Parse JSON thành công chưa chứng minh checksum, quyền truy cập, lineage hoặc khả năng thực thi đã hợp lệ.

### 0.2 Bản đồ các nhóm hợp đồng

| Nhóm | Model chính | Bên tạo → bên đọc |
| --- | --- | --- |
| Tiếp nhận input | `InputManifest`, `InputAssemblySnapshot`, `InputResolutionReport`, `InputRecipe` | Upload/resolver → project, job, worker |
| Chuẩn bị video | `ClientVideoPreparationManifest`, `ServerVideoPreparationVerification` | Trình duyệt/upload verifier → reconstruction |
| Thực thi | `JobManifest`, `StageArtifact`, `RuntimeManifest` | Orchestrator/worker → API, tiến trình, bên đọc bước sau |
| Tái dựng | `ReconstructionPreview`, `VisualArtifact`, `GeometryArtifact`, `LiDARGeometryArtifact`, `ReconstructionBundle` | Reconstruction → Studio, scene processing |
| Cảnh chỉnh sửa | `SceneIR`, `SceneObject`, `ObjectMembershipArtifact`, các manifest surface/collision | Scene processing/editor → viewer, Walk, simulation |
| Đóng gói và kiểm định | `PreflightReport`, `CandidatePackage`, `ValidationConfig`, `ValidationRunRecord`, `ValidationReport` | Builder/validator → review |
| Đánh giá và phát hành | `EvaluationReport`, `ApprovalRecord`, `ReleaseManifest` | Evaluator/Reviewer/release service → báo cáo, tải bản phát hành |

## 1. Artifact, định danh và tính toàn vẹn

### 1.1 Một reference chỉ tới dữ liệu nào

[`ArtifactRef`](../src/models/contracts/artifacts.py) chứa `artifact_type`, `schema_version`, `artifact_uri`, `artifact_checksum`, `data_class`, `producer_stage`; `job_id` và `source_provenance` tùy chọn ở model cơ sở. Các model cụ thể có thể yêu cầu chặt hơn, chẳng hạn preview bắt buộc reference thuộc cùng job và attempt.

URI dùng dạng `artifact://jobs/<job_id>/<artifact-path>`. Schema từ chối đường dẫn tuyệt đối, segment rỗng, `.`/`..`, dấu gạch chéo ngược và ký tự không được hỗ trợ. Một số luồng upload dùng namespace tiếp nhận dưới cùng dạng URI; không suy ra rằng mọi namespace đều là một reconstruction job đã chạy.

Tên file, URL tải tạm và đường dẫn cache cục bộ không thay thế định danh. API kiểm quyền truy cập trước khi cấp nội dung hoặc link tải; bản thân một reference hợp lệ không cấp quyền cho người đang cầm nó.

### 1.2 Phân loại quyền sử dụng dữ liệu

`ArtifactDataClass` có bốn giá trị: `product_input`, `derived`, `ground_truth`, `evaluation_only`. `ProductArtifactRef` và `InputFile` chỉ nhận hai giá trị đầu. `EvaluationReport` dùng `ArtifactRef` tổng quát để có thể ghi nguồn tham chiếu phục vụ đánh giá.

`data_class` khai báo dữ liệu được dùng ở boundary nào. Provenance khai báo nó được tạo từ đâu. Đổi thư mục hoặc sửa class trên JSON không chứng minh nguồn dữ liệu đã được phép đưa vào prediction.

[`PreprocessingProvenance`](../src/models/contracts/reconstruction.py) ghi dependency bằng `role`, `origin`, `source_checksum`. `origin` là `sensor_input`, `estimated`, `external` hoặc `ground_truth`; `ground_truth_assisted` phải khớp với việc có dependency ground truth. Bundle dùng LiDAR có hỗ trợ ground truth phải giữ dấu này trong provenance. Kết quả đó không chứng minh độ chính xác độc lập với ground truth.

### 1.3 Hai loại checksum

Checksum có dạng `sha256:` cộng 64 ký tự hex thường. Cần xác định đối tượng được hash trước khi so sánh:

| Loại định danh | Ví dụ | Cách xác minh |
| --- | --- | --- |
| Bytes của file | `ArtifactRef.artifact_checksum`, `InputFile.checksum`, checksum payload của `StageArtifact` | SHA-256 trên đúng bytes được lưu |
| Nội dung logic của model | `input_manifest_checksum`, `job_manifest_checksum`, `scene_ir_checksum`, `report_checksum`, `candidate_checksum`, `release_manifest_checksum` | Hash canonical JSON, bỏ riêng field self-checksum ở cấp ngoài cùng |
| Định danh được sao chép từ nguồn | `ValidationReport.candidate_checksum`, `ApprovalRecord.validation_report_checksum` | So với checksum đã xác minh của dữ liệu nguồn tương ứng |
| Cấu hình xử lý | `JobManifest.config_checksum`, `CandidateManifest.build_config_checksum` | SHA-256 bytes cấu hình mà composition root đã chọn |

[`canonical_json_bytes`](../src/models/contracts/identity.py) lấy kết quả `model_dump(mode="json")`, sắp key, dùng separators `,`/`:`, UTF-8, không ASCII-escape, không NaN/Inf. Thứ tự phần tử trong array có ảnh hưởng đến định danh. Serializer riêng của model quyết định field nào bị lược bỏ để tương thích dữ liệu cũ; không tự thêm `null` hay bỏ default trước khi hash.

`ReconstructionBundle.artifact_checksum` là định danh nội dung bundle. Khi bundle được publish thành file JSON, reference bao ngoài mang checksum bytes của file đó. Tương tự, `SceneResponse.scene_checksum` nhận diện bytes SceneIR đã publish, còn `scene.scene_ir_checksum` nhận diện nội dung logic. Hai giá trị có thể khác nhau mà vẫn đúng.

### 1.4 Publish và đọc lại

Bên tạo hoàn tất payload, tính checksum, validate model rồi publish vào URI chưa dùng. [`FilesystemArtifactStore`](../src/services/orchestration/artifacts/store.py) kiểm checksum payload và tạo destination bất biến; file đã tồn tại không bị ghi đè. Luồng cho phép gọi lại phải xác minh bytes đang có trước khi dùng lại kết quả.

Bên đọc dùng `ArtifactResolver.require` để kiểm tồn tại và SHA-256, sau đó parse model và kiểm các ràng buộc của nghiệp vụ. `resolve` chỉ cho đường dẫn; `locate` hỗ trợ tìm/tải về. Hai hàm này không tự chứng minh toàn vẹn bytes. `require_unchanged` là tối ưu có kiểm phiên bản file dành cho các đường đọc preview đã chọn; các bên đọc nghiêm ngặt vẫn dùng `require`.

## 2. Input và lựa chọn một lần chạy

### 2.1 InputManifest và privacy

[`InputManifest`](../src/models/contracts/manifests.py) gắn danh sách file đã nhận, modality, khai báo quyền dữ liệu và checksum nội dung manifest. Mỗi `InputFile` có tên gốc, media type, kích thước, checksum bytes, URI và class. `source_type` là `dataset` hoặc `upload`.

`InputConfiguration` yêu cầu ít nhất RGB hoặc registered LiDAR. Depth cần đi cùng RGB. Khi RGB và registered LiDAR cùng có mặt, `declared_same_scene` phải là `true`; registered LiDAR cần `lidar_metadata`, còn input không có modality này không được khai báo metadata đó. Đây là khả năng biểu diễn của model; các recipe đang chạy được được mô tả trong PIPELINE.

`PrivacyValidationReport` gắn `input_manifest_checksum`, phạm vi kiểm tra, số frame, finding còn mở và kết quả `PRELIMINARY_SCREENED`, `VERIFIED_ANONYMIZED` hoặc `QUARANTINED`. Khai báo quyền của người upload, kết quả privacy và việc người dùng chấp nhận bộ frame đã che là các bằng chứng khác nhau. DTO còn phân biệt `privacy_mode=self_attested` với `qa_verified`; không diễn giải self-attestation thành QA đã kiểm chứng. Điều kiện public/demo tuân PRD và quy trình privacy đang có.

### 2.2 Assembly, resolution và recipe đã chấp nhận

[`InputAssemblySnapshot`](../src/models/contracts/input_assembly.py) là một revision bất biến của tập file, role binding và declaration. Binding chỉ được trỏ tới file trong cùng snapshot, mỗi role chỉ có một binding được chọn. Thay file hoặc khai báo tạo revision/checksum mới.

`InputResolutionReport` gắn assembly revision/checksum, phiên bản resolver và runtime registry checksum. `state` phân biệt `ready`, `needs_input`, `pending_verification`, `unsupported`, `invalid`. Chỉ report `ready` mới được đề xuất một candidate `ready` có runtime `qualified`. Một report có thể có nhiều candidate, gồm `video_recipe` hoặc `gaussian_view_import`; `candidate_id` ở đây nhận diện lựa chọn input, khác candidate OpenUSD ở mục 7.

`InputRecipe` khóa assembly, resolution, candidate, role binding, file bị loại, nguồn trajectory, component versions, config, người chấp nhận và thời điểm UTC. Retry gắn recipe đã chấp nhận; không đọc draft mới nhất rồi âm thầm đổi input.

[`InputAssemblyRunRecord`](../src/services/orchestration/inputs/runs.py) gắn receipt chấp nhận với `project_id`, `job_id`, recipe ref/checksum, requester, `idempotency_key` và request fingerprint. Receipt dùng để nhận diện lần chấp nhận đầu hoặc phát lại cùng yêu cầu, thay vì tạo job mới theo mỗi lần gửi lại HTTP.

### 2.3 Runtime qualification và import

`RuntimeCapabilityRecord` dùng `qualified`, `wired_unqualified`, `unavailable`, `incompatible`. Khai báo `qualified` cần runtime ID, version và checksum bằng chứng qualification. Trạng thái này khác heartbeat cho biết có worker đang sống.

`GaussianViewImportIntent` khóa đúng file PLY/SOG, format và checksum nguồn để xem. Nó không yêu cầu reconstruction. Có schema cho một modality hoặc recipe cũng không có nghĩa worker hỗ trợ mọi tổ hợp của schema; các gate R4/R5/R6 và giới hạn import hiện tại nằm trong PIPELINE.

### 2.4 Video chuẩn hóa và ánh xạ frame

[`ClientVideoPreparationManifest`](../src/models/contracts/video_preparation.py) gắn normalization profile, implementation/version, metadata nguồn, bytes video đầu ra, pixel transform, audio disposition và frame-map sidecar. `VideoFrameBinding` nối frame index/PTS đầu ra với frame index/PTS nguồn. Descriptor ghi checksum, kích thước và số dòng; toàn bộ map không được nhét vào API JSON body.

Video đầu ra phải tuân profile được khóa: không upscale, rotation được áp dụng một lần, metadata rotation về 0, pixel vuông và metadata màu SDR phù hợp. Bỏ audio có track nguồn cần khai báo `omitted_with_user_consent`. Các giới hạn preset và số bytes lấy từ profile trong code.

`ServerVideoPreparationVerification` gắn checksum/kích thước upload, stream server quan sát được, client manifest và ref sidecar. `status=server_verified` xác nhận phần server đã kiểm trên dữ liệu nhận được. `original_source_status=client_declared_unverified` nói rõ file gốc còn ở máy người dùng chưa được server xác minh; không nâng mức tin cậy của file gốc theo trạng thái upload.

## 3. Job, stage và định danh runtime

### 3.1 Trạng thái và bằng chứng thực thi

[`JobManifest`](../src/models/contracts/manifests.py) chứa job/project/revision, input/config/runtime checksum, seed, thời điểm, `current_stage`, `stage_artifacts` và checksum nội dung manifest. Phiên bản phần mềm không được khai báo bằng các field `software_versions`/`environment_versions` tự thêm vào JobManifest; model hiện lưu checksum nhận diện runtime.

`JobStatus` và `StageStatus` đều có `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`. Một `StageArtifact` thành công cần URI, checksum và `completed_at`; URI đi cùng `data_class`. Stage thất bại cần `ExecutionError` có cùng `stage_id`. Validator cấu trúc không thay việc bên đọc kiểm toàn bộ artifact bắt buộc của stage.

`StageId` trong source là registry mã stage. Các mã mark/UI như `ST-ANONYMIZATION-REVIEW` và `ST-VIEW-LOD` không tự trở thành StageArtifact. Job reconstruction thành công chỉ kết luận công việc của job đó; geometry operation, validation run và release có lifecycle riêng.

### 3.2 Attempt, lỗi và quyền ghi của worker

[`JobAttemptRecord`](../src/services/orchestration/jobs/models.py) lưu lịch sử attempt cùng định danh manifest, stage, lỗi và số frame thực tế khi có. Retry nối thêm lịch sử, giữ provenance trước đó. `requested_by` chỉ gắn vào event bắt đầu `QUEUED`; không dùng role hiện tại để suy ra người đã yêu cầu một attempt cũ.

`ExecutionError` có `error_code`, `stage_id`, `human_message`, `retryable` và `details` tùy chọn. [`retryability.py`](../src/models/contracts/retryability.py) là nơi kiểm chính sách retry; không chỉ tin cờ `retryable` do dữ liệu cũ hoặc exception tổng quát mang tới.

Operation chạy nền còn có lease và token/generation để chặn worker đã mất quyền. Token cụ thể phụ thuộc loại operation; không có một field lease chung trên mọi JobManifest. Scene publication và validation run kiểm quyền ghi riêng tại lúc commit, như mục 6 và 8.

### 3.3 Phiên bản runtime

`RuntimeManifest` ghi component với `UNVERIFIED` hoặc `VERIFIED`; component `VERIFIED` cần version. Nó cũng có checksum nội dung riêng. Ghi được version vào manifest không chứng minh mọi tool trong đó đã chạy cho một candidate cụ thể.

[`ExecutionProfile`](../src/services/orchestration/jobs/profile.py) khóa config checksum và runtime ở composition root. Job mới dùng checksum phần mềm, loại `gpu_model`, `vram`, `nvidia_driver` khỏi phép hash ghép job với worker. Profile vẫn giữ checksum runtime đầy đủ và chấp nhận dạng đầy đủ của job cũ. Vì vậy không mặc định mọi `JobManifest.runtime_manifest_checksum` đều bằng checksum của manifest toàn bộ máy đang chạy.

## 4. Tọa độ, mét và kết quả reconstruction

### 4.1 Quy ước tọa độ chuẩn

[`CoordinateSystem` và `Transform`](../src/models/contracts/coordinates.py) khóa các quy ước sau:

| Thuộc tính | Giá trị |
| --- | --- |
| Đơn vị canonical | `meter` |
| Trục hướng lên | `Z` |
| Hệ trục | `right` |
| Frame gốc | `world` |
| Chiều transform | `parent_from_local` |
| Thứ tự quaternion | `xyzw`, chuẩn hóa |
| Đơn vị góc | `radian` |

Ý nghĩa là `p_parent = T_parent_from_local * p_local`. `parent_frame` và `local_frame` phải khác nhau. Adapter đổi convention COLMAP, sensor, viewer hoặc simulator tại boundary; tên transform từ dataset không đủ để suy ra chiều phép biến đổi.

`SceneObject.transform` đặt local frame của vật vào parent frame. `collider.local_transform` là offset có parent bằng local frame của vật. Khi compose, dùng đúng hai transform này; không tạo thêm world pose độc lập cho collider.

### 4.2 Preview và xác nhận mét

[`ReconstructionPreview`](../src/models/contracts/preview.py) gắn job, attempt, input checksum, source visual, camera pose và delivery SOG. Các ref phải thuộc cùng job/attempt và đúng stage tạo ra chúng. Preview bắt buộc `metric_status=UNCONFIRMED`, `coordinate_frame=sfm_world`, `unit=arbitrary`; nó chưa phải canonical VisualArtifact dùng cho simulation.

`MetricScale` có `UNCONFIRMED` hoặc `CONFIRMED`; trạng thái confirmed cần `meters_per_unit` dương. [`MetricConfirmationService`](../src/services/orchestration/jobs/metric.py) còn gắn quyết định với job, checksum preview đã xem và người xác nhận theo cấu hình auth. Một flag `CONFIRMED` được ghi tay không thay thế chuỗi bằng chứng này.

Sau canonicalization, geometry và bundle builder yêu cầu scale đã xác minh, `meters_per_unit=1`. Các artifact ghi confirmation checksum và transform/scale đã áp dụng để bên đọc kiểm nguồn và tránh áp scale thêm lần nữa. Đề xuất mét và xác nhận alignment LiDAR là hai quyết định khác nhau.

### 4.3 Visual, geometry và bundle

[`VisualArtifact`](../src/models/contracts/reconstruction.py) mô tả payload với format, tên/phiên bản công cụ tạo ra nó, input checksum và coordinate system. Master PLY phục vụ xử lý/xuất và delivery SOG phục vụ browser được tham chiếu riêng; không dùng delivery nén thay master chỉ vì chúng trông cùng một cảnh.

`GeometryArtifact` cho RGB gắn master checksum, confirmation, applied transform/scale, voxel/seed/capsule và provenance. Phiên bản `1.2` còn bắt buộc cleanup evidence khớp job, nguồn và collision mesh. Nó là geometry suy ra từ RGB 3DGS; chưa tự chứng minh collision đầy đủ trong thế giới thật.

`ReconstructionBundle` chứa định danh input, coordinate/metric metadata, các ref frame/pose/visual/geometry và `canonical_geometry_ref` được chọn rõ. Khi có RGB, phải có frame, pose, visual và RGB geometry. `depth_present` phải khớp `depth_frame_set`; depth khai báo dtype, format, `scale_to_meter` dương và frame refs, không mặc định là ground truth.

[`validate_bundle_sources`](../src/services/reconstruction/bundle_validation.py) kiểm đúng job, bytes, vai trò bên tạo, metric verification và dependencies trước publish. Model bundle có thể biểu diễn nhiều modality hơn các đường chạy public hiện có; không dùng sự hiện diện của một field làm bằng chứng pipeline đầu-cuối đã hỗ trợ.

### 4.4 LiDAR và alignment

`LiDARGeometryArtifact` giữ geometry đã đăng ký, source input/frame, declared transform và preprocessing provenance. Declared transform chưa phải alignment confirmed. Artifact gốc không bị sửa để giả thành dữ liệu đã căn chỉnh.

Mixed bundle cần `AlignmentRecord.status=CONFIRMED`; `source_lidar_checksum` và `target_rgb_geometry_checksum` phải khớp đúng hai nguồn. Record giữ `transform_target_from_source`, method và evidence refs; bundle builder còn kiểm record đã publish và bytes bằng chứng.

Nhánh registration có [`RegistrationRequest`, `RegistrationProposal`, `RegistrationQAReport`, `RegistrationConfirmationRecord`](../src/models/contracts/rgb_lidar_registration.py). Confirmation gắn định danh operation/request, revision dự kiến, candidate được chọn, checksum nội dung đã xác nhận, người và thời điểm. Không xác nhận lại một proposal mới bằng quyết định dành cho proposal cũ. Việc chọn collision source sau registration thuộc mục 5.4.

## 5. SceneIR, vật thể và quyền sở hữu dữ liệu nguồn

### 5.1 Nội dung canonical của một scene

[`SceneIR`](../src/models/contracts/scene.py) có `scene_id`, `scene_revision`, coordinate/metric metadata, `environment`, `objects`, provenance và checksum nội dung. ID vật phải duy nhất trong revision. Review status nằm ở `SceneRevisionRecord`, không được thêm `review_state` vào SceneIR để thay workflow.

`SceneObject` có state `CANDIDATE` hoặc `CONFIRMED`, origin `reconstructed` hoặc `user_added`, cờ `active`, transform và các ref biểu diễn. `user_added` cần asset ref hoặc kích thước primitive hợp lệ; nó không sở hữu vùng collision tái dựng của nguồn.

Geometry readiness hiện nằm trong `scene.provenance.object_geometry` với `awaiting_review` hoặc `ready`. [`geometry_state.py`](../src/services/scene/geometry_state.py) có tương thích cho scene cũ thiếu key: gate thao tác coi là ready, projection hiển thị trả `None`. Không dùng sự thiếu key để kết luận scene đã qua quy trình dựng geometry mới.

### 5.2 Vai trò các biểu diễn và trạng thái vật

| Trường | Vai trò |
| --- | --- |
| `visual_ref` | Dữ liệu hiển thị của vật/nền |
| `geometry_ref` | Geometry mà object/environment đang khai báo |
| `surface_mesh_ref` | Surface `ObjectShellMesh` hoặc `ObjectSurfaceMesh`, khác collider |
| `collider.geometry_ref` | Geometry phục vụ collider và physics |
| `physics` | Dynamic/static, khối lượng và nguồn khối lượng, ma sát, restitution |
| `source_collision` | Vùng object sở hữu trên collision nguồn và pose lúc extraction |

Vật động cần `mass_kg` và `mass_source`. Các giá trị này có provenance riêng; nhãn semantic không tự chứng minh khối lượng đã được đo.

[`scene_representations`](../src/services/scene/representation_composition.py) tính cách dùng biểu diễn từ state, active và `provenance.review`. Candidate hoặc vật `IGNORED` tái dựng hợp lệ giữ biểu diễn nguồn; `DELETED`/`MERGED` bị loại; vật confirmed dùng biểu diễn object khi active. Active trên candidate hoặc trên vật ignored/deleted/merged tạo blocker. Ẩn một layer tạm trong viewer không thay disposition đã persist.

### 5.3 Gaussian membership và lệnh correction

[`ObjectMembershipArtifact`](../src/models/contracts/object_membership.py) gắn exact source visual, source geometry, extraction revision, coordinate system, số Gaussian và labels ref. Payload labels là `little-endian-int32`, một nhãn mỗi Gaussian nguồn; `-1` là background, nhãn không âm ánh xạ tới object ID. Nhãn hợp lệ vẫn cần bên đọc kiểm độ dài payload, số row nguồn và sự tồn tại của object được ánh xạ.

Merge/reassign/region command có `expected_scene_revision` và `membership_checksum`. Field `membership_checksum` so với `membership.labels_ref.artifact_checksum`, tức checksum bytes labels, không phải hash toàn manifest membership. [Bộ kiểm tra membership](../src/services/scene/editing/membership.py) kiểm lại revision, nguồn, owner map và các object đủ điều kiện trước khi sửa.

Lựa chọn bằng Gaussian index còn gắn `source_visual_checksum`; index phải duy nhất, có thứ tự và không âm. ROI reassign dùng tọa độ world mét; `RegionBox` dùng tọa độ local của vật với half extents theo mét và yaw theo radian. Không dùng chung box của hai hệ tọa độ mà bỏ transform.

Preview correction ghi số Gaussian chuyển được, số bị bảo vệ và số thuộc owner khác. Preview chưa phải commit. Apply phải kiểm lại context hiện hành và tạo artifact/revision mới; không sửa nhãn của revision cũ tại chỗ. Schema lệnh cũng không bảo đảm mọi scene nhận được lệnh: [`object_correction.py`](../src/services/orchestration/scene/object_correction.py) có gate chặn merge legacy khi scene đã dùng object-aware collision.

### 5.4 Collision ownership và nguồn đang có hiệu lực

`SourceCollisionMembership` lưu triangle index duy nhất, tăng dần trên đúng bytes `source_geometry_ref`; danh sách rỗng có thể là trạng thái ownership hợp lệ sau khi chuyển hết triangle. `SourceCollisionRegion` giữ object ID, extraction revision và `source_transform`; mode là triangle membership hoặc OBB nguồn. Chỉ số triangle không được tái dùng cho mesh khác dù hai mesh có hình gần giống nhau.

Đường chọn collision nguồn ghi cặp `environment.collision_source_ref` và `collision_selection_ref`, cùng `collider_ref` hiệu lực. [`CollisionSourceSelection`](../src/models/contracts/collision_quality.py) gắn source/QA, input mode, alignment QA phù hợp, profile/config checksum và output collision. SceneIR và CandidateManifest kiểm các ref đi cùng nhau, đúng loại và job.

Đường object-aware ghi `object_aware_collision_ref` tới [`ObjectAwareEnvironmentManifest`](../src/models/contracts/object_geometry.py), đi cùng membership và collider. Nó loại trừ cặp legacy collision-source selection. Manifest gắn nguồn geometry, membership, danh sách object đã loại khỏi nền và collision đầu ra; không ghép hai đường selection trong cùng environment.

`ObjectShellManifest`/`ObjectSurfaceManifest` gắn mesh local mét với nguồn membership và pose/dataset/checkpoint tương ứng. Surface, collider và visual vẫn là các artifact riêng, dù cùng mô tả một vật.

## 6. Revision, concurrency và vô hiệu hóa kết quả cũ

### 6.1 Revision mới và committed head

Scene edit gửi `expected_scene_revision` để kiểm rằng người dùng đang sửa bản hiện hành. [`SceneHeadRepository`](../src/services/orchestration/scene/heads.py) quản lý reservation, artifact đã publish và committed head bằng compare-and-swap theo revision/generation/checksum. Số revision cao nhất có trên storage chưa đủ để trở thành head.

Commit chỉ nhận đúng artifact đã gắn với writer, reservation chưa hết hạn, head chưa bị người khác đổi và operation commit guard còn hợp lệ. Worker mất lease không được đưa output của nó thành head mới. Artifact đã publish nhưng chưa commit không tự được xem là scene hiện hành.

### 6.2 Kết quả bước sau thuộc revision nào

`SceneRevisionRecord` gắn `scene_ir_checksum` với workflow state và checksum candidate/validation/evaluation/approval của revision đó. Sửa nội dung scene tạo revision mới; kết quả và approval cũ vẫn được giữ để truy vết, nhưng không xác nhận nội dung mới.

Khôi phục bố trí hoặc nhân bản một vật cũng đi qua đường tạo revision của editor. Không lấy checksum report cũ gắn sang revision mới chỉ vì bố trí nhìn giống bản cũ. Chi tiết thao tác và các đường rebuild nằm trong PIPELINE.

## 7. Preflight và candidate bất biến

### 7.1 Preflight kiểm gì

[`PreflightReport`](../src/models/contracts/validation.py) gắn revision, SceneIR checksum, ruleset version, từng rule, evidence/remediation và `blocking_result`. Rule result là `PASS`, `FAIL`, `ERROR`. Registry hiện có các rule về metric, collider, transform, bounds, artifact, object confirmation, representation và collision coverage.

Report pass thể hiện preflight đã vượt các rule áp dụng. Nó không thay Isaac validation, bằng chứng coverage ngoài đời hoặc quyết định Reviewer. Không chuyển lỗi thực thi thành kết quả pass.

### 7.2 Inventory và checksum candidate

`CandidatePackage` gồm `candidate_manifest`, `entrypoint_usd`, `assets`, `geometry`, `colliders` và `candidate_checksum`. Manifest gắn revision, SceneIR/job/config checksum, coordinate system, object transforms và refs. Candidate checksum nhận diện toàn package logic, không chỉ entrypoint USD hay file ZIP.

[`verify_candidate_inventory`](../src/models/contracts/identity.py) yêu cầu `asset_refs`/`collider_refs` khớp package và checksum inventory theo đúng thứ tự:

```text
entrypoint_usd
→ assets[]
→ geometry[]
→ colliders[]
→ collision_selection_ref nếu có
→ object_aware_collision_ref nếu có
```

`collision_source_ref`, nếu có, phải nằm trong `colliders[]`; không append thêm checksum nguồn lần nữa ngoài danh sách đó. Mỗi member vẫn cần kiểm bytes riêng. Các ref collision tùy chọn là phần inventory hiện tại mà mô tả Foundation cũ chưa liệt kê đủ.

Candidate đã đưa vào validation/review phải giữ nguyên bytes và định danh. Thay mesh, transform, cấu hình hoặc thành viên package cần build candidate mới; không regenerate rồi giữ checksum hoặc approval cũ.

## 8. Validation, evaluation và độ tin cậy của bằng chứng

### 8.1 Config, run và report

[`ValidationConfig`](../src/models/contracts/validation_run.py) khóa policy ID, check bắt buộc/cảnh báo, Start–Goal pairs, runtime profile khi có và config checksum. Pair dùng tọa độ mét; không mang hidden expected benchmark label vào validator.

`ValidationRunRecord` nhận diện `run_id`, attempt, job/revision/SceneIR/candidate/config và origin `WORKER` hoặc `SYNTHETIC_FIXTURE`. Worker đã chạy cần assignment `worker_id`/`lease_id`/`fencing_token` đầy đủ. Run `COMPLETED` cần runtime ref, report ref, report checksum, execution-log ref và các thời điểm UTC đúng thứ tự. Completed là trạng thái thực thi; report vẫn có thể trả fail.

`ValidationReport` ghi candidate checksum, validator/environment versions, checks, kết quả path quan sát và checksum nội dung. Check/overall result là `PASS`/`FAIL`/`ERROR`; path là `CLEAR`/`BLOCKED`/`ERROR`. Report không chứa expected benchmark labels.

### 8.2 Run nào được dùng để review

`ValidationRunSelection` là con trỏ được cập nhật bằng CAS tới đúng run/report/config của candidate. [Repository selection](../src/services/orchestration/review/validation_runs.py) chỉ cho chọn run `WORKER` đã `COMPLETED`. [`evaluate_validation_eligibility`](../src/services/orchestration/review/validation_gate.py) đối chiếu selection với job, revision, SceneIR, candidate, config, report và RuntimeManifest; thiếu hoặc lệch bằng chứng thì chặn.

Gate yêu cầu runtime xác nhận component `isaac_sim` là `VERIFIED`, overall pass và các check/path đáp ứng policy. Check `FAIL`/`ERROR` không được bỏ qua bằng acknowledgment. Path `BLOCKED` bắt buộc là blocker; path không bắt buộc có thể tạo warning ID cụ thể. Không dùng riêng chuỗi version hay một JSON report pass để kết luận đã chạy Isaac thật.

### 8.3 Collision coverage và bằng chứng vật lý

`CollisionQualityReport` gắn source selection, geometry, cấu hình, output/effective collider, profile và bằng chứng đo. `CollisionPathSupportEvidence`/`CollisionPathCoverageDiagnostic` gắn coverage với từng path và candidate. Coverage phân biệt `observed_static`, `unobserved`, `inferred`, `motion_suspected`; `CLEAR` khi thử path không tự chứng minh mọi vùng quanh nó đã được quan sát.

Schema chỉ cho `physics_claim=verified` khi có QA pass theo acceptance profile, đúng candidate/effective collider, coverage đầy đủ của các vùng khai báo, obstacle/support reference độc lập và Isaac contact evidence gắn đúng checksum. Reference cùng input hoặc synthetic không đủ cho khai báo này. `collision_support_policy` của validation config quy định coverage là advisory hay required; không tự đổi policy khi trình bày report.

### 8.4 Evaluation tách khỏi validation sản phẩm

`EvaluationReport` gắn `subject_type`, ID/checksum đối tượng được đo, protocol, split khi có, references và preprocessing dependencies. Subject có thể là reconstruction, scene revision hoặc candidate package. `path_comparisons` mới chứa observed/expected/agreement.

Validation quan sát candidate theo cấu hình sản phẩm; evaluation so với reference theo protocol. Schema `ReleaseManifest` cho phép ordinary release thiếu evaluation checksum, nhưng bắt buộc checksum này với `LOCKED_MVP_ACCEPTANCE` và `BENCHMARK`. Điều đó không chứng minh mọi release mode đều được UI hiện tại expose; cách đo và ngưỡng nghiệm thu thuộc PRD và tài liệu đánh giá.

## 9. Approval và release

### 9.1 Quyết định của Reviewer

[`ApprovalRecord`](../src/models/contracts/release.py) gắn đúng candidate checksum, validation-report checksum, reviewer, quyết định, thời điểm và từng warning ID được chấp nhận. Reject cần lý do. Workflow state gồm `DRAFT`, `PROCESSING`, `CANDIDATE_READY`, `VALIDATING`, `READY_FOR_REVIEW`, `APPROVED`, `REJECTED`, `RELEASED`; các state này không phải JobStatus hoặc geometry readiness.

[`decide`](../src/services/orchestration/review/workflow.py) chỉ nhận quyết định khi revision đang `READY_FOR_REVIEW` và định danh còn khớp. Approve yêu cầu danh sách warning được chấp nhận bằng đúng danh sách warning hiện hành. Actor và quyền Reviewer do API/auth xác định; không tự cấp quyền bằng `reviewer_id` gửi từ client.

### 9.2 Đóng dấu đúng package đã duyệt

`ReleaseManifest` giữ định danh input/job/config/candidate/preflight/validation, evaluation khi áp dụng, software versions, artifact inventory, approval projection, timestamp và checksum nội dung release. Inventory dùng URI và checksum bytes để lần lại từng artifact.

Luồng hiện tại cố gắng seal release ngay sau approve. Approval có thể đã lưu bền vững trong khi sealing lỗi; trạng thái `APPROVED` chưa đủ để nhận là `RELEASED`. Thử seal lại dùng cùng định danh candidate/report/approval, xác minh manifest/archive và không build lại candidate đã duyệt. Không kế thừa approval sang scene/candidate khác.

## 10. API, tương thích và kiểm tra khi thay đổi

### 10.1 DTO HTTP và mirror TypeScript

[`src/api/schemas.py`](../src/api/schemas.py) định nghĩa DTO chung; request/response chuyên biệt còn nằm cạnh router trong [`src/api/studio`](../src/api/studio/) và [`src/api/product`](../src/api/product/). Dùng OpenAPI do ứng dụng hiện hành sinh để xem endpoint/body; không lấy một danh sách endpoint sao chép trong docs làm schema thứ hai.

Response scene trả nội dung, revision, URI/checksum file và representation projection. Response validation/review có các cờ như `isaac_runtime_proof`, `synthetic_authorization`; client phải giữ ý nghĩa nguồn bằng chứng thay vì chỉ hiển thị nhãn pass/approved. Error DTO cơ sở là `detail: str`, trong khi lỗi stage là `ExecutionError`; không giả định mọi lỗi HTTP có cùng cấu trúc với lỗi worker.

Frontend có [`api.ts`](../frontend/src/lib/contracts/api.ts), parser [input assembly](../frontend/src/lib/contracts/inputAssembly.ts), [preview](../frontend/src/lib/contracts/preview.ts), [video preparation](../frontend/src/lib/contracts/videoPreparation.ts) và các projection riêng. TypeScript interface không tự validate JSON tại runtime. Khi đổi payload phải kiểm cả parser, caller và bên tạo; không nới union thành `string` để che chênh lệch.

### 10.2 Version và dữ liệu cũ

`ContractModel` mặc định `extra="forbid"`. Một số receipt bên đọc có chủ ý dùng `extra="ignore"`, chẳng hạn `PreparedInputReceipt`; không suy rộng ngoại lệ đó ra toàn bộ contracts. Nhiều model yêu cầu gọi hàm verify/seal riêng, không tự kiểm logical checksum ngay khi parse.

`SchemaVersion` dùng chung hiện nhận `1.0`/`1.1`, nhưng có model khóa version riêng. Ví dụ payload `GeometryArtifact` nhận cả `1.2`; không mặc định mọi `ArtifactRef` hoặc model khác nhận cùng version. Khi thay version phải xem cả envelope lẫn parser payload tại bên tạo/bên đọc.

Thêm field optional cũng có thể đổi checksum nếu serializer đưa thêm default/null. Các model tương thích cũ dùng serializer hoặc `exclude_if` có chủ đích. Thay shape, enum, ý nghĩa field, đơn vị, transform hoặc checksum protocol cần bên tạo/bên đọc review, fixture và phương án đọc/migrate dữ liệu cũ. Lượt chuẩn hóa tài liệu này không nâng schema version hoặc tự duyệt các thay đổi đó.

### 10.3 Các kiểm tra sẵn có

Chạy tại repository root trong môi trường đã cài dependency và cấu hình theo README:

```bash
.venv/bin/python -m scripts.check_foundation
.venv/bin/python -m scripts.check_contract_mirror
.venv/bin/pytest tests/test_contracts -q
```

[Foundation checker](../scripts/check_foundation.py) kiểm typed fixtures, bytes/checksum, synthetic lineage, negative cases và một số projection tài liệu cũ. [Mirror checker](../scripts/check_contract_mirror.py) kiểm các enum/model/transition được liệt kê trong script; nó không bao phủ toàn bộ API và mọi parser frontend. [Contract tests](../tests/test_contracts/) kiểm validator và định danh, còn [integration tests](../tests/integration/) kiểm thêm các đường bàn giao cụ thể.

Các kiểm tra này không thay browser, GPU, runtime provider hoặc Isaac acceptance. Những file kỹ thuật cũ mà checker/agent/task còn tham chiếu phải được chuyển bên đọc trước khi dọn; không xóa chúng chỉ vì CONTRACTS mới đã tồn tại.
