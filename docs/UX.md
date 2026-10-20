# Trải nghiệm sử dụng Real2Sim Studio

## 0. Phạm vi và cách đọc

Tài liệu mô tả người dùng vào đâu, xem được gì, cần làm gì tiếp và thao tác nào lưu thay đổi. Nội dung được đối chiếu với frontend và API trên `develop`, HEAD `ac0be875`, ngày 20/10/2026. Đây là bản chuẩn hóa chờ chủ dự án rà soát; chưa phải kết quả nghiệm thu trên trình duyệt, thiết bị hoặc deployment thật.

[PRD](PRD.md) giữ yêu cầu và quyền sản phẩm. [PIPELINE](PIPELINE.md) giải thích các bước xử lý bên trong. [CONTRACTS](CONTRACTS.md) giải thích dữ liệu, revision và bằng chứng. UX chỉ mô tả cách các nội dung đó xuất hiện và được thao tác trên giao diện.

Bản đặc tả cũ `STUDIO_UX_SPEC.md` đã bỏ ngày 20/10/2026; các mã D-xx/Q-xx còn gặp trong hồ sơ task cũ tra trong lịch sử Git.

### 0.1 Các khái niệm dùng trên giao diện

| Khái niệm | Cách hiểu khi sử dụng |
| --- | --- |
| Scene từ video | Công việc có dữ liệu nguồn, job xử lý và các revision scene khi đã tạo được |
| Preview 3DGS | Bản xem xuất hiện sớm; có thể chưa có đơn vị mét hoặc geometry dùng mô phỏng |
| Vật ứng viên | Vật hệ thống đề xuất tách; người dùng cần duyệt hoặc sửa vùng |
| Revision | Một bản nội dung scene đã được server lưu |
| Gói mô phỏng / candidate | Gói OpenUSD của một revision để kiểm tra; khác vật ứng viên |
| Validation | Lần kiểm tra một candidate theo policy cụ thể |
| Review và bản phát hành | Quyết định của Reviewer và kết quả đóng dấu đúng gói đã kiểm tra |
| Scene import | File 3DGS có sẵn được chuẩn bị để xem, khác job dựng từ video |

## 1. Điểm vào và điều hướng

### 1.1 Trang ứng dụng

Trong WebApp, `/` chuyển tới màn đăng nhập với đích sau đăng nhập là `/overview`. Landing giới thiệu sản phẩm là ứng dụng riêng. Người đã đăng nhập hoặc dùng chế độ local không yêu cầu đăng nhập được chuyển tiếp theo entry gate; không coi `/` là danh sách Scenes như tài liệu cũ.

Khung ứng dụng có thanh bên thu gọn, breadcrumb, menu tài khoản và điều khiển giao diện. Trên màn hẹp, thanh bên mở dạng ngăn trượt. Nguồn: [AppShell](../frontend/src/features/shell/AppShell.tsx), [routes](../frontend/src/lib/routes.ts), [AuthForms](../frontend/src/features/studio/auth/AuthForms.tsx).

| Vùng | Route | Công việc chính |
| --- | --- | --- |
| Tổng quan | `/overview` | Đọc tổng hợp và mở scene cần xử lý |
| Tạo scene mới | `/new` | Nhập chung video, LiDAR, metadata hoặc 3DGS |
| Scenes từ video | `/scenes` | Tìm, lọc và mở job/scene đã tạo |
| Scenes đã import | `/imports` | Theo dõi và mở file 3DGS đã nhập |
| Benchmark | `/benchmark` | So sánh các project đã đưa vào benchmark |
| Thùng rác | `/trash` | Khôi phục hoặc xóa hẳn theo quyền |
| Nhóm | `/team` | Quản lý thành viên và mã mời; mục điều hướng dành cho Reviewer khi bật auth |
| Tài khoản | `/account` | Xem thông tin phiên và đăng xuất |
| Thử mẫu | `/new/try-demo` | Chọn mẫu, đọc thông tin và xem tiến trình đã ghi |

`/new/import-video` hiện mở cùng form với `/new`. `/new/import-scene` còn là lối nhập 3DGS riêng. `/jobs` chuyển về `/scenes`; không có trang Jobs độc lập trong thanh bên hiện tại. Danh sách route thực tế nằm trong [frontend/src/app](../frontend/src/app/).

### 1.2 Tìm lại công việc

[Tổng quan](../frontend/src/features/studio/OverviewPage.tsx) hiển thị số scene từ video, số đang xử lý, số cần người dùng xử lý và số scene import. Mục “Scene đang chờ bạn” dẫn về công việc cụ thể. Khi API chưa trả dữ liệu, giao diện dùng dấu `—` hoặc trạng thái tải; lỗi đọc nguồn không được hiểu thành số lượng bằng 0.

[Scenes từ video](../frontend/src/features/studio/ScenesHome.tsx) có tìm theo tên, bộ lọc trạng thái, sắp xếp, lưới/danh sách và phân trang. Thẻ scene dẫn tới `/scenes/<jobId>` và hiển thị người tạo/người chạy lại khi có dữ liệu. Tìm không thấy do bộ lọc có đường xóa bộ lọc; khác với danh sách chưa có scene hoặc tải danh sách lỗi.

Scene import nằm trong [thư viện riêng](../frontend/src/features/studio/ImportedScenesHome.tsx). Chuyển vào thùng rác là thao tác có quyền của từng resource; không suy ra quyền xóa từ việc nhìn thấy thẻ scene.

## 2. Phiên đăng nhập, quyền và hạn mức

### 2.1 Ai có thể làm gì trên giao diện

Người chưa đăng nhập có thể vào vùng thử mẫu được công khai. Khi auth bật, mở trang làm việc cần tài khoản sẽ chuyển tới đăng nhập và giữ đường dẫn trở lại. Visitor chưa đăng nhập khác tài khoản có role Guest.

Guest có thể xem workspace chung và thao tác resource mình sở hữu. Editor/Reviewer có quyền can thiệp workspace theo PRD; UI vẫn nhận capability của từng resource từ server. Guest xem scene của người khác được mở bản xem chỉ đọc, không hiện form sửa hoặc xác nhận mét của chủ sở hữu.

Nút retry, cancel, xóa, tạo gói và sửa scene dùng capability tương ứng. Thiếu capability ở API cũ không được tự cấp quyền sửa cho Guest. Backend tiếp tục kiểm ownership khi nhận lệnh; ẩn/hiện nút không thay cơ chế phân quyền. Nguồn: [auth helpers](../frontend/src/lib/api/auth.ts), [ownership guard](../src/api/ownership.py), [StudioTab](../frontend/src/features/studio/scene/StudioTab.tsx).

### 2.2 Đăng ký và thông tin tài khoản

[Đăng ký](../frontend/src/features/studio/auth/AuthForms.tsx) có nhánh Guest và nhánh mã mời. Guest signup chỉ mở khi API báo `guest_signup_enabled=true`; khi đóng, giao diện nói rõ và đưa lối dùng mã mời. Mã mời quyết định quyền Editor/Reviewer, không có ô tự chọn role. Luồng hiện tại chưa xác minh email qua thư.

[Tài khoản](../frontend/src/features/studio/auth/AccountPage.tsx) hiển thị email, tên, role, trạng thái hoạt động và hạn mức lấy từ API. Trang này chủ yếu chỉ đọc và đăng xuất; không mô tả thành trang sửa hồ sơ hoặc đổi mật khẩu. Chế độ local nói rõ không có tài khoản, không tạo profile giả.

[Nhóm](../frontend/src/features/studio/auth/TeamPage.tsx) phục vụ quản lý thành viên, role, active, hạn mức và tạo mã mời theo quyền. Quyền duyệt/phát hành luôn cần phiên Reviewer thật, kể cả khi deployment local cho phép các thao tác làm việc khác không đăng nhập.

### 2.3 Hạn mức Guest được hiển thị thế nào

Guest có tối đa 3 lượt tạo job hoặc Retry thủ công được chấp nhận mỗi ngày, đặt lại lúc 00:00 giờ Việt Nam. Upload và phân tích input chưa tạo job, chưa trừ lượt; object/geometry operation không phải một lượt tạo reconstruction job mới.

Số còn lại và thời điểm đặt lại lấy từ backend qua [GuestQuotaStatus](../frontend/src/features/studio/auth/GuestQuotaStatus.tsx). Khi gửi lệnh bị từ chối vì hết lượt, trang tải lại hạn mức. Không dùng số cũ đang hiện để bảo đảm yêu cầu tiếp theo chắc chắn được chấp nhận.

## 3. Tạo scene từ dữ liệu riêng

### 3.1 Bước Chọn dữ liệu

[/new dùng UnifiedInputFlow](../frontend/src/features/studio/UnifiedInputFlow.tsx), gồm ba bước: **Chọn dữ liệu → Cấu hình xử lý → Xác nhận**. Người dùng thả nhiều file vào cùng một vùng; không cần chọn trước một màn riêng cho mỗi recipe kỹ thuật.

Form nhận video MP4/MOV, point cloud PLY/PCD, calibration, trajectory, timestamp, Gaussian PLY/SOG và ZIP trong phạm vi server nhận dạng được. Vai trò được phân tích từ nội dung; phần mở rộng không đủ để kết luận dữ liệu dùng được. Danh sách file cho biết đang chuẩn bị, đang upload, đang xác minh, đã sẵn sàng hoặc lỗi.

Người dùng có thể bỏ chọn file khỏi lần phân tích tiếp theo hoặc xóa file khỏi tập đang chuẩn bị. Thành phần không nhận ra vai trò được nêu rõ là bị loại. Hệ thống tự phân tích sau thay đổi; thiếu dữ kiện thì hỏi thêm về cùng cảnh, đơn vị, frame, chiều trajectory, clock hoặc timestamp. Các dữ kiện đã đọc được và dữ kiện người dùng khai báo có nguồn riêng.

Kết quả phân tích cho biết cách xử lý được đề xuất, file dùng, file bỏ qua, dữ kiện còn thiếu và lý do chưa chạy được. Một phương án cần bổ sung dữ liệu có nút “Dùng cách này”; người dùng hoàn tất thông tin để phân tích lại. Các trường hợp không hỗ trợ hoặc runtime chưa đủ điều kiện không được trình bày như job đã xếp hàng.

### 3.2 Chuẩn bị video trước upload

Video mặc định chuẩn bị ở 720p; có thể chọn preset khác trong giới hạn profile. Form giữ tỉ lệ khung hình và hiển thị tiến trình chuẩn bị riêng với tiến trình gửi file. Upload đạt 100% vẫn có thể đang kiểm nội dung, chưa đồng nghĩa input đã sẵn sàng.

Nếu bước chuẩn bị gặp lỗi có đường phục hồi phù hợp, UI có thể cho “Tải video gốc không nén”; không tự hạ yêu cầu hoặc đổi file âm thầm. Nguồn gốc video chuẩn hóa và giới hạn server xác minh được giải thích trong CONTRACTS.

Nút hướng dẫn quay tại đầu form mở [CaptureGuide](../frontend/src/features/studio/CaptureGuide.tsx). Hướng dẫn thu thập dữ liệu không phải cam kết mọi video đáp ứng mô tả đều sẽ tái dựng tốt.

### 3.3 Cấu hình và xác nhận tạo scene

Bước cấu hình dùng các lựa chọn server cung cấp, preset/kịch bản và kiểm tra tài nguyên. Mở thông số chi tiết khi cần; lỗi tải hoặc kiểm cấu hình có nút thử lại. Cấu hình chưa xác nhận hoặc vượt khả năng worker chặn bước gửi.

Bước cuối yêu cầu tên scene. Với video, người dùng khai báo nguồn, chủ sở hữu, mục đích, quyền sử dụng, tình trạng dữ liệu cá nhân và việc lưu dữ liệu/kết quả. Tự động che mặt/biển số có thể xuất hiện theo khả năng worker; nó là lớp bảo vệ thêm, không thay xác nhận nguồn dữ liệu.

Ngay cạnh nút bị khóa có danh sách “Còn thiếu để tạo scene”. Tóm tắt chỉ rõ file và cấu hình sẽ dùng. Bấm “Tạo scene” gửi lựa chọn đã được phân tích hợp lệ; thành công chuyển tới trang scene/job cụ thể. Với Gaussian dựng sẵn, nút là “Mở scene 3DGS”, chuyển sang scene import và nêu rõ chưa có luồng xử lý tiếp.

### 3.4 Rời form và quay lại

Upload tạm và bản nháp form thuộc phiên tài khoản/trình duyệt. Form có cơ chế khôi phục những upload còn hợp lệ, nhưng khi rời trang nó dừng các công việc chuẩn bị/upload và gửi yêu cầu bỏ upload tạm chưa dùng. Không dùng form này như nơi lưu input lâu dài hoặc hứa mọi upload sẽ tiếp tục sau khi đóng trình duyệt.

Sau khi server đã chấp nhận job, theo dõi công việc tại Scenes; lifecycle của job khác lifecycle form upload. Khi gửi lỗi, đọc thông báo trước khi thao tác tiếp, thay vì chọn lại dữ liệu hoặc tạo nhiều job để kiểm tra.

## 4. Trang scene và tiến trình

### 4.1 Bốn vùng làm việc

[`ScenePage`](../frontend/src/features/studio/ScenePage.tsx) giữ tên scene, trạng thái, số lần chạy khi có retry và thông báo hành động tiếp theo trong cùng ngữ cảnh job. Mặc định mở Tiến trình; bước mới hoàn tất không tự đổi tab người dùng đang đọc.

| Vùng | Điều kiện mở hiện tại | Nội dung |
| --- | --- | --- |
| Tiến trình | Khi mở được job | Các bước, điểm chờ, lỗi, lịch sử attempt |
| Studio | Có preview tải được | Xem 3DGS, xác nhận mét hoặc chỉnh vật theo trạng thái |
| Kiểm tra & duyệt | Điều kiện scene-ready của trang đã đạt | Gói, registration, validation và quyết định Reviewer |
| Kết quả | Có preview | File làm việc, candidate và release theo dữ liệu hiện có |

Tab chưa đủ điều kiện có lý do khóa. Link trỏ tới tab khóa đưa về Tiến trình kèm giải thích. Việc tab được mở không bảo đảm mọi artifact bên trong đã có; panel tiếp tục kiểm revision và dữ liệu cần thiết.

Studio chiếm toàn màn hình ứng dụng, có nút thoát về Tiến trình. Viewer được giữ sau lần mở đầu để quay lại không phải nạp lại toàn bộ scene; khi Studio không hiển thị, viewer nghỉ và thoát Walk. `tab`/`mode` có trong URL, nhưng chỉ chế độ hợp lệ và được bật mới dùng được.

### 4.2 Đọc tiến trình và điểm chờ

[Tiến trình](../frontend/src/features/studio/scene/ProgressTab.tsx) hiển thị các bước backend trả về; nhánh LiDAR hoặc geometry review có thể thêm bước tương ứng. Không dùng một danh sách cố định 5 hay 8 bước để giải thích mọi scene.

| Trạng thái người dùng thấy | Cách hiểu và xử lý |
| --- | --- |
| Chờ máy xử lý/runtime/tài nguyên | Yêu cầu đã nhận nhưng chưa chạy được; đọc lý do và tiếp tục chờ theo trạng thái server |
| Đang xử lý | Xem bước hiện tại, thời gian và lần cập nhật gần nhất |
| Chờ xem bản đã che | Cần người có quyền kiểm tra và chấp nhận trước khi dựng 3D |
| Chờ tỉ lệ mét | Mở công cụ xác nhận trong Studio |
| Chờ duyệt vật / tạo mesh | Mở Studio để xử lý candidate hoặc chờ geometry operation |
| Lỗi một bước | Đọc lỗi tại bước và dùng đúng nút phục hồi được cung cấp |
| Mất kết nối cập nhật | Tải lại trạng thái; chưa có căn cứ kết luận job đã thất bại |

Nút hành động xuất hiện tại hàng bước cần xử lý; chuông ở đầu scene tổng hợp việc tiếp theo. Thời gian máy chạy, thời gian chờ và thời gian người dùng xác nhận có ý nghĩa khác nhau. Thanh chờ không có phần trăm đo được dùng trạng thái không xác định, không chạy phần trăm giả.

### 4.3 Hủy, thử lại và mở kết quả từng bước

Hủy reconstruction job, hủy geometry operation và hủy validation run là các thao tác riêng. Nút “Huỷ xử lý” có xác nhận; gửi yêu cầu chưa phải bằng chứng process đã dừng. Đóng trang theo dõi không tự hủy job server.

“Thử lại” chỉ mở khi lỗi cho phép, người dùng có quyền và hạn mức còn phù hợp. Trang đợi backend xác nhận attempt mới trước khi báo đã chạy lại; lỗi mạng khi gửi có thể ở trạng thái chưa rõ. Lịch sử attempt vẫn giữ để xem lỗi/lần chạy trước.

Bấm bước có kết quả để mở [Xem giai đoạn](../frontend/src/features/studio/inspection/StageInspectionPage.tsx) tại `/scenes/<jobId>/stages/<stageId>`. Màn này có nội dung xem và panel thông tin đầu ra/artifact. Bước chưa xong chưa được coi là kết quả; QA LiDAR thất bại có thể mở phần chẩn đoán được phép. Màn metric đã hoàn tất dùng để xem kết quả, còn thao tác xác nhận đang chờ thực hiện trong Studio.

### 4.4 Chấp nhận bộ frame đã che

[Panel xem bản đã che](../frontend/src/features/studio/scene/AnonymizationReviewPanel.tsx) cho xem những frame bị che và các vùng mặt/biển số được phát hiện. Người có quyền dùng “Xác nhận và dựng 3D” khi đồng ý bộ frame đó. Nếu còn thông tin cá nhân chưa che, hướng dẫn là hủy job và xử lý lại video.

Bộ phát hiện có thể bỏ sót; số vùng bằng 0 không chứng minh video không có dữ liệu cá nhân. Việc chấp nhận bộ frame, khai báo của uploader và QA privacy được phân biệt trong CONTRACTS.

## 5. Xác nhận tỉ lệ mét

### 5.1 Đo bằng điểm và khoảng cách

Khi đang chờ metric, mở **Studio → Tỉ lệ mét**. [MetricConfirmView](../frontend/src/features/studio/MetricConfirmView.tsx) hướng dẫn chọn A–B trên vật biết kích thước, C–D trên vật khác để kiểm độc lập và ba điểm sàn. Nhập khoảng cách thực theo mét khi dùng chế độ đo tay.

Chọn “Xem trước”, kiểm tỉ lệ, độ cao camera, độ lệch sàn và kết quả C–D rồi mới “Xác nhận tỉ lệ này”. Đổi điểm hoặc số đo làm preview cũ hết hiệu lực; cần kết quả xem trước khớp dữ liệu mới. Điểm lấy từ Gaussian có thể lệch ở vùng mờ, nên không diễn giải sai số chọn điểm thành độ chính xác được bảo đảm.

Đề xuất ước lượng khi có phải giữ nhãn và độ bất định tương ứng; người dùng chọn dùng đề xuất hoặc số đo theo khả năng panel. Xác nhận thành công đưa về Tiến trình để hệ thống dựng tiếp; mở xem 3DGS đơn thuần không xác nhận mét.

### 5.2 Đề xuất từ trajectory LiDAR

Khi proposal có method `lidar_trajectory_alignment`, UI dùng [LidarMetricConfirm](../frontend/src/features/studio/LidarMetricConfirm.tsx). Người dùng xem số frame khớp, độ lệch pose, đường đi camera, tỉ lệ, nguồn trajectory và cảnh báo; không phải chọn lại bảy điểm như nhánh đo tay.

Nút “Xác nhận tỉ lệ từ LiDAR” chỉ bật khi proposal tạo được input/preview hợp lệ và check đạt. Chỉ upload LiDAR chưa bảo đảm nhánh này xuất hiện. Thiếu sàn/đoạn kiểm hoặc dữ liệu không khớp phải xử lý nguyên nhân, không tự xác nhận để bỏ qua điểm chờ.

## 6. Duyệt vật và chỉnh scene

### 6.1 Chọn vật cần tách

[ObjectReviewView](../frontend/src/features/studio/ObjectReviewView.tsx) liên kết viewport, danh sách vật và inspector. Bấm vật hoặc chọn từ danh sách để kiểm tra tên, trạng thái, nguồn và kích thước; có “Bay tới” để tìm vật trong scene.

Trong Draft đang duyệt geometry, người dùng chọn “Tách thành vật để chỉnh sửa” cho vật cần độc lập, hoặc “Giữ trong nền cố định” cho phần muốn giữ ở môi trường. Có thao tác giữ các vật chưa chọn làm nền hoặc đánh dấu nhiều vật rồi áp dụng. Các lựa chọn này lưu quyết định; chưa tự bắt đầu geometry build.

[Nút Tạo mesh](../frontend/src/features/studio/GeometryReviewBanner.tsx) ghi rõ số vật đã chọn và bị khóa khi còn candidate chưa xử lý. Duyệt hết các vật còn lại rồi tạo mesh. Trong thời gian Draft chưa có geometry theo vật, các thao tác cần geometry như dịch/xoay, thêm vật, Walk và tạo gói bị khóa theo điều kiện tương ứng.

### 6.2 Sửa vùng tách

“Chỉnh vùng” mở [RegionEditor](../frontend/src/features/studio/region/RegionEditor.tsx) với box ban đầu do server tính. Người dùng sửa box cộng/trừ, xem lại vùng và số Gaussian được chọn. Các góc Trên/Trước/Bên giúp kiểm hình; preview cho biết vật chồng lấn và những phần bị bảo vệ.

“Lấy luôn” một vùng của vật khác là lựa chọn có tác động tới owner đó, cần đọc tên và số lượng trước khi áp dụng. Nút Apply chỉ bật khi box hợp lệ, preview khớp và không còn blocker. Đổi box phải đợi preview mới; Hủy/đóng preview chưa ghi SceneIR.

Apply trên Draft có thể trả revision mới ngay. Trên Ready, thao tác có thể được nhận thành yêu cầu dựng lại; nhận yêu cầu chưa phải geometry mới đã xong. Nếu revision hoặc membership đã đổi, panel báo xung đột và cho tải lại; không ghi đè phiên bản server bằng preview cũ.

Gộp ứng viên, reassign bằng ROI và Brush/Lasso Gaussian có gate riêng theo scene/runtime. Trong Draft dùng Chỉnh vùng; không mô tả mọi công cụ correction đều dùng được với mọi loại scene. Chi tiết ràng buộc nguồn nằm trong CONTRACTS.

### 6.3 Chỉnh vật đã có geometry

Khi scene sẵn sàng, UI có các thao tác dịch/xoay bằng gizmo, đổi tên/nhãn, khối lượng theo nhãn, nhân bản, thêm primitive/asset, đặt vật bằng chuột và xóa/khôi phục theo dữ liệu hỗ trợ. Đặt vật có hộp xem trước trên sàn; bấm để đặt hoặc Esc để hủy. Không có công cụ scale toàn vật được mặc định từ wireframe cũ.

Inspector có collider riêng. Sửa kích thước/offset/góc xoay trong form là bản xem trước; “Lưu collider” mới gửi thay đổi. Các kiểu collider không hỗ trợ sửa bằng form phải theo giới hạn được hiển thị, không dùng kích thước hộp để giả thành surface mới.

Thao tác ghi thành công trả revision mới và trạng thái lưu. Không có một nút “Lưu nháp” tổng quát bắt buộc sau mọi chỉnh sửa vật. Khi nhận 409, trang báo “Scene đã đổi ở lượt khác”, tải bản mới và yêu cầu thao tác lại; không nhận revision cũ là đã lưu.

### 6.4 Ẩn trên màn hình, tắt mô phỏng và xóa

| Thao tác | Ý nghĩa |
| --- | --- |
| Ẩn/Hiện trên màn hình | Chỉ đổi visibility viewport; không ghi SceneIR |
| Tắt/Bật trong mô phỏng | Đổi `active` của vật confirmed qua server; tạo thay đổi scene |
| Giữ trong nền cố định / Loại | Quyết định cách xử lý vật đề xuất; không đồng nghĩa xóa quan sát nguồn |
| Xóa vật | Gửi thay đổi scene sau xác nhận; khác ẩn layer |
| Khôi phục | Phụ thuộc vật đang bị ẩn, tắt, loại, xóa hay gộp; vật gộp có giải thích khôi phục nhóm |

Nút lọc/nhóm lưu trữ giúp tìm lại vật đã loại, xóa, gộp hoặc ẩn. Không dùng việc vật biến mất khỏi viewport để kết luận nó đã bị loại khỏi collision hoặc candidate.

## 7. Xem 3D, lớp hiển thị và Walk

### 7.1 Cách hiểu các lớp

[MetricSceneView](../frontend/src/features/studio/MetricSceneView.tsx) cung cấp bản Gaussian, collision và khung vật theo dữ liệu được truyền vào. Draft còn có shell xem trước. Shell, surface và collider có mục đích khác nhau; chọn một vật hoặc thấy viền sáng không chứng minh đã có collider cuối.

“Khung vật thể” có thể dùng hình collider khi sẵn có hoặc kích thước hộp của vật. Collision xem trong Studio và Walk phải theo revision hiện hành. Màn Xem giai đoạn có thể cố ý cho xem kết quả tái dựng gốc; nó không phải bản bố trí mới nhất sau các chỉnh sửa.

### 7.2 Điều hướng camera và Walk

Viewer có điều khiển camera, toàn cảnh, về vị trí ban đầu và các lớp hiển thị phù hợp. Chọn điểm đo, chọn vật, chỉnh vùng và đặt vật là những chế độ khác nhau; đọc hướng dẫn công cụ đang bật trước khi bấm trong viewport.

Walk chỉ dùng khi geometry và collision cần thiết sẵn sàng. Lần mở có thể cần tải collision/physics; UI báo đang chuẩn bị hoặc lý do không dùng được. Vật lý và việc đẩy vật trong browser là trải nghiệm kiểm tra cục bộ, không thay validation Isaac hoặc chứng minh robot ngoài đời đi an toàn.

### 7.3 Khả năng trình duyệt và Gaussian editor

[Renderer hiện tại](../frontend/src/features/viewer/renderer-setting.ts) mặc định WebGL; viewer thông thường cần WebGL2 phù hợp. Tùy chọn WebGPU là cấu hình thử nghiệm, không phải yêu cầu bật cờ trình duyệt để xem scene bình thường. Lỗi tải file và lỗi renderer cần được phân biệt theo thông báo; không hứa có video/ảnh thay thế nếu chưa có artifact đó.

[`GAUSSIAN_EDIT_ENABLED`](../frontend/src/features/studio/scene/state.ts) hiện là `false`. Đường xem thông thường và scene import dùng viewer; không hướng dẫn người dùng mở “Chỉnh Gaussian → File → Export” như chức năng đang bật. Code editor/navigation guard còn tồn tại cho cấu hình có editor, nhưng export Gaussian cục bộ vẫn khác lưu SceneObject revision và khác release được duyệt.

## 8. Kiểm tra, căn chỉnh và quyết định duyệt

### 8.1 Tạo gói mô phỏng

Mở [Kiểm tra & duyệt](../frontend/src/features/studio/scene/ReviewTab.tsx), kiểm revision rồi dùng “Tạo gói mô phỏng”. [Panel gói](../frontend/src/features/studio/SimulationPackagePanel.tsx) hiển thị preflight, khả năng xuất USD, blocker, vật bị ảnh hưởng và hướng khắc phục.

Khi preflight hoặc export bị chặn, sửa nguyên nhân rồi thử lại. Thành công có thể tạo revision đã bổ sung physics; các panel phải đọc lại revision đó. “Có gói tải được” chỉ xác nhận candidate đã được tạo, chưa xác nhận Isaac chạy hoặc Reviewer đã duyệt.

### 8.2 Căn chỉnh map LiDAR khi áp dụng

[Panel registration](../frontend/src/features/studio/scene/RegistrationPanel.tsx) cho chuẩn bị request, kiểm dữ liệu và chạy đề xuất căn chỉnh map LiDAR với scene RGB. Nó có trạng thái chờ/chạy, hủy, proposal, QA và overlay để xem các phương án.

Xác nhận chỉ dùng phương án được QA chọn, QA pass, không đổi scale và scene còn đúng revision; phương án đang xem phải là phương án được xác nhận. Kết quả căn chỉnh/bundle được công bố riêng. Thao tác này không tự thay SceneIR hoặc collision mesh; chọn nguồn collision là thao tác khác trong Studio.

### 8.3 Chạy và chọn validation

[Lịch sử Isaac validation](../frontend/src/features/studio/ValidationRunsPanel.tsx) có “Chạy validation” khi candidate hợp lệ đã có và người dùng có quyền. Mỗi run hiển thị lần chạy, trạng thái, candidate, lỗi và các file report/runtime/log khi hoàn tất.

Các thao tác gồm hủy run đang hoạt động, thử lại lỗi được phép và “Dùng report này cho review” cho run hoàn tất của candidate hiện tại. Run cũ được gắn nhãn “Candidate cũ”; run được chọn có nhãn “Đang được dùng”. Hoàn tất một run chưa đồng nghĩa report đã pass hoặc đã được dùng để duyệt.

[Báo cáo validation](../frontend/src/features/studio/ValidationReportCard.tsx) tách check, Start–Goal, collision coverage và nguồn kết quả. Cảnh báo thiếu bằng chứng worker/runtime Isaac phải được giữ rõ. Metrics hoặc giá trị không đủ reference không được biến thành 0 hay nhận là nghiệm thu; phương pháp đánh giá thuộc tài liệu EVALUATION trong kế hoạch chuẩn hóa.

### 8.4 Reviewer phê duyệt hoặc yêu cầu sửa

[ReviewPanel](../frontend/src/features/studio/ReviewPanel.tsx) chỉ mở quyết định khi backend cho biết đúng revision/candidate đủ điều kiện. Người chưa có phiên Reviewer được xem thông tin theo quyền, không được duyệt bằng chế độ local thay cho tài khoản.

Reviewer đọc blocker và bằng chứng, đánh dấu chấp nhận từng warning hiện hành, chọn “Phê duyệt để phát hành” rồi xác nhận đúng gói. “Yêu cầu sửa” cần lý do; sau đó người làm sửa scene, tạo candidate và kiểm lại. Chỉnh scene không phải một cách thay kết quả của report cũ.

Approval đã ghi có thể còn chờ seal release. Nếu phát hành lỗi, panel giữ thông tin đã duyệt và cho Reviewer “Thử lại phát hành”; không yêu cầu tạo quyết định giả hoặc chạy lại reconstruction để tải file. Chỉ trạng thái release hợp lệ mới mở bản phát hành tương ứng.

## 9. Chọn đúng loại kết quả tải về

[Kết quả](../frontend/src/features/studio/scene/ResultsTab.tsx) có ba thẻ với mục đích riêng:

| Loại | Khi nào dùng | Giới hạn |
| --- | --- | --- |
| Bản làm việc 3DGS | Tải preview SOG để xem bằng công cụ khác | Bản preview chưa quy đổi mét/chưa duyệt; không phải scene mô phỏng đã release |
| Gói mô phỏng (candidate) | Tải gói OpenUSD của revision hiện tại | Đọc trạng thái preflight; chưa phải bản phát hành |
| Bản phát hành | Tải gói đã validation, Reviewer duyệt và seal thành công | Phải khớp revision hiện tại và có archive/manifest hợp lệ |

Scene đã đổi revision thì thẻ gói/duyệt cũ nói rõ kết quả không còn áp dụng. Lỗi mạng khi đọc gói hiện thành “Chưa đọc được”, có đường thử lại; không đổi thành “Chưa có gói”. Mở “Nguồn kết quả” để đối chiếu revision, candidate và report/manifest khi cần truy vết.

## 10. File import và mẫu công khai

### 10.1 Scene 3DGS nhập sẵn

Tạo import từ form chung hoặc lối `/new/import-scene`, rồi theo dõi tại `/imports/<importId>`. [ImportScenePage](../frontend/src/features/studio/ImportScenePage.tsx) hiển thị đang chờ worker/tài nguyên, chuẩn bị bản xem, lỗi hoặc hoàn tất. PLY được chuyển sang SOG; SOG hợp lệ giữ nguyên bytes. Đây không phải reconstruction job từ video.

Import đang hoạt động có thể hủy theo capability; lỗi có lịch sử và nút thử lại khi được phép. Khi READY, workspace cho xem 3DGS và các điều khiển camera/bookmark phù hợp. UI hiện chưa có continuation sang xác nhận mét, object geometry, validation hoặc release từ import; ZIP có COLMAP không tự mở các bước đó.

### 10.2 Xem tiến trình mẫu và mở phiên tương tác

[/new/try-demo](../frontend/src/features/studio/NewSceneFlow.tsx) có ba bước: Chọn mẫu, Xem thông tin, Xem tiến trình. [SampleFlow](../frontend/src/features/studio/SampleFlow.tsx) dùng dữ liệu và tiến trình đã ghi; có thể mở kết quả mà không đợi replay. Replay không tạo job GPU mới và thời gian phát lại không phải thời gian xử lý vừa đo.

Mở `/samples/<sampleId>/scene` tạo [phiên demo riêng](../frontend/src/features/studio/SampleScene.tsx). Banner nói rõ thay đổi chỉ có trong phiên; “Khôi phục mẫu” tạo lại trạng thái mẫu. Khi phiên hết hạn có hướng mở lại. Nếu không mở được workspace mà file mẫu còn đọc được, UI cho chọn chỉ xem file 3DGS.

Phiên demo không phải resource lâu dài của tài khoản Guest và không ghi đè mẫu công khai. Bản xem fallback cũng không được gọi là phiên chỉnh sửa hoặc bằng chứng đã chạy pipeline mới.

### 10.3 Trạng thái lưu và thư viện mẫu

[DemoControls](../frontend/src/features/studio/scene/DemoControls.tsx) tách “Lưu trạng thái”, “Quay lại trạng thái đã lưu” và “Về bản gốc”. Lưu/bỏ mốc dành cho Reviewer hoặc chế độ local được phép; khôi phục vẫn chịu quyền thao tác scene. Lưu trạng thái là mốc để khôi phục, khác lưu từng thao tác scene và khác release. Khôi phục có xác nhận và nhận revision mới; về bản gốc vẫn giữ mốc đã lưu.

“Đặt làm bản demo” xuất vào thư viện công khai cần phiên Reviewer và dữ liệu được server chấp nhận. “Bỏ khỏi demo” chỉ gỡ khỏi thư viện, giữ project và dữ liệu scene. Không gọi hai thao tác này là approve/release package.

## 11. Benchmark và thùng rác

### 11.1 Benchmark trong scene và bảng tổng hợp

[Panel Benchmark](../frontend/src/features/studio/value/BenchmarkPanel.tsx) thuộc ngữ cảnh scene, dùng quyền sửa job để quyết định có được ghi thông tin tham chiếu hay chỉ xem. Nó phục vụ nhập dữ liệu đánh giá và lựa chọn đưa scene vào benchmark; không thay thông tin nguồn reconstruction.

[/benchmark](../frontend/src/features/studio/value/BenchmarkPage.tsx) tổng hợp job mới nhất của từng project được đưa vào benchmark, có lọc nguồn dữ liệu và tải CSV/Markdown. Số chưa đo ghi rõ thiếu; không coi bảng tổng hợp này là tất cả scene đã đạt acceptance hoặc mọi chỉ số đều có reference hợp lệ.

### 11.2 Khôi phục và xóa hẳn

[Thùng rác](../frontend/src/features/studio/trash/TrashPage.tsx) có scene, import và file nguồn đã chuyển vào đó. Capability quyết định khôi phục/xóa hẳn; chọn nhiều chỉ áp dụng các mục được phép. Xóa hẳn có xác nhận. Kết quả từng phần nêu mục đã làm được và mục lỗi, không nhận toàn bộ thành công khi còn mục thất bại.

Thời hạn hiển thị dựa trên dữ liệu server. Chuyển vào thùng rác, xóa hẳn resource và xóa một vật trong SceneIR là ba phạm vi khác nhau.

## 12. Phản hồi, khả năng sử dụng và giới hạn kiểm chứng

### 12.1 Phân biệt tải, rỗng, lỗi và thiếu quyền

Màn tải chờ dữ liệu; màn rỗng nói chưa có dữ liệu hoặc không khớp bộ lọc; màn lỗi giữ thông báo và hành động thử lại phù hợp. Thiếu quyền hoặc hết phiên có đường đăng nhập/trở lại. Không bịa kết quả mẫu để lấp panel, cũng không yêu cầu chạy lại pipeline chỉ vì request tải report thất bại.

Khi thao tác đang gửi, nút liên quan bị khóa để tránh gửi lặp. Thành công chỉ hiện khi nhận kết quả tương ứng. Đã nhận yêu cầu, đã lưu revision, run hoàn tất, validation pass, đã duyệt và đã phát hành là các kết quả khác nhau.

### 12.2 Trạng thái cục bộ và việc rời trang

Camera, lựa chọn layer và ẩn viewport chủ yếu thuộc phiên xem. Các form có nút Áp dụng/Lưu giữ nháp cho đến khi gửi. Revision scene đã được server xác nhận vẫn tồn tại khi rời trang; không hứa undo chung cho mọi thao tác.

[NavigationGuard](../frontend/src/features/shell/NavigationGuard.tsx) có cơ chế hỏi khi rời phiên Gaussian editor có thay đổi hoặc chưa đọc được trạng thái. Cờ editor hiện tắt; không suy rộng dialog đó thành bảo vệ mọi form, mọi upload hoặc mọi thay đổi chưa lưu trên ứng dụng.

### 12.3 Màn hẹp, bàn phím và kiểm chứng thực tế

Frontend có label/aria cho nhiều nút icon, trạng thái tải, tab và dialog; các panel có bố cục thu gọn theo màn hình. Trạng thái cần đọc bằng chữ và thông báo cạnh thao tác, không chỉ dựa vào màu. Thao tác 3D phức tạp vẫn ưu tiên máy tính với chuột/bàn phím; không cam kết editor cảm ứng đầy đủ.

Source và component tests cho biết logic dự kiến của control. Chúng chưa chứng minh chất lượng render, độ tương phản, thứ tự focus toàn ứng dụng, thao tác cảm ứng hoặc hiệu năng scene thật. Khi nghiệm thu UX cần ghi rõ browser/thiết bị, dữ liệu scene, role và luồng đã chạy; chỉ gọi một chức năng browser-verified khi có bằng chứng tương ứng.
