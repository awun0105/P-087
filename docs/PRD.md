# PRD — Real2Sim Studio: chuẩn bị môi trường mô phỏng cho robot trong nhà

## 0. Phạm vi và cách sử dụng tài liệu

| Thuộc tính | Nội dung |
| --- | --- |
| Dự án | P-087 / RAV-01 — VinUni AI20K, Cohort 4 |
| Phiên bản | 2.0 — chuẩn hóa ngày 20/10/2026 |
| Trạng thái tài liệu | Bản chuẩn hóa để chủ dự án rà soát; không phải biên bản nghiệm thu MVP |
| Định vị | Công cụ tạo và chỉnh sửa môi trường thử nghiệm robot từ dữ liệu quan sát thực tế |
| Người dùng chính | Kỹ sư mô phỏng và kỹ sư tích hợp robot di động trong nhà |
| Trình mô phỏng nghiệm thu đầu tiên | NVIDIA Isaac Sim |
| Nguồn ý tưởng | [BRAINSTORM](BRAINSTORM.md), [MASTER_PITCH](MASTER_PITCH.md) |

PRD quy định **sản phẩm phục vụ ai, cần làm được gì và phải chứng minh bằng cách nào**. Mô tả “phải” là yêu cầu nghiệm thu, không khẳng định chức năng đã chạy thành công. Mô tả “có trong code” chỉ xác nhận implementation, không thay thế kiểm tra trên dữ liệu và môi trường thật.

Các mã `G-01…G-07`, `SM-01…SM-07`, `FR-00…FR-13`, `NFR-01…NFR-08` và `AC-01…AC-12` được giữ để tiếp tục truy vết từ tài liệu cũ. Phạm vi, hành trình và cách diễn giải được cập nhật theo định vị indoor robotics và code đã khảo sát ngày 20/10/2026.

### 0.1 Ranh giới với tài liệu khác

| Nội dung | Nơi trình bày chính |
| --- | --- |
| Câu chuyện sản phẩm, lập luận thị trường, nội dung pitching | [MASTER_PITCH](MASTER_PITCH.md); PRD chỉ rút yêu cầu sản phẩm |
| Thành phần hệ thống và ranh giới module | [ARCHITECTURE](ARCHITECTURE.md) |
| Trình tự xử lý, thuật toán và nhánh runtime hiện tại | [PIPELINE](PIPELINE.md) |
| Schema, tọa độ, checksum và bàn giao artifact | [CONTRACTS](CONTRACTS.md) và model trong source |
| Chi tiết màn hình và tương tác | [UX](UX.md) |
| Dataset, ground truth và protocol đo | [EVALUATION](EVALUATION.md) |
| Cài đặt và vận hành | [OPERATIONS](OPERATIONS.md) |
| Đã kiểm chứng tới đâu | [STATUS](STATUS.md); hồ sơ task trong `.ai/` và `docs/plans/` là bằng chứng gốc, task status không tự công nhận nghiệm thu |

PRD không sao chép schema, danh mục tham số, phiên bản dependency hay lệnh vận hành từ các nguồn đó.

### 0.2 Quy tắc thay đổi yêu cầu

Định vị theo hai tài liệu ý tưởng đã được chủ dự án chỉ định. Các yêu cầu bắt buộc đã có được giữ khi chuẩn hóa, trừ nội dung đã được thay thế bởi quyết định mới được ghi trong repository. Không tự thay đổi ngưỡng nghiệm thu theo kết quả đo, không biến giới hạn của implementation thành việc bỏ yêu cầu.

Nếu cần thay phạm vi hoặc tiêu chí bắt buộc, phải ghi yêu cầu bị đổi, lý do và quyết định của chủ dự án. Chỉnh sửa PRD không tự cấp trạng thái `APPROVED` cho một scene hay chứng minh MVP đã hoàn thành.

### 0.3 Trách nhiệm xác nhận

PRD trước ghi nhận Cường phụ trách sản phẩm, `@awun0105` phụ trách kỹ thuật/tích hợp, Đạt phụ trách kiểm thử và Đức phê duyệt phát hành. Lượt chuẩn hóa này giữ thông tin phân công đó để truy vết, chưa xác minh lại nhân sự. Khi khóa nghiệm thu phải xác nhận người chịu trách nhiệm cho scope, dữ liệu/ngưỡng, môi trường và quyết định phát hành; không suy vai trò của người vận hành từ quyền tài khoản trong ứng dụng.

## 1. Bài toán và định vị sản phẩm

### 1.1 Công việc người dùng cần giải quyết

Khi đưa robot vào một địa điểm mới, kỹ sư cần một môi trường thử nghiệm phản ánh bố trí thực tế. Nếu chưa có CAD hoặc scene phù hợp, họ phải chuẩn bị hình học, kích thước, vật thể và collision bằng nhiều bước. Khi bố trí thay đổi, scene cũng cần được cập nhật trước khi chạy lại bài thử.

Video giúp ghi lại địa điểm nhưng chưa cung cấp một scene có thể dùng ngay cho mô phỏng. Một bản dựng 3D nhìn rõ vẫn có thể sai kích thước, thiếu vật cản hoặc có collision không khớp hình ảnh.

Giả thuyết của sản phẩm là giảm công chuẩn bị và cập nhật scene trong những tình huống này. Mức độ khó khăn, tần suất nhu cầu và khả năng trả tiền phải được xác thực với người dùng; không coi đó là kết luận từ việc pipeline chạy được.

### 1.2 Sản phẩm cung cấp gì

Real2Sim Studio hỗ trợ chuyển dữ liệu quan sát thành scene 3D có thể kiểm tra và chỉnh sửa theo vật thể. Người dùng xác nhận kích thước, sửa cách tách vật, quản lý hình học va chạm và chuẩn bị gói OpenUSD cho bài thử trong Isaac Sim.

Phạm vi đầu tiên là **không gian trong nhà, một tầng, tương đối tĩnh**: phòng, văn phòng, hành lang, khu lưu trữ hoặc khu vực kho nhỏ. Nhà kho là một use case, không phải điều kiện để mọi dữ liệu demo đều phải là warehouse.

### 1.3 Tình huống sử dụng đầu tiên và tầm nhìn

Một robot cần đi qua lối giữa bàn hoặc kệ và tường. Kỹ sư tạo scene của địa điểm, kiểm tra bố trí A, di chuyển một vật cản để tạo bố trí B, rồi chạy lại cùng bài thử. Kết quả cần chỉ ra ảnh hưởng của thay đổi, gồm collision ở vị trí mới và khả năng còn collision giả ở vị trí cũ.

Tầm nhìn dài hạn là hỗ trợ tạo và diễn tập nhiều tình huống không gian trước khi thử ngoài đời. MVP chưa bao gồm tự tạo kịch bản bằng world model, tự huấn luyện policy hay chứng nhận an toàn robot thật.

## 2. Mục tiêu và thước đo thành công

### 2.1 Mục tiêu

| Mã | Kết quả cần đạt |
| --- | --- |
| G-01 | Chạy xuyên suốt từ video RGB camera di chuyển tới scene được kiểm định trong Isaac Sim và phát hành có kiểm soát |
| G-02 | Đo công chuẩn bị/chỉnh scene và so sánh với workflow thủ công trên cùng bài toán |
| G-03 | Giữ hình ảnh, hình học và collider nhất quán khi bố trí thay đổi |
| G-04 | Chứng minh LiDAR đã đăng ký thực sự đóng góp vào geometry hoặc validation của ít nhất một scene/khu vực |
| G-05 | Giữ quyết định phê duyệt phát hành ở người có quyền Reviewer |
| G-06 | Truy vết đúng input, cấu hình, scene revision, candidate và kết quả của mỗi release |
| G-07 | Cho phép kiểm tra và chỉnh scene trên browser với 3DGS thật và các lớp kỹ thuật phù hợp |

### 2.2 Chỉ số và ngưỡng

Mỗi phép đo có trạng thái `MEASURE`, `BASELINE`, `PROPOSED_TARGET` hoặc `LOCKED_ACCEPTANCE_THRESHOLD`. Chỉ ngưỡng đã được chủ dự án và người phụ trách đánh giá khóa trước khi xem kết quả cuối mới được dùng làm cổng đạt/rớt định lượng. Khi chưa có ngưỡng, phải ghi “chưa khóa”, không tự thêm tỷ lệ cải thiện.

| Mã | Chỉ số | Điều kiện sử dụng |
| --- | --- | --- |
| SM-01 | Hoàn thành luồng RGB đầu-cuối | Scene demo chính phải đạt AC-01; tỷ lệ thành công khi chạy lặp là phép đo riêng |
| SM-02 | Khả năng tải và dùng scene trong simulator | Gói demo chính phải mở đúng đơn vị, asset và cấu hình bài thử đã khóa |
| SM-03 | Nhất quán transform | So sánh các biểu diễn trước/sau chỉnh và lưu/mở lại; chỉ chấp nhận epsilon số học đã khóa |
| SM-04 | Collision và đường đi | Có kết quả cho 5/5 cặp Start–Goal đã khóa; kết quả phải khớp 5/5 nhãn đối chứng của bộ đánh giá |
| SM-05 | Chất lượng đề xuất vật thể | Báo độ phủ, vật thiếu/gộp nhầm và công sửa; ngưỡng chất lượng chỉ chặn nghiệm thu khi đã khóa |
| SM-06 | Công người và thời gian có scene dùng được | Đo riêng thời gian thao tác, chờ máy và sửa lỗi; chỉ kết luận cải thiện khi có manual baseline công bằng |
| SM-07 | Độ đầy đủ truy vết | Toàn bộ artifact bắt buộc của release có identity, nguồn, cấu hình và validation tương ứng |

PSNR, SSIM, LPIPS và chỉ số hình học phục vụ các mục đích khác nhau. Không lấy điểm hình ảnh cao làm bằng chứng collision đúng. Phạm vi và cách đo được quy định tại mục 10.

## 3. Người dùng và quyền truy cập

### 3.1 Vai trò trong công việc

**Kỹ sư mô phỏng** chuẩn bị dữ liệu, xác nhận hệ mét, chỉnh vật/collider và đưa scene đi kiểm định. Họ cần biết phần nào đã dùng được, phần nào cần sửa và thay đổi có được giữ đúng khi xuất sang simulator hay không.

**Kỹ sư tích hợp robot** xác định robot footprint và bài thử cần thực hiện. Họ quan tâm lối đi, vật cản và ảnh hưởng của thay đổi bố trí, thay vì chỉ chất lượng hình ảnh.

**Reviewer** xem candidate, kết quả kiểm định, cảnh báo và nguồn bằng chứng. Họ quyết định approve hoặc reject đúng candidate, không phê duyệt chung mọi revision về sau.

Các vai trò công việc này khác role cấp quyền trong ứng dụng. Một kỹ sư có thể dùng tài khoản Guest hoặc Editor tùy cách cộng tác.

### 3.2 Role và ownership

Visitor là người chưa đăng nhập. Guest là tài khoản đã có danh tính. Hierarchy là `Guest < Editor < Reviewer`; quyền sửa còn phụ thuộc chủ sở hữu resource.

| Hành động | Visitor | Guest | Editor | Reviewer |
| --- | --- | --- | --- | --- |
| Xem/thử mẫu công khai | Trong phạm vi mẫu được công bố | Có | Có | Có |
| Đọc scene/job/artifact dùng chung của nhóm | Không truy cập ngoài demo session | Có trong phạm vi được cấp | Có | Có |
| Tạo input và job | Không qua API làm việc của nhóm | Có, chịu quota | Có, theo hạn mức tài khoản | Có |
| Chỉnh/cancel/retry/xóa/khôi phục | Chỉ thao tác demo được cho phép | Resource của mình | Có quyền can thiệp resource của nhóm | Có |
| Dựng geometry hoặc simulation package | Theo capability của demo session | Trên resource của mình | Có | Có |
| Duyệt/reject/phát hành, quản lý tài khoản, purge thùng rác | Không | Không | Không | Có |

Mọi can thiệp cross-user phải truy vết được. Nếu Reviewer sửa scene rồi tự duyệt, vẫn phải tách bản ghi sửa và phê duyệt, có nhãn tự duyệt; không bỏ các bước kiểm định bắt buộc.

### 3.3 Đăng ký và hạn mức

Khi deployment cho phép, người dùng đăng ký Guest bằng tên hiển thị, email và mật khẩu; không tự chọn role cao hơn. Mã mời hợp lệ cấp role theo lời mời. Cờ cấu hình có thể đóng Guest signup; trạng thái bật trong code không chứng minh một deployment đã nghiệm thu signup.

Guest có ba lượt tạo job hoặc manual Retry được máy chủ chấp nhận trong một ngày lịch Việt Nam, đặt lại lúc 00:00 `Asia/Ho_Chi_Minh`. Request lặp có cùng accepted identity, worker resume và objectify không tiêu thêm lượt. Hệ thống phải hiển thị quota và xử lý cạnh tranh ở server, không dựa vào số đếm trên UI. Hạn mức Editor là chính sách tài khoản riêng, không áp lịch Guest cho Editor.

## 4. Phạm vi và mức ưu tiên

### 4.1 Luồng bắt buộc của MVP — P0

P0 là luồng video thực → tái dựng → xác nhận mét → duyệt/chỉnh vật → geometry/collider → chỉnh bố trí → OpenUSD → kiểm định Isaac → Reviewer duyệt → release. Người dùng phải sửa được một trường hợp thiếu vật hoặc grouping sai, và thao tác thêm/di chuyển/xóa vật phải có hiệu lực ở scene xuất ra.

MVP còn cần bằng chứng LiDAR tại mục 4.2 và các phép đánh giá tại mục 10. Walk trong browser, demo phát lại hoặc mở được USD bằng thư viện không thay thế luồng kiểm định Isaac.

### 4.2 Bằng chứng đóng góp của LiDAR

Giữ yêu cầu chứng minh trên ít nhất một RGB + registered/fused LiDAR run của **cùng scene/traversal**. LiDAR phải tạo `LiDARGeometryArtifact`, được căn chỉnh về scene, rồi được sử dụng thực sự bởi ít nhất một collider, scene geometry hoặc phép validation. Manifest phải chỉ ra nguồn, transform, checksum và consumer đó.

Có thể tái sử dụng RGB artifact đã bất biến, có checksum và cùng scene; không cần chạy lại toàn bộ reconstruction chỉ để tạo evidence. Bằng chứng này không bắt buộc LiDAR-only có đủ mọi tính năng Object/Edit/Review/Release của luồng RGB. Việc chỉ upload hoặc hiển thị point cloud không đạt G-04.

### 4.3 Chức năng hỗ trợ có điều kiện

Code hiện có nhánh nhập 3DGS, RGB kết hợp LiDAR, ghép scan có quỹ đạo, odometry tùy chọn và căn chỉnh hỗ trợ. Chúng chỉ được nhận xử lý khi đủ dữ liệu, runtime và cấu hình tương ứng. Có nhánh trong code không biến nhánh đó thành release blocker mới hoặc thành cam kết mọi input đều chạy được.

Nhập Gaussian dựng sẵn phù hợp để kiểm tra chỉnh vật/collision. Nó không chứng minh video→3D end-to-end. LiDAR-only đầy đủ vẫn là phạm vi mở rộng P1. Các khả năng vá nền, gợi ý nhãn hoặc thay asset phải công bố giới hạn; không coi kết quả suy đoán là dữ liệu được quan sát.

### 4.4 Ngoài mục tiêu MVP

MVP không thay thế simulator, SLAM/Nav2 hoặc CAD khi chúng đã đủ cho bài toán. Không cam kết tự động hoàn toàn, metric scale chính xác từ monocular RGB, xử lý mọi video, vật mềm/khớp động, nhiều tầng, không gian ngoài trời lớn hoặc photorealistic completion của vùng chưa từng quay.

Không bao gồm điều khiển robot thật, tự học policy, multi-tenant SaaS hoàn chỉnh, nhiều simulator hay chứng nhận an toàn vận hành ngoài đời. Những mục này chỉ được đưa vào roadmap bằng yêu cầu riêng.

## 5. Dữ liệu đầu vào và điều kiện sử dụng

### 5.1 Video RGB

Luồng chính cần video giải mã được, camera di chuyển, có thị sai và vùng nhìn chồng lặp, cảnh chủ yếu tĩnh. Vùng cần kiểm thử phải xuất hiện trong dữ liệu. Video camera giám sát cố định không được coi là đủ để tái dựng toàn bộ không gian.

Chuẩn bị video trên thiết bị có lựa chọn 1080p/720p/480p, mặc định 720p. Giữ hướng hiển thị, tỷ lệ khung hình và thời gian nguồn; không crop, upscale hoặc lặp frame để giả tạo dữ liệu. Profile hiện giới hạn tối đa 30 FPS theo presentation timeline. Codec, HDR, audio hoặc giới hạn thiết bị không phù hợp phải có thông báo và hướng xử lý. Chỉ tải bản gốc khi người dùng chủ động chọn và đường tiếp nhận cho phép.

Server xác minh bytes đã nhận. File gốc còn trên thiết bị và hash do client khai báo không phải bằng chứng server đã lưu/xác minh file gốc đó.

### 5.2 RGB và LiDAR

Dữ liệu kết hợp phải cùng địa điểm, có vùng chồng lặp và thông tin đơn vị/hệ tọa độ. Recipe cần quỹ đạo, timestamp hoặc calibration thì phải yêu cầu đủ các dữ kiện đó. Scan thô chỉ được xử lý qua nhánh ghép/odometry được hỗ trợ; không suy ra rằng mọi chuỗi scan đều hợp lệ.

Nếu dùng căn chỉnh tự động, người dùng phải xem kết quả và thông tin chất lượng phù hợp trước khi chấp nhận nguồn geometry. Thiếu scale/calibration hoặc runtime không phải lý do để âm thầm ghép hai nguồn khác hệ tọa độ.

### 5.3 Scene 3DGS nhập sẵn

File Gaussian tương thích có thể được mở để xem hoặc xử lý tiếp khi đủ capability. Phải giữ nguồn và giới hạn định dạng: PLY/SOG không tự cung cấp camera, ảnh gốc, metric scale hoặc chất lượng geometry đã được xác nhận.

Khi thiếu dữ kiện cho bước tiếp theo, hệ thống yêu cầu người dùng bổ sung/xác nhận hoặc báo nhánh không khả dụng. Không tạo provenance COLMAP/Brush giả cho scene bên ngoài và không coi giải mã định dạng nén là khôi phục được thông tin đã mất.

### 5.4 Điều kiện tiếp nhận chung

Người upload phải khai báo nguồn, quyền sử dụng và tình trạng dữ liệu nhận dạng cá nhân. File rỗng, hỏng, không đúng định dạng hỗ trợ hoặc thiếu dữ kiện quyết định phải được từ chối/giữ chờ với lý do cụ thể trước bước không thể thực hiện.

Thư viện mẫu là dữ liệu đã chuẩn bị sẵn, có nguồn và checksum. Việc người dùng mở mẫu không đồng nghĩa một job reconstruction mới đã chạy. Chính sách ẩn danh và giữ dữ liệu được quy định tại NFR-05.

## 6. Hành trình người dùng

### 6.1 Từ video tới scene chỉnh sửa được

| Bước | Người dùng thực hiện | Hệ thống phải thể hiện |
| --- | --- | --- |
| 1. Chuẩn bị input | Chọn file, tên scene, quyền dữ liệu và thông số | Dữ liệu nhận được, nhánh xử lý khả dụng, thiếu gì và lý do không chạy được |
| 2. Theo dõi job | Gửi xử lý; xem hoặc rời trang rồi quay lại | Tiến trình được lưu, việc đang làm, lỗi/chờ GPU và hành động tiếp theo |
| 3. Duyệt dữ liệu đã che nếu cần | Xem và chấp nhận hoặc hủy | Bản dữ liệu đúng lượt xử lý; không chạy dựng hình trước khi đủ điều kiện privacy |
| 4. Xác nhận hệ mét | Chọn tham chiếu kích thước và mặt sàn | Preview, scale áp dụng và nguồn xác nhận; chưa xác nhận thì nêu rõ đang chờ |
| 5. Duyệt vật | Kiểm tra đề xuất, sửa vùng/membership | Draft cho xem Gaussian và vỏ xem trước; không trình bày nó như collider đã hoàn tất |
| 6. Tạo geometry | Chấp nhận vùng và yêu cầu tạo mesh | Tiến trình geometry, lỗi chất lượng và trạng thái sẵn sàng theo đúng kết quả |
| 7. Chỉnh bố trí | Sửa vật/collider, thêm/xóa, lưu revision | Thay đổi có hiệu lực ở dữ liệu đã lưu và các biểu diễn đang dùng |

Đây là các điểm tương tác, không phải số lượng approval gates. Duyệt bản che có điều kiện; mặc định hiện tại có xác nhận mét và duyệt vật trước tạo mesh. Cấu hình tự tạo geometry không thay quyền approve release.

### 6.2 Từ scene tới bản phát hành

Người dùng chọn cấu hình robot và bài thử, gửi revision cần kiểm định. Hệ thống kiểm preflight và khả năng export, tạo candidate bất biến, chạy Isaac trên candidate đó và công bố report/evidence. Reviewer xem kết quả rồi approve hoặc reject.

Lưu Draft chỉ lưu công việc. Tạo package chỉ chuẩn bị candidate. Cả hai chưa cấp approval. Chỉ candidate đủ điều kiện mới được đưa vào review; release phải đóng dấu đúng candidate/report đã được duyệt theo FR-10 và FR-11.

### 6.3 Lỗi, sửa lại và tiếp tục công việc

UI phải phân biệt chờ người, chờ tài nguyên, đang xử lý, thất bại và đã hủy. Lỗi cần chỉ ra bước, nguyên nhân có thể công bố và hành động phù hợp. Không trình bày thời gian hoặc thành công giả cho bước được tái sử dụng/không chạy.

Khi retry, hệ thống chỉ tái sử dụng output/checkpoint có identity phù hợp. Khi sửa scene đã kiểm định hoặc bị reject, tạo revision mới và giữ lịch sử; kết quả cũ không tự áp cho dữ liệu mới.

### 6.4 Thử mẫu công khai

Người chưa đăng nhập có thể mở phiên demo được cho phép. Phiên có dữ liệu làm việc và thời hạn riêng; thay đổi không được làm hỏng bản mẫu gốc hay dữ liệu nhóm. Các thao tác vượt scope, cần runtime chưa có hoặc cần quyền Reviewer phải bị chặn và giải thích.

Phiên demo không đồng nhất với Guest signup, quota tài khoản hoặc bằng chứng chạy một video mới.

## 7. Yêu cầu chức năng

### FR-00 — Web Studio và xem 3D

Browser desktop được hỗ trợ phải render 3DGS thật do Brush tạo trong luồng RGB và cho orbit/pan/zoom, chọn vật, bật/tắt các lớp inspection phù hợp. Visual, geometry, point cloud và collider phải có tên/vai trò rõ; không thay mesh hoặc point cloud cho 3DGS rồi gọi là đã đạt yêu cầu Visual.

WebGL2 là baseline; WebGPU là tùy chọn khi khả dụng và được kiểm chứng, không phải điều kiện bắt buộc của client. Phải kiểm đường render được hỗ trợ bằng output producer thật, không chỉ bằng khả năng khởi tạo renderer.

Nếu thiếu artifact, không tương thích định dạng hoặc renderer không dùng được, UI báo nguyên nhân và phần còn xem được. Tính tương thích WebGL/WebGPU phải có evidence riêng trên browser, không suy từ test component.

### FR-01 — Tạo scene và tiếp nhận dữ liệu

Lưu input đã nhận cùng checksum, kích thước, nguồn và cấu hình lựa chọn. Xác định route dựa trên nội dung và dữ kiện, không chỉ tên file. Cần hiển thị các file thực sự tham gia và file chưa được dùng.

Request tạo job được chấp nhận phải truy vết/idempotent khi luồng yêu cầu, tránh tạo job hoặc tính quota hai lần do người dùng gửi lại. Input đã nhận không bị mất chỉ vì xử lý thất bại, ngoại trừ việc xóa theo chính sách dữ liệu đã công bố.

### FR-02 — Kiểm điều kiện trước xử lý

Kiểm khả năng đọc, chất lượng và thông tin cần cho route tại mục 5. Phát hiện sớm được gì thì báo sớm; không hứa biết đầy đủ camera registration trước khi bước ước lượng camera thực sự chạy.

Mỗi blocker có mã, thông điệp dễ hiểu và hướng khắc phục. Runtime không phù hợp phải hiện là không khả dụng, không tự đổi sang một phép xử lý có ý nghĩa khác để báo thành công.

### FR-03 — Job dài hạn

Job chạy ngoài vòng đời HTTP, có trạng thái `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, stage và attempt. UI rời trang không tự dừng job. Tiến trình phải thể hiện kết quả đã ghi nhận và bước chờ người/tài nguyên.

Hỗ trợ cancel/retry theo quyền và policy; worker chết hoặc công cụ treo phải có hướng phục hồi thay vì giữ trạng thái đang chạy vô hạn. Không báo stage thành công khi thiếu output bắt buộc. Không yêu cầu xây thêm batch/priority scheduling để đạt FR này.

### FR-04 — Tái dựng RGB

Tạo frame, camera/intrinsics/poses, visual và geometry cần thiết từ input hợp lệ; lưu thông tin chất lượng và output mỗi bước. Preview cho người dùng kiểm tra trước khi tiếp tục.

Visual preview và kết quả cuối có thể khác cấu hình/identity. Có preview không tự cho phép gọi scene đã sẵn sàng collision, export hoặc kiểm định.

### FR-05 — Geometry từ LiDAR

Giữ đơn vị, hệ tọa độ, alignment và nguồn của artifact LiDAR. Consumer downstream phải xác minh đúng dữ liệu và transform khi sử dụng. Nghiệm thu contribution theo mục 4.2; không chỉ chứng minh parser đọc được file.

Nhánh odometry/căn chỉnh được phép từ chối input không đủ điều kiện; không biến số đo độ lệch của chính input thành ground truth độc lập.

### FR-06 — Xác nhận hệ mét và căn chỉnh

Có ít nhất luồng chọn hai điểm, nhập khoảng cách thực, xem rồi xác nhận scale. Có thể dùng nguồn cảm biến đáng tin cậy khi phù hợp, nhưng phải lưu bằng chứng và người/cơ chế xác nhận.

Scale, hướng sàn và transform phải áp nhất quán lên camera, visual, geometry và vật thể. Cảnh chưa xác nhận mét không được vượt gate xuất/duyệt cần metric. Ước lượng tự động không tự trở thành xác nhận của người dùng.

### FR-07 — Đề xuất vật thể và sửa cách tách

Tạo đề xuất tự động trước khi người dùng sửa, giữ identity và nguồn để phân biệt đề xuất với xác nhận. Hỗ trợ đặt tên, confirm/ignore và correction tối thiểu: gộp, tạo vật bị thiếu, gán lại vùng/membership bị sai.

Cho kiểm tra thay đổi vùng trước khi áp dụng, giữ liên kết với source/revision. Sau sửa, chỉ geometry bị ảnh hưởng cần được tạo lại khi dữ liệu cho phép; không yêu cầu reconstruction lại toàn cảnh. Chỉnh vùng không đồng nghĩa tự xác nhận object hoặc đã có mesh đạt chất lượng.

### FR-08 — Chỉnh SceneObject nhất quán

Hỗ trợ đổi tên, move/rotate, thêm vật cơ bản và xóa/vô hiệu hóa vật đã tách. Các biểu diễn phải theo canonical transform và trạng thái vật. Phân biệt ẩn lớp để xem với thao tác làm vật không tham gia physics.

Khi move/delete, loại collision nguồn thuộc vật ở vị trí cũ, compose collider tại vị trí/trạng thái mới và bảo toàn sàn/tường/vật khác. Xóa vật không được phục hồi collision của nó vào nền. Không bắt buộc vá hình ảnh hoàn hảo vùng chưa quan sát, nhưng giới hạn đó phải nhìn thấy được.

### FR-09 — Geometry, collider và chất lượng

Cho xem collider chồng với visual, chỉnh loại/tham số/transform theo capability được hỗ trợ và lưu vào revision. Floor cùng các obstacle bắt buộc cần representation collision hợp lệ; không lấy vỏ xem trước hay box hiển thị làm proof collider cuối.

Thiếu topology, geometry không hợp lệ hoặc chất lượng không đạt phải được báo/block đúng policy. Không âm thầm thay mesh bằng box/hull, xóa bề mặt dùng chung hoặc chỉ dựa vào `watertight` để kết luận an toàn vật lý. Scene chờ duyệt geometry phải khóa các thao tác cần geometry sẵn sàng.

### FR-10 — Revision, review và release

Lưu lịch sử sửa, tác giả, review, thời điểm và lý do reject. Scene revision, trạng thái geometry, job và validation run là các trạng thái khác nhau; không dùng một nhãn “xong” cho tất cả.

Sửa scene sau validation tạo revision mới, làm bằng chứng/approval cũ không còn áp cho revision đó. Chỉ Reviewer được approve/reject; automation không tự approve. Release bind chính candidate checksum, report và approval đã được chọn, không rebuild candidate sau approve rồi coi là cùng bản. Retry thao tác phát hành không được tạo nội dung mâu thuẫn.

### FR-11 — OpenUSD và kiểm định Isaac

Export phải giữ các yêu cầu scene: đơn vị/trục, object hierarchy và transform, geometry/collider, physics, asset reference, cùng visual khi profile yêu cầu. Khả năng thực tế của exporter/runtime quyết định profile nào được hỗ trợ; thiếu capability phải block, không bỏ vật/physics hoặc hạ profile âm thầm.

Candidate được tạo trước validation và bất biến. Isaac phải tải đúng gói, kiểm floor/obstacle, robot spawn, các cặp Start–Goal và trả `CLEAR`, `BLOCKED` hoặc `ERROR`. Policy quyết định check/path nào bắt buộc; nhãn ground truth của evaluator không được truyền vào để quyết định kết quả quan sát.

Report và media/logs là evidence riêng, bind đúng candidate/run. Cố gắng tạo replay/screenshots; lỗi capture phải được báo riêng, không sửa kết quả physics đã quan sát. Điều kiện media của demo chính vẫn áp theo AC-07/AC-08. USD có Gaussian chưa tự chứng minh simulator đã render Gaussian hoặc robot đã chạy đúng.

### FR-12 — Preflight và quyết định điều kiện tiếp tục

Preflight kiểm metric, transform/bounds, object confirmation, representation/collider và artifact cần thiết trước build. Capability export và kiểm định Isaac là các kiểm tra riêng, không gộp chúng thành một PASS chung.

Blocker phải ngăn bước phụ thuộc; warning cần được hiển thị và chấp nhận rõ khi policy cho phép. Giải thích tự động chỉ hỗ trợ người đọc, không thay kết quả gốc hoặc lách gate.

### FR-13 — Manifest và truy vết

Mỗi release phải xác định được input, config, phần mềm/runtime, scene revision, inventory/checksum artifact, validation run/report và quyết định của Reviewer. Cảnh báo đã chấp nhận phải gắn đúng bản được duyệt.

Giữ bằng chứng gốc để phân biệt dữ liệu quan sát, dữ liệu suy đoán, artifact tái sử dụng và output được tạo mới. Không ghi secret hoặc địa chỉ truy cập chứa credential vào manifest.

## 8. Yêu cầu phi chức năng

### NFR-01 — Tái lập và giải thích kết quả

Người khác trong nhóm phải dùng manifest để xác định đúng input/config/runtime/artifact của một run. Lưu seed khi công cụ hỗ trợ. Phân biệt mở lại đúng artifact đã phát hành với chạy lại thuật toán; không hứa output GPU giống từng byte nếu chưa chứng minh tính quyết định.

### NFR-02 — Hiệu năng và giới hạn dữ liệu

Công bố giới hạn input, tài nguyên và profile đo theo cấu hình thực tế. Đo thời gian xử lý, tải scene, phản hồi chỉnh vật và peak RAM/VRAM riêng; không dùng số đo local/in-process làm độ trễ production.

UI phải còn thao tác được trong phạm vi thiết bị hỗ trợ. Scene vượt khả năng máy cần cảnh báo hoặc profile phù hợp. Ngưỡng đạt/rớt theo mục 2.2, không thêm SLA không có benchmark.

### NFR-03 — Phục hồi và toàn vẹn dữ liệu

Giữ revision đã lưu, artifact đã publish và lịch sử khi worker/UI mất kết nối hoặc xử lý thất bại. Tác vụ cũ không được ghi đè revision mới. Cancel, retry, process timeout và tài nguyên chờ quá hạn phải kết thúc có trạng thái rõ.

Xóa/khôi phục theo quyền và chính sách retention; thử lại không ghi đè release bất biến hoặc tự thay input đã được khóa.

### NFR-04 — Bảo mật và phân quyền

Server thực thi ma trận quyền tại mục 3; không dựa vào nút bị ẩn trên frontend. Khi chạy staging/production phải bật auth. Upload không được thực thi như mã, truy cập file phải nằm trong boundary đã cho phép.

Secret không nằm trong source, output công khai hoặc log. Quyền dùng demo tạm không được mở rộng sang API của nhóm hoặc phiên người khác.

### NFR-05 — Quyền riêng tư và vòng đời dữ liệu

Dữ liệu có thông tin nhận dạng phải được xử lý theo chính sách công bố trước khi chia sẻ/đưa vào kết quả công khai. Người upload vẫn phải khai quyền sử dụng và tình trạng riêng tư; detector không thể thay lời khai hoặc bảo đảm phát hiện hết.

`self_attested` dựa trên lời khai, không phải proof đã ẩn danh. `qa_verified` yêu cầu bước che tự động cho video upload; khi có frame bị che, người upload xem/chấp nhận đúng bản trước reconstruction. Không có frame bị che có thể đi tiếp theo policy, nhưng không được trình bày là người dùng đã tự duyệt hay đã xác minh không còn PII.

Không dùng dữ liệu chưa đáp ứng chính sách để tiếp tục xử lý/chia sẻ; phải chặn hoặc giới hạn phù hợp. Source, bản che, thumbnail và artifact dẫn xuất cần lineage và boundary tương ứng. Thời gian giữ input/artifact, phiên demo, thùng rác và cách xóa phải được công bố theo deployment; không mặc định giữ vĩnh viễn hay tự nhận đáp ứng mọi quy định pháp lý.

### NFR-06 — Tương thích

Khóa profile simulator, OpenUSD, worker image/runtime và môi trường browser cho từng acceptance run. Ghi version/driver/hardware ảnh hưởng kết quả. Tương thích ở parser, USD authoring, simulator physics và browser renderer là các kiểm chứng khác nhau.

### NFR-07 — Quan sát và số đo trung thực

Job có ID/attempt/stage, thời điểm, error code và đường tới artifact/log trong boundary cho phép. Người dùng phải biết đang chờ ai/cái gì, lỗi ở đâu và có thể làm gì tiếp.

Telemetry cần phân biệt tổng thời gian, thời gian tool, thời gian chờ và thao tác người. Trường thiếu phải ghi thiếu/partial; không cộng các span không đầy đủ rồi gọi là tổng end-to-end.

### NFR-08 — Ranh giới hệ thống

Scene và invariant không phụ thuộc UI hoặc một scene demo riêng. Runtime chuyên môn giao tiếp qua hợp đồng/identity được kiểm tra. Có thể thay nhà cung cấp compute mà không thay ý nghĩa scene; không cần xây trước mọi domain/simulator adapter để hoàn thành MVP.

## 9. Tiêu chí nghiệm thu

Các AC dưới đây là phép thử trên build, dữ liệu và môi trường đã khóa. Test unit/fixture là kiểm tra hỗ trợ; không tự đánh dấu các AC cần browser/GPU/Isaac là đạt.

### AC-01 — Luồng RGB đầu-cuối

Dùng video của scene demo chính. Chạy từ input mới tới reconstruction, xác nhận mét, sửa vật, build geometry, chỉnh scene, export, Isaac validation và Reviewer release. Bằng chứng gồm job/attempt, input checksum, artifact inventory và chuỗi candidate→report→approval→release cùng identity. Không thay stage chưa chạy bằng dữ liệu mẫu mà vẫn tính end-to-end.

### AC-02 — Từ chối input không phù hợp

Dùng ít nhất video hỏng/không đủ điều kiện camera và point cloud rỗng hoặc thiếu metadata bắt buộc. Hệ thống dừng trước bước không thể thực hiện, trả blocker có hướng khắc phục, không tạo output giả thành công. Cùng bài thử phải phân biệt input lỗi với runtime chưa được cấu hình.

### AC-03 — Xác nhận mét

Dùng khoảng cách tham chiếu đã đo và dung sai khóa trước. Sau xác nhận, đo lại khoảng cách trong scene và kiểm các biểu diễn dùng cùng scale. Thử bỏ xác nhận để chứng minh gate cần metric bị chặn. Ghi nguồn/khoảng cách chuẩn, người xác nhận, kết quả và sai số.

### AC-04 — LiDAR được sử dụng thật

Thực hiện evidence run ở mục 4.2. Từ manifest phải lần được `LiDARGeometryArtifact` qua alignment/composition tới consumer đang dùng geometry đó. Kiểm checksum, transform và cùng scene của artifact RGB tái sử dụng. Chỉ mở file hoặc xem point cloud không đạt AC này.

### AC-05 — Đề xuất và correction vật thể

Giữ bản đề xuất trước sửa và bản sau sửa trên scene khóa, gồm ít nhất một vật bị thiếu hoặc grouping sai. Thực hiện correction tối thiểu của FR-07 mà không reconstruction lại toàn cảnh; kiểm membership, revision và phần geometry được tạo lại. Báo độ phủ/công sửa theo SM-05, không lấy trạng thái CONFIRMED lưu sẵn làm bằng chứng có người đã thao tác.

### AC-06 — Nhất quán chỉnh sửa

Move/rotate một vật đã có geometry, lưu rồi mở lại. So sánh transform của visual/geometry/collider và vị trí collision trước/sau, gồm vùng vị trí cũ. Vật khác, sàn/tường phải còn nguyên trong phạm vi thử; kết quả số theo epsilon đã khóa. Chỉ xem khung collider di chuyển cùng Gaussian chưa đủ kiểm collision môi trường.

### AC-07 — Review và release gate

Thử gọi thao tác approve bằng tài khoản không có quyền; thử candidate thiếu validation và candidate đã thay đổi; tất cả phải bị từ chối. Với run hợp lệ, Reviewer mở report, cảnh báo và evidence đúng candidate, reject có lý do hoặc approve đúng identity. Sửa scene sau đó phải làm approval cũ không áp được. Demo chính cần replay/screenshots mở được trên Web trước khi công nhận review flow.

### AC-08 — Kiểm định trong Isaac

Nạp candidate demo chính vào runtime đã khóa; kiểm floor, collider cần thiết và robot spawn. Chạy 5/5 cặp Start–Goal, lưu kết quả quan sát và đối chiếu SM-04 bằng evaluator riêng. Run phải có report/log và replay/screenshots bind đúng candidate; `ERROR` hoặc runtime không chạy không được diễn giải là CLEAR/PASS.

### AC-09 — Lỗi và thử lại

Chủ động gây một lỗi stage và một tình huống worker bị gián đoạn trong môi trường thử. Kiểm trạng thái/lỗi có thể khắc phục, input/revision được giữ và attempt mới không ghi đè output bất biến. Nếu reuse checkpoint/stage, phải chứng minh identity hợp lệ; kiểm quota/idempotency cho luồng Guest liên quan.

### AC-10 — Truy vết bản phát hành

Một thành viên không trực tiếp tạo scene dùng release manifest tìm đúng input, config/runtime, scene revision, candidate, validation và approval. Kiểm đủ dependency/checksum và mở đúng gói đã seal. Báo riêng khả năng truy vết artifact với kết quả chạy lại pipeline nếu có.

### AC-11 — Viewer trên browser

Trên browser desktop được hỗ trợ, mở 3DGS thật do Brush tạo trong luồng RGB, đổi các lớp kỹ thuật, orbit/pan/zoom, chọn/chỉnh vật và kiểm lỗi artifact. Ghi build/browser, renderer WebGL2/WebGPU, format/producer/version/checksum của artifact và video/ảnh thao tác. Synthetic splats, test DOM hoặc view mesh không thay proof render 3DGS thật.

### AC-12 — Thay đổi bố trí và hệ quả bài thử

Tạo bố trí A, thêm/move/rotate vật cản để thành B, rồi xóa cả vật thêm và ít nhất một vật tái dựng trong các revision thử tương ứng. Kiểm active objects, visual tách riêng, collider và collision nền sau từng thao tác; không còn vật cản giả ở vị trí cũ, không mất sàn/tường do xóa nhầm.

Dùng cùng robot/footprint, bộ điều khiển hoặc phép kiểm đường đi và cấu hình quan sát cho các bố trí được so sánh trong Isaac. Kết quả phải phản ánh layout đã lưu/xuất. Nếu chỉ thử được Walk, ghi nhận browser preview, chưa công nhận phần thử robot trong simulator.

## 10. Đánh giá sản phẩm

### 10.1 Phạm vi dữ liệu

Bộ nghiệm thu cần một scene thực từ video trong nhà và một scene/case có kiểm soát để chủ động thử lỗi. Indoor Room phù hợp kiểm chỉnh vật; warehouse synthetic có thể cung cấp đối chứng; video thực kiểm điều kiện thu nhận. Không dùng kết quả một nhóm để suy ra chất lượng nhóm khác.

Trước chạy kết quả cuối, khóa input/checksum, frame split, vật cản mục tiêu, kích thước chuẩn, geometry tham chiếu độc lập, robot/footprint, 5 cặp Start–Goal và nhãn kỳ vọng, config và môi trường. Dữ liệu chỉ để đánh giá không được đưa vào nhánh dự đoán/validation sản phẩm.

### 10.2 Nhóm phép đo

| Nhóm | Phép đo cần báo cáo | Giới hạn diễn giải |
| --- | --- | --- |
| Chất lượng tái dựng theo yêu cầu RAV-01 | PSNR, SSIM, LPIPS, Chamfer Distance, thời gian dựng/train và hiệu năng render | Image metric không thay physics; Chamfer cần reference độc lập, thiếu thì ghi chưa đo |
| Tính đúng của scene | Sai số mét, object coverage/correction, consistency sau edit, false collision và vật cản bị bỏ sót | Chỉ áp cho input, vùng có đối chứng và protocol đã khóa |
| Dùng trong simulator | Load, spawn, floor/collision, kết quả path và end-to-end | Có package hoặc preflight PASS chưa chứng minh nhóm này |
| Giá trị công việc | Human active time, manual step count, time-to-usable-scene | Cùng đầu vào, người thực hiện/điều kiện được ghi, cùng chuẩn đầu ra với manual baseline |
| Vận hành | Stage/tool/wait time, GPU-hours, peak RAM/VRAM, tải scene và độ trễ chỉnh sửa | Ghi coverage, phần cứng và local/cloud; không ước tính số còn thiếu thành số đã đo |

Protocol, công thức và vị trí evidence thuộc tài liệu đánh giá, không lặp trong PRD. Không đổi threshold sau khi thấy kết quả để biến run thất bại thành đạt.

### 10.3 Xác thực nhu cầu và giá trị

Phỏng vấn người thực sự chuẩn bị simulation scene về một công việc gần đây, đầu vào/công cụ, công đoạn tốn công và cách cập nhật bố trí. Kế hoạch trong MASTER_PITCH đề xuất 5–8 người; số đó là kế hoạch discovery, không phải khách hàng đã xác thực.

Chỉ công bố tiết kiệm thời gian, độ tin cậy cao hơn hoặc lợi thế so với công cụ khác khi có benchmark công bằng. Demo kỹ thuật và xác thực nhu cầu là hai kết quả riêng.

## 11. Rủi ro và thông tin cần khóa

| Rủi ro | Hệ quả cần kiểm soát | Thông tin/hành động cần có |
| --- | --- | --- |
| Video thiếu thị sai, blur hoặc vùng bị che | Reconstruction không đủ dữ liệu | Phạm vi input được hỗ trợ, hướng dẫn thu nhận, case từ chối và scene thực để kiểm |
| Monocular không có mét tuyệt đối | Collision/khoảng hở sai kích thước | Tham chiếu đo và dung sai trước nghiệm thu |
| Grouping/membership và collision ownership sai | Vật còn va chạm ở vị trí cũ hoặc mất sàn/tường | Correction case, đối chứng hình học và kiểm trước/sau edit |
| Vùng chưa quan sát bị vá/suy đoán | Hình ảnh có vẻ đầy đủ nhưng không có proof bề mặt | Nhãn provenance và giới hạn collision claim |
| Đổi runtime hoặc thiếu capability export/Isaac | Gói không bảo toàn scene hoặc không chạy được | Khóa runtime và chạy phép thử thật, không dùng parser-only proof |
| Thời gian người/máy chưa đo đủ | Kết luận giá trị sai | Protocol timer, span coverage và manual baseline |
| Scene dựng sẵn/Room thay cho input thực | Nhầm proof subsystem thành end-to-end | Gắn nhãn dataset/source và stage thực chạy |
| Chính sách retention/quyền dữ liệu chưa công bố | Không đủ điều kiện chia sẻ công khai | Chốt policy deployment trước demo công khai |

Các mục phải khóa trước nghiệm thu: scene/frame range thực tế, profile input/tài nguyên, reference scale/geometry, bộ robot/path, ngưỡng chất lượng, runtime/version, retention và nơi lưu bằng chứng. Không mặc định `Aisle_CW` là scene demo chính chỉ vì đã dùng ở giai đoạn trước.

## 12. Truy vết yêu cầu vào code

Bảng này chỉ chỉ ra nơi kiểm tra implementation, không xác nhận test hay runtime đã đạt. Model/OpenAPI là nguồn của schema chi tiết; các phép thử tại mục 9 mới quyết định nghiệm thu.

| Yêu cầu | Nguồn kiểm tra chính | Tiêu chí |
| --- | --- | --- |
| FR-00, FR-08 | [ScenePage](../frontend/src/features/studio/ScenePage.tsx), [scene commands](../src/api/product/scene.py) | AC-06, AC-11, AC-12 |
| FR-01, FR-02 | [input assemblies](../src/api/studio/assemblies.py), [input resolver](../src/services/reconstruction/inputs/input_resolver.py), [imports](../src/api/studio/imports.py) | AC-02 |
| FR-03 | [worker](../src/services/orchestration/jobs/worker_cli.py), [job runner](../src/services/orchestration/jobs/runner.py) | AC-01, AC-09 |
| FR-04, FR-05, FR-06 | [runner](../src/services/orchestration/jobs/runner.py), [metric API](../src/api/studio/metric.py) | AC-01, AC-03, AC-04 |
| FR-07, FR-09 | [objectify](../src/services/orchestration/scene/objectify.py), [geometry state](../src/services/scene/geometry_state.py) | AC-05, AC-06, AC-12 |
| FR-10, FR-13 | [review workflow](../src/services/orchestration/review/workflow.py), [release contracts](../src/models/contracts/release.py) | AC-07, AC-10 |
| FR-11, FR-12 | [simulation package](../src/services/orchestration/review/simulation_package.py), [validation gate](../src/services/orchestration/review/validation_gate.py), [Isaac process](../src/services/simulation/isaac/process.py) | AC-07, AC-08 |
| Quyền và quota | [auth API](../src/api/auth.py), [ownership](../src/api/ownership.py), [Guest quota](../src/services/orchestration/auth/quota.py) | AC-07, AC-09 và kiểm quyền theo route |
| Demo tạm | [demo session API](../src/api/demo_sessions.py) | Kiểm scope, cách ly thay đổi, hết hạn và khả năng phục hồi theo deployment |
| Chuẩn bị video và privacy | [video normalization](../frontend/src/lib/media/video-normalization-core.ts), [sanitization](../src/services/reconstruction/rgb/frames/frame_sanitization.py) | AC-02 và điều kiện NFR-05 |

## 13. Các mốc xác nhận sản phẩm

Không dùng lại lịch “bốn tuần” đã cũ để mô tả tiến độ hiện tại. Mỗi mốc dưới đây cần báo cáo riêng; thứ tự triển khai thực tế thuộc task/roadmap.

| Mốc | Bằng chứng để chuyển tiếp |
| --- | --- |
| Khóa bài toán và phép thử | Scene/input, tham chiếu, robot/path, baseline và ngưỡng được xác định |
| Reconstruction và hệ mét | Artifact thật mở được, scale được xác nhận, failure case được báo đúng |
| Chỉnh sửa scene có collision | Correction, move/delete, consistency và chất lượng geometry trên scene thực |
| Candidate dùng được trong simulator | Đúng package được Isaac tải/kiểm, report và media có provenance |
| Release và giá trị | Reviewer duyệt đúng candidate, truy vết được; benchmark giá trị được báo với giới hạn |

Không suy mốc đã đạt từ việc có source file, commit hoặc task được đánh dấu hoàn thành. Những phần đang thiếu evidence phải ở trạng thái chưa nghiệm thu.

## 14. Định nghĩa hoàn thành MVP

Chỉ công nhận MVP khi PRD được chủ dự án chấp thuận, các yêu cầu bắt buộc được kiểm trên bộ dữ liệu/môi trường đã khóa, có chủ thể xác nhận và bằng chứng gốc truy vết được. Toàn bộ AC-01…AC-12 phải có kết luận phù hợp phạm vi của từng AC; không đổi `SKIP`, thiếu runtime hoặc fixture-only thành PASS.

Các metric bắt buộc được đo/báo cáo với protocol và giới hạn; việc thiếu ground truth phải được công bố, không tạo số thay thế. Mọi ngưỡng được dùng làm gate tuân theo mục 2.2. Nếu thay một yêu cầu bắt buộc, phải có quyết định phạm vi rõ trước khi công bố hoàn thành theo phạm vi mới.

Tình trạng thực tế phải được cập nhật ở tài liệu trạng thái và báo cáo nghiệm thu, không viết ngược vào yêu cầu để khớp những gì đã làm xong. Claims về tiết kiệm công, simulator, khả năng tổng quát và an toàn phải tuân theo [claims policy trong MASTER_PITCH](MASTER_PITCH.md#phần-xi--claims-policy-những-gì-được-phép-tuyên-bố).

## Phụ lục — Thuật ngữ dùng trong PRD

| Thuật ngữ | Ý nghĩa |
| --- | --- |
| Visual / 3DGS | Biểu diễn ngoại hình để quan sát; không tự là collision |
| Geometry / surface | Dữ liệu không gian/bề mặt phục vụ xử lý hình học |
| Collider / physics | Biểu diễn dùng cho tương tác va chạm trong profile mô phỏng |
| Membership | Phần dữ liệu nguồn được gán cho từng vật hoặc nền |
| Draft / Ready về geometry | Chờ duyệt/tạo hình học hoặc đã có hình học theo luồng hỗ trợ; không phải approval release |
| SceneIR revision | Phiên bản scene được lưu, gồm vật, transform và các tham chiếu liên quan |
| CandidatePackage | Gói ứng viên bất biến để kiểm định, định danh bằng checksum |
| ValidationReport | Kết quả của run kiểm định đúng candidate, khác ảnh/video minh họa |
| Approved release | Candidate đã đủ kiểm định, được Reviewer duyệt và seal cùng report/approval |
