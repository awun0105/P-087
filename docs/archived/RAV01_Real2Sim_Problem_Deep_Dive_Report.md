# Problem Deep-Dive Report
## RAV-01 — Real2Sim Workspace
### Từ dữ liệu quan sát đến môi trường mô phỏng có kiểm chứng cho AMR

**Đề gốc:** RAV-01 — Real2Sim Studio - Công cụ dựng lại cảnh đường/kho (warehouse) từ video RGB & LiDAR thành scene mô phỏng chỉnh sửa được.  
**Phạm vi đề xuất:** Một khu vực trong nhà tĩnh, một tầng; tái tạo hình ảnh 3D, tách một số vật thể, dựng hình học va chạm đơn giản, chỉnh sửa, kiểm định và xuất gói scene cho Isaac Sim.  
**Persona chính:** Robotics Simulation Engineer / AMR Integration Engineer.  
**Quy mô thực hiện:** 4 thành viên, 6 tuần; không phát triển robot hoặc mô hình nền tảng từ đầu.  
**Phiên bản report:** 1.0 — 16/09/2026.  
**Quyết định đề xuất:** GO cho khảo sát và thử nghiệm khả thi; chỉ chuyển sang pilot khi vượt các điều kiện đầu vào. NOT YET cho sử dụng vận hành thực tế.

**Quy ước bằng chứng:** [F1]–[F5] là các file đề tài, worksheet và report mẫu. [W1]–[W17] là nguồn kỹ thuật công khai trong phần Research. Các persona chi tiết, cấu hình MVP, số lượng mẫu và ngưỡng nghiệm thu trong report là **đề xuất/giả thuyết thiết kế**, không phải kết quả đã đo hoặc yêu cầu nguyên văn của BTC. Toàn bộ nội dung riêng của RAV-01 trong ngân hàng đề được giữ ở Phụ lục A.

## 1. Executive Summary

RAV-01 nêu vấn đề kỹ sư AV/robotics cần nhiều cảnh mô phỏng, nhưng dựng cảnh thủ công tốn công và dữ liệu quay thật khó chỉnh sửa để tạo tình huống mới. Đề cho phép đường hoặc kho, 3D Gaussian Splatting/NeRF, đầu vào video RGB và/hoặc LiDAR, cùng các mức đầu ra cơ bản và nâng cao khác nhau. [F1]

Report đề xuất thu hẹp sang **chuẩn bị scene trong nhà cho kỹ sư triển khai robot di động tự hành — AMR**. Đơn vị công việc cần giải quyết là: từ một bộ dữ liệu khảo sát của khu vực nhỏ đến một gói scene có tỉ lệ, vật thể, collision, lịch sử chỉnh sửa và bằng chứng kiểm tra đủ để kỹ sư đưa vào một bài thử điều hướng giới hạn trong simulator. Không đặt mục tiêu dựng toàn bộ nhà máy, mô phỏng giao thông hoặc chứng nhận an toàn cho robot thật.

Sản phẩm có hai biểu diễn liên kết: **lớp hình ảnh 3DGS** để xem và đối chiếu với quan sát; **lớp hình học/semantics/collision** để chỉnh sửa và chạy kiểm tra trong Isaac Sim. Hai lớp dùng chung hệ tọa độ, mã vật thể và phiên bản, nhưng không đánh đồng Gaussian splat với mesh vật lý. Splatfacto có đường xuất splat; collision và dữ liệu physics trong simulator vẫn cần được tạo, cấu hình và kiểm tra riêng. [W2][W8]

Lựa chọn kỹ thuật là **CV/geometry + rule + stateful workflow + một QA agent giới hạn trong harness + human-in-the-loop**. Chatbot không phải thành phần bắt buộc. Agent chỉ hỗ trợ chọn công cụ chẩn đoán, tìm bằng chứng và đề nghị bước sửa; không được tự sinh hình học chưa quan sát rồi xác nhận là đúng, đổi ngưỡng kiểm định hoặc duyệt scene thay kỹ sư.

**Giá trị phải kiểm chứng:** giảm ít nhất 50% tổng thời gian thao tác của người làm và người duyệt so với quy trình đối chứng đủ mạnh, không đánh đổi độ đúng hình học và không chuyển công việc sang một bước sửa lỗi khác. Chỉ số hình ảnh đẹp hoặc demo robot tới đích không đủ chứng minh mục tiêu đó. Nếu quy trình CAD/occupancy map hiện có đã giải quyết nhu cầu nhanh hơn, hoặc user không cần hình ảnh 3DGS, nhóm phải chấp nhận thu hẹp/pivot thay vì cố giữ mọi thành phần AI.

## 2. Why This Problem Matters — Actor và ngữ cảnh

### 2.1 Persona và trách nhiệm

Các persona dưới đây là **giả thuyết để tuyển người phỏng vấn**, không phải chân dung đã xác nhận từ khách hàng.

| Persona | Công việc và pain dự kiến | Quyền quyết định / lợi ích |
|---|---|---|
| Simulation Engineer — người dùng chính | Chuyển dữ liệu site thành scene; sửa scale, object, collision; kiểm tra import và chạy thử | Xây/sửa scene, đề xuất phát hành; được giảm thao tác chuẩn bị và rework |
| AMR Integration Engineer — người dùng phối hợp | Kiểm tra một bố trí hoặc một lối đi với cấu hình robot cụ thể | Chốt footprint, route và cấu hình kiểm thử; không giao quyền điều khiển robot thật cho công cụ |
| Simulation Reviewer / Tech Lead | Kiểm tra scene có đúng dữ liệu khảo sát, phiên bản và mục đích thử hay không | Duyệt hoặc từ chối release, chấp nhận phạm vi chưa biết; không chỉ bấm duyệt một ảnh đẹp |
| Project/Engineering Manager — người mua tiềm năng | Quản lý thời gian bàn giao môi trường thử và công sức bảo trì nhiều site | Đánh giá mua theo chi phí tiết kiệm được; nhu cầu trả phí phải được kiểm chứng riêng |

### 2.2 Job-to-be-done

> Khi có một khu vực triển khai mới hoặc layout đã thay đổi, tôi cần chuẩn bị nhanh một môi trường thử có tỉ lệ, vật cản và dữ liệu kiểm định rõ ràng, để kiểm tra bố trí/điều hướng của robot mà không phải lắp ráp lại scene và dò lỗi export từ đầu.

**Bối cảnh MVP:** một phòng/khu vực kho thử nhỏ, nền tương đối phẳng, không có người hay xe đang chuyển động trong capture; chỉ làm sàn, tường và một số vật cản tĩnh. “Kho” là phân khúc ứng dụng cần khảo sát; một bộ dữ liệu phòng làm việc không tự chứng minh được nhu cầu của nhà kho thực tế.

### 2.3 Ai không phải khách hàng mục tiêu ban đầu?

Không ưu tiên đội chỉ cần bản đồ occupancy 2D; đội đã có CAD/BIM sạch và quy trình import nhanh; người chỉ muốn một bản quét đẹp để trình diễn; hay doanh nghiệp không có nhu cầu mô phỏng theo site. Với các nhóm đó, neural reconstruction có thể chỉ tăng chi phí. Đây là điều kiện loại trừ để tránh xây sản phẩm “có cũng được”.

### 2.4 Lý do sử dụng lặp lại

Trigger dự kiến gồm site mới, thay bố trí vật cản, bổ sung một bài thử, review phiên bản scene và sửa một lần import/kiểm định thất bại. Cần đo số trigger thực tế mỗi tháng và mỗi dự án: **không giả định kỹ sư sẽ dùng hằng ngày**. Nhu cầu theo dự án có thể phù hợp thu phí theo site hơn thuê bao tháng.

## 2A. Four-Lens Problem Identification

Worksheet yêu cầu nhìn qua bốn lăng kính: lặp lại, tốn thời gian, AI có thể tốt hơn và pain từ người khác. Bốn lăng kính này dùng để tìm vấn đề, không phải bốn feature cần thêm vào sản phẩm. [F2]

### 2A.1 Phân tích bằng bốn lăng kính

| Lens | Vấn đề cần kiểm chứng | Evidence cần lấy |
|---|---|---|
| Lặp lại | Mỗi site/phiên bản layout lại phải chuẩn hóa scale, vật cản, export và chạy kiểm tra | Lịch sử scene, ticket thay layout, số lần import lại; tần suất theo tháng/dự án |
| Tốn thời gian | Người làm phải chuyển qua capture tool, 3D editor, simulator và bảng kiểm; sửa một bên làm lệch bên còn lại | Ghi màn hình/time log từng bước; tách thời gian thao tác, chờ GPU, chờ review |
| AI có thể tốt hơn | Segmentation có thể giảm khoanh vật thể; QA agent có thể nối nhiều log để chọn chẩn đoán phù hợp | So sánh với chọn object thủ công, rule-only QA và cùng pipeline không có agent |
| Pain từ người khác | Người nhận scene khó biết chỗ nào thiếu quan sát, collision nào là ước lượng, bản nào đã duyệt | Phỏng vấn cả người dựng và người nhận; tìm một lần bàn giao bị trả lại và lý do |

**Kết luận hiện tại:** lens 1–3 có giả thuyết kỹ thuật hợp lý; lens 4 chưa có phỏng vấn/ticket của người dùng trong tài liệu đã cung cấp. Không ghi các giả thuyết đó thành trải nghiệm cá nhân hoặc kết quả khảo sát của nhóm.

### 2A.2 Scan các vấn đề trong phạm vi đã chọn

| Mã | Candidate problem | Persona chịu ảnh hưởng | Dấu hiệu cần xác nhận |
|---|---|---|---|
| P1 | Capture thiếu coverage, phát hiện quá muộn sau khi chạy reconstruction | Scene builder | Số lần phải quay lại khảo sát và thời gian compute bỏ phí |
| P2 | Chưa xác lập đúng đơn vị mét, trục và pose giữa công cụ | Simulation engineer | Số lỗi scale/axis; thời gian dò lỗi import |
| P3 | Scene nhìn đẹp nhưng không có collision đúng hoặc thiếu vật cản | AMR engineer | Route xuyên vật cản, raycast thiếu mặt hoặc reviewer trả scene |
| P4 | Tách/đổi một vật thể làm visual và collision không còn khớp | Scene builder, reviewer | Số lỗi sau edit; thời gian cập nhật đồng bộ |
| P5 | Bằng chứng QA phân tán, không biết version nào đáng dùng | Tech Lead | Thời gian review; lỗi dùng nhầm phiên bản |
| P6 | Layout đổi nhỏ nhưng phải chạy/sửa lại quá nhiều phần | Integrator | Thời gian sửa một object, số bước lặp không cần thiết |

Đây là **problem scan phân tích**, không thay bản scan cá nhân từ trải nghiệm thật của từng học viên. Nhóm cần bổ sung evidence trước khi coi P1–P6 là pain đã validate. [F2][F3]

### 2A.3 Top 3 Problem Cards để hội tụ

**Card 1 — Chuẩn bị collision và scale có thể kiểm tra.** Actor là Simulation Engineer; bối cảnh là bàn giao một scene mới; workflow hiện tại dự kiến: nhập capture → căn tỉ lệ → dựng vật cản → cấu hình collision → thử robot → sửa. Bottleneck giả thuyết nằm ở dựng/sửa proxy và dò lỗi import; impact là kéo dài thời gian đến bài thử đầu tiên. Metric là tổng active time đến scene đạt bộ kiểm định, không chỉ thời gian train. Non-AI alternative là CAD/primitive editor + checklist. AI hypothesis là hỗ trợ chọn object và ưu tiên vùng cần review, không quyết định hình học thay người. Hướng sơ bộ: workflow có CV hỗ trợ.

**Card 2 — Edit không làm visual và physics lệch nhau.** Actor là người dựng/reviewer; bối cảnh là chuyển một vật cản trong layout. Current: sửa visual → sửa collider riêng → import lại → kiểm tra; future: một edit theo object ID → cập nhật cả hai biểu diễn → vô hiệu hóa QA cũ → chạy kiểm tra liên quan. Metric là active time mỗi edit và số lỗi không đồng bộ; alternative là editor có group/prefab, chưa chắc cần LLM. Đây là một chức năng bắt buộc của Card 1, không phải sản phẩm độc lập ở MVP.

**Card 3 — Chẩn đoán scene QA thất bại.** Actor là kỹ sư nhận scene; current: đọc log, mở nhiều công cụ rồi thử chỉnh; future: rule đo lỗi → agent gọi công cụ chẩn đoán được phép → trả bằng chứng → người sửa. Metric là time-to-diagnosis và tỷ lệ khuyến nghị đúng trên lỗi cài sẵn. Alternative là bảng kiểm/rule report; chỉ giữ agent khi cho lợi ích thêm so với alternative này.

**Đề xuất hội tụ:** lấy Card 1 làm problem chính, Card 2 là điều kiện đúng đắn, Card 3 là phần agentic hỗ trợ. Đây là đề xuất để nhóm thảo luận, không phải biên bản biểu quyết đã diễn ra. Scope này không mở rộng thành một nền tảng digital twin toàn nhà máy.

## 2B. Persona Painpoint, Mission và Definition of Pain Solved

### 2B.1 Pain cốt lõi

> Kỹ sư không thiếu công cụ vẽ hoặc render; họ có thể thiếu một đường đi ngắn, kiểm tra được và ít sửa lại từ dữ liệu quan sát đến scene phù hợp với bài thử robot cụ thể.

Câu trên là **product hypothesis**, cần đối chiếu với workflow thật. Sản phẩm không tạo giá trị nếu chỉ gom các thư viện phía sau một nút “Generate” mà engineer vẫn phải tự nối mọi bước, làm lại collision và chạy kiểm định bằng tay.

| Pain cụ thể | Cách xử lý trong MVP | Khi nào coi là chưa giải quyết |
|---|---|---|
| Không biết capture đủ dùng chưa | Kiểm file, pose, coverage và điều kiện scale trước job nặng; khoanh vùng thiếu dữ liệu | Vẫn train xong mới biết thiếu ảnh hoặc sai scale |
| Mất công xác định sàn/vật cản | Geometry đề xuất plane/proxy; segmentation có tương tác; hiển thị evidence theo object | Tạo proxy nhanh nhưng reviewer phải dựng lại gần hết |
| Scene không dùng được trong simulator | Xuất hình học/collision rõ; kiểm đơn vị, trục, reference và probe vật lý | Chỉ mở được file USD, robot/raycast vẫn xuyên vật cản |
| Edit làm hai biểu diễn bất nhất | Object ID chung, edit transaction, cùng transform, QA bị vô hiệu hóa khi đổi | Visual đã di chuyển nhưng collider hoặc báo cáo vẫn dùng bản cũ |
| Không tin kết quả QA | Số đo do tool tính; link về frame/mesh/test và người duyệt | Agent tự viết “PASS” hoặc suy diễn vùng chưa quan sát |
| Sửa layout lại phải làm từ đầu | Clone scene version, reuse artifact chưa đổi, chỉ chạy lại bước phụ thuộc | Không tiết kiệm effort ở nhiệm vụ chỉnh sửa lặp lại |

### 2B.2 Sứ mệnh và mục tiêu

**Mission:** Giảm công sức chuẩn bị và kiểm tra môi trường mô phỏng theo site, để kỹ sư dành nhiều thời gian hơn cho thiết kế thí nghiệm, phân tích lỗi và triển khai robot có trách nhiệm.

**Mục tiêu sản phẩm:** từ “tự ráp và dò lỗi qua nhiều công cụ” sang “kiểm tra đề xuất, sửa phần mơ hồ, duyệt artifact có bằng chứng”. Công cụ hỗ trợ chuyên môn, không tự quyết điều kiện an toàn ngoài đời và không lấy giảm biên chế làm KPI.

**Mục tiêu kỹ thuật:** cảnh có visual review được; geometry đủ đúng trong vùng thử; thao tác object có kiểm soát; xuất đúng simulator đã chọn; cùng input và version phải truy lại được artifact và kiểm định đã dùng.

**Mục tiêu kinh tế cần đo:** tiết kiệm effort ròng sau khi tính cả capture, chỉnh sửa, review, retry, đào tạo sử dụng và compute. Một GPU job chạy lâu có thể tiết kiệm thao tác nhưng tăng thời gian bàn giao; phải báo cáo cả hai, không chọn chỉ số có lợi cho demo.

### 2B.3 Definition of pain solved

MVP chỉ được xem là có giá trị khi đạt các gate ở Mục 15 và có người dùng mục tiêu xác nhận workflow thực tế thuận tiện hơn. “Must-have” không phải một lời cam kết; nó là giả thuyết được kiểm tra bằng việc kỹ sư tự chọn dùng công cụ ở nhiệm vụ tiếp theo có cùng nhu cầu.

Nếu người dùng chỉ cần occupancy map/CAD, review tốn ngang làm tay, hoặc quality tăng mà chi phí tăng vượt lợi ích, nhóm phải bỏ tính năng dư hoặc đổi định vị. Không giải thích thất bại bằng việc cần thêm nhiều agent. Quyền xuất dữ liệu, sửa bằng công cụ khác và làm việc khi LLM lỗi phải được giữ, tránh tạo phụ thuộc nhân tạo.

## 3. Current-State Workflow Mapping

### 3.1 Workflow hiện tại — giả thuyết để khảo sát

```text
Nhận bài thử + giới hạn vùng khảo sát
  -> Thu capture / CAD / số đo
  -> Căn pose, scale, hệ trục
  -> Dựng / làm sạch geometry và collision  [nghẽn dự kiến]
  -> Tách object và gắn semantics
  -> Import simulator, kiểm tra, sửa lại  [nghẽn dự kiến]
  -> Reviewer duyệt và lưu phiên bản
```

### 3.2 Actor, input, output và cách đo theo bước

| Bước / actor | Input → output | Handoff | Thời gian / tần suất phải thu |
|---|---|---|---|
| 1. Integrator + reviewer | Mục tiêu thử → vùng, robot, route và tolerance | Người đặt bài → người dựng | Phút làm rõ yêu cầu; mỗi scene mới |
| 2. Người khảo sát | Site hoặc bộ dữ liệu → ảnh, depth/scan, số đo, quyền sử dụng | Người khảo sát → engineer | Active capture + upload; số lần recapture |
| 3. Engineer | Dữ liệu → pose, hệ trục, scale đã kiểm | Chuẩn bị dữ liệu → reconstruction | Phút thao tác, phút compute; lỗi import |
| 4. Engineer | Reconstruction/scan → sàn, tường, object/collider | Geometry → editor | Phút dựng và sửa từng object |
| 5. Engineer | Object → semantics, grouping, phiên bản | Editor → simulator | Phút chỉnh nhãn/transform; số object sửa |
| 6. Engineer | Scene + robot/test suite → lỗi và bằng chứng | Simulator → người sửa | Thời gian chạy, số vòng sửa, test fail |
| 7. Reviewer | Artifact + evidence → duyệt hoặc trả lại | Reviewer → thư viện scene | Phút review, thời gian chờ, số lần trả |

**Bottleneck ưu tiên:** công sức làm cho geometry/collision và các chỉnh sửa thực sự dùng được trong bài thử, không mặc định thời gian chạy 3DGS là bottleneck. Cần xác nhận bằng time log trước khi đầu tư sâu vào neural rendering.

### 3.3 Baseline và phạm vi đo

Hiện chưa có time log hoặc case khách hàng chứng minh bao nhiêu giờ đang bị mất. Baseline phải dùng workflow hiện có của người tham gia, cho phép họ dùng CAD, scan processing và template sẵn có. Không so với một đối chứng cố tình yếu như bắt vẽ lại mọi thứ từ đầu khi thực tế đã có file CAD.

Đo riêng: **active person-minutes** của tất cả người tham gia; **wall-clock time** từ capture được chấp nhận đến release; compute time; thời gian chờ reviewer; số lần sửa; tỷ lệ scene không hoàn thành trong budget. Cả task thất bại cũng nằm trong báo cáo.

## 4. Problem Statement v0 — 6 Fields

| Field | Nội dung |
|---|---|
| Actor / Operator | Simulation Engineer ở đội tích hợp AMR; reviewer chịu trách nhiệm phê duyệt mục đích dùng scene |
| Current Workflow | Thu capture → căn pose/scale → dựng visual và collision → gắn semantics → import/test → sửa → duyệt |
| Bottleneck | Chuyển dữ liệu quan sát thành hình học và collision có thể kiểm tra; sửa nhiều biểu diễn và dò lỗi bàn giao |
| Business Impact | Lead time chuẩn bị bài thử kéo dài, rework và chi phí review tăng; mức tác động thực tế chưa được đo |
| Success Metric | Mục tiêu pilot: giảm ≥50% active person-minutes so với đối chứng; chất lượng/kiểm định không kém tiêu chuẩn chốt trước; báo cáo cả wall-clock và chi phí |
| Operational Boundary | Một khu vực indoor tĩnh; một AMR mẫu trong simulator; không robot thật, không kết luận safety, không tự bịa geometry hoặc tự approve |

**Problem statement một câu:** Kỹ sư chuẩn bị mô phỏng AMR cần chuyển capture của một khu vực trong nhà thành scene có tỉ lệ, vật cản và kiểm định rõ ràng với ít công sức sửa lại hơn, để bắt đầu bài thử phù hợp mà vẫn giữ quyền đánh giá chuyên môn và phê duyệt scene.

Đây là v0 trước validation. V1 tại Mục 7.4 bổ sung điểm can thiệp AI, loại workflow và người kiểm soát rủi ro; không giả vờ đã có vòng phỏng vấn làm thay đổi problem.

## 5. Quick Validation Plan

### 5.1 Evidence hiện có và khoảng trống

| Nhóm evidence | Trạng thái hiện tại | Có thể kết luận đến đâu? |
|---|---|---|
| Ngân hàng đề RAV-01 | Có problem và yêu cầu đầu ra [F1] | Căn cứ lựa chọn đề, không phải bằng chứng khách hàng sẽ trả tiền |
| Tài liệu công cụ/dataset | Có nguồn chính thức [W1]–[W17] | Biết thành phần tồn tại; chưa chứng minh tổ hợp của nhóm chạy được |
| Interview/time log | Chưa có trong tài liệu đầu vào | Chưa xác nhận persona pain, tần suất, baseline hoặc mức sẵn lòng trả phí |
| Prototype/benchmark RAV-01 | Chưa thực hiện trong report này | Không có số PSNR, Chamfer, thời gian hoặc tỷ lệ pass thực nghiệm để công bố |

### 5.2 Người cần gặp và câu hỏi

Mục tiêu tuyển 3–5 người từng chuẩn bị scene cho robot, trong đó cố gắng có ít nhất một người review/nhận bàn giao. Nhờ mentor/CLB robotics/đơn vị integrator tiếp cận được một workflow gần đây. Khảo sát này là định tính ban đầu, không đại diện toàn thị trường.

Các câu hỏi trọng tâm: Lần cuối anh/chị tạo/cập nhật scene là khi nào? Đầu vào thực tế là CAD, video hay LiDAR? Bước nào phải làm lại nhiều nhất? Bài thử có cần visual 3DGS hay chỉ hình học/occupancy? Ai duyệt collision/scale? Công cụ đang dùng đã giải quyết được phần nào? Một scene bị trả lại vì lý do gì? Tần suất đổi layout và ngân sách công cụ hiện có là bao nhiêu?

Yêu cầu người tham gia chỉ ra thao tác thật hoặc artifact đã ẩn danh; không chỉ hỏi “anh/chị có dùng app AI này không?”. Không yêu cầu họ chia sẻ sơ đồ site, log hoặc hình ảnh nội bộ chưa được cho phép.

### 5.3 Gate trước khi triển khai rộng

Chỉ tiếp tục product pilot khi có ít nhất hai workflow người dùng cụ thể để đối chiếu, một reviewer đồng ý kiểm bộ acceptance, và dữ liệu được phép sử dụng. Nếu chưa tìm được người, nhóm vẫn có thể làm technical feasibility study nhưng phải ghi rõ chưa chứng minh problem/product fit.

Trong tuần 1, đồng thời kiểm tra GPU chạy được simulator và xuất một scene proxy tối giản. Không đợi tuần 5 mới phát hiện máy không chạy được Isaac Sim. Nếu hết tuần 1 vẫn thiếu GPU phù hợp hoặc không có dữ liệu metric, giảm mục tiêu sang technical prototype hoặc xin BTC duyệt thay đổi phạm vi; không gọi một viewer đơn thuần là ứng dụng simulation-ready.

## 6. Research — Existing Solutions và phạm vi sản phẩm

### 6.1 Những gì công cụ hiện có đã giải quyết

Đây là phần research bổ sung, tách khỏi mô tả đề gốc. Các nguồn được kiểm tra ngày 16/09/2026; capability công bố không được coi là hiệu quả đã benchmark bởi nhóm.

| Công cụ / hướng | Capability có nguồn | Bài học và giới hạn cho đề tài |
|---|---|---|
| COLMAP | Pipeline SfM và MVS phục vụ tái tạo ảnh, pose và hình học [W3] | Tận dụng công cụ có sẵn; không tuyên bố nhóm tự phát minh camera reconstruction |
| Nerfstudio Splatfacto / 3DGS | Huấn luyện biểu diễn Gaussian và xuất splat để render [W1][W2] | Một splat export không tự trở thành collider; viewer đẹp không phải kết thúc workflow |
| Open3D RGB-D integration | Tích hợp depth vào TSDF và trích mesh [W4] | Có đường hình học độc lập cho collision/reference; chất lượng phụ thuộc depth và pose |
| NVIDIA Omniverse NuRec | Neural reconstruction và rendering gắn với OpenUSD, Isaac Sim và các simulator khác [W6] | Không claim “lần đầu biến capture thành simulation”; tích hợp NuRec cũng cần kiểm định compatibility, tài nguyên và quyền sử dụng |
| Isaac Sim + công cụ dựng scene sẵn có | Scene có physics, robot, sensor và bài thực hành Nav2 [W7][W8][W9] | Phải so với workflow hiện hữu; không chứng minh giá trị chỉ bằng việc thêm web UI |

**Khoảng giá trị cần kiểm chứng:** chuẩn hóa capture → object → collision → edit → QA → release cho một nhóm kỹ sư cụ thể, làm rõ vùng không chắc chắn và giảm tổng công sức. Chưa có evidence rằng đối thủ không làm được chuỗi này; đây là giả thuyết định vị, không phải kết luận thị trường còn trống.

### 6.2 Vì sao chọn Isaac Sim thay vì CARLA trong report này?

Đây là lựa chọn theo scope, không phải đánh giá simulator nào tốt hơn tuyệt đối. CARLA đặt trọng tâm autonomous driving; Isaac Sim có workflow robotics, robot/sensor assets và Nav2 phù hợp hướng indoor AMR. [W7][W9][W16]

RAV-01 gốc cho phép cả hai. Report chọn **một target Isaac Sim** để tránh cùng lúc xử lý road network, OpenDRIVE, traffic actors và workspace robot. Nếu nhóm chuyển về cảnh đường/AV, phải lập lại persona, dataset và acceptance; không chỉ thay một dòng cấu hình simulator.

### 6.3 Scope thu hẹp và thay đổi so với tầm nhìn rộng

| Thành phần | MVP 6 tuần | Hoãn / không cam kết |
|---|---|---|
| Môi trường | Một vùng indoor tĩnh, một tầng; sàn, tường, vài vật cản | Toàn kho/nhà máy, giao thông, người/xe động, outdoor lớn |
| Capture | Chuỗi RGB có intrinsics, pose được cung cấp hoặc chuẩn bị; depth/scan hoặc số đo để xác lập hình học metric | Video điện thoại bất kỳ tự có scale chính xác; input thiếu coverage vẫn dựng đúng |
| Reconstruction | Một backend 3DGS có sẵn; geometry đi đường depth/point cloud đã kiểm | Tự huấn luyện world model; nhiều backend NeRF/GS đồng thời |
| Chỉnh sửa | Chọn, bật/tắt, sửa nhãn; dịch chuyển vật cản đã tách và đồng bộ collider | Xóa object rồi tạo hoàn hảo phần nền chưa từng nhìn thấy; relighting/weather vật lý |
| Export | Mesh/proxy, semantics, collider và manifest cho Isaac Sim; splat đi kèm trong gói | Mọi simulator tự đọc trực tiếp mọi định dạng splat; full RAV-23 replay |
| Robot test | Một robot mẫu, cấu hình cố định, route và collision probes giới hạn | Huấn luyện policy, chứng nhận an toàn, sim-to-real hoặc deploy robot thật |

**Điều chỉnh triển khai cần nói rõ:** hướng RGB-only được thảo luận trước đó thuận tiện cho người dùng, nhưng không bảo đảm metric scale và collision geometry. MVP ưu tiên capture có pose/depth hoặc tham chiếu đo được; RGB-only + COLMAP/MVS là mở rộng có điều kiện, không xây hai pipeline độc lập trong 6 tuần. Đây là lựa chọn triển khai của nhóm, không phải yêu cầu mới của đề gốc. [W3][W4][W17]

Việc dùng RGB-D/indoor public data thay danh sách dataset đường phố gợi ý cần được ghi trong scope nộp BTC/mentor. Những phần nâng cao hoãn lại vẫn giữ trong bảng đối chiếu ở Mục 18, không âm thầm coi đã hoàn thành.

## 7. Rule vs Workflow vs Agent — AI Fit

### 7.1 Phân tách đúng loại công việc

**Computer Vision không đồng nghĩa với LLM.** 3DGS là lõi tái tạo hình ảnh; segmentation hỗ trợ tách vùng; geometry và các kiểm tra số học làm bằng thuật toán. LLM không tính tọa độ từ trí nhớ, không tự viết ra metric và không quyết định collider có an toàn hay không.

| Hướng | Khi nào đủ? | Rủi ro | Quyết định |
|---|---|---|---|
| No AI / CAD + template | Có CAD sạch, layout đơn giản, chỉ cần occupancy và proxy | Vẫn có thao tác dựng; nhưng có thể đã nhanh nhất | Là đối chứng và phương án thay thế hợp lệ |
| Rule + geometry | Input rõ, chuẩn đơn vị, plane fitting, check reference, probe cố định | Không hiểu mọi lỗi dữ liệu phức hợp | Bắt buộc cho phép đo và policy |
| Stateful workflow + CV | Chuỗi ingest, reconstruct, segment, export, test đã biết | Retry cứng có thể tốn compute khi thiếu thông tin | Là backbone MVP |
| Bounded QA agent | QA fail có nhiều giả thuyết; cần chọn công cụ và evidence tiếp theo | Hallucination, chạy vòng lặp, đề nghị sửa sai | Chỉ dùng trong một vùng chẩn đoán, có budget và HITL |
| Autonomous agent toàn quy trình | Tự thay dữ liệu, tự duyệt, tự kiểm robot thật | Quyền quá rộng; thiếu bằng chứng | Không chọn |

### 7.2 Có cần chat UI không?

**Không.** UI chính là trình xem scene, danh sách object, overlay collision, bảng metric, lịch sử chỉnh sửa và màn hình duyệt. Người dùng có thể bấm “Phân tích lỗi QA” để agent chạy; đầu ra là issue có evidence và hành động đề xuất. Một ô nhập mô tả bài thử là tùy chọn, không phải lý do sản phẩm tồn tại.

### 7.3 Quyết định kiến trúc

Chọn **CV/geometry + deterministic rules + stateful agentic workflow + agent harness + bounded QA agent + HITL**. Harness là lớp quản lý quyền, state, jobs, ngân sách và phê duyệt; không phải một phương pháp AI cạnh tranh với rule hay agent.

MVP chỉ cần một agent chẩn đoán. Nếu tách hai agent sau này, nên là Capture/Reconstruction QA và Simulation QA có tool/context riêng; chưa có lý do để tạo một nhóm agent chỉ nhằm đủ tên gọi multi-agent. PLO2 trong ngân hàng đề áp dụng khi bài toán cần nhiều agent phối hợp. [F1]

### 7.4 Problem Statement v1

| Field | Nội dung đã làm rõ |
|---|---|
| Actor | Simulation Engineer là operator; integrator chốt bài thử; reviewer duyệt release |
| Workflow | Capture có quyền sử dụng → pose/scale → visual + geometry → object edit → QA/probes → reviewer → gói simulator |
| Bottleneck | Effort biến quan sát thành geometry/collision đúng và effort sửa nhiều biểu diễn không đồng bộ |
| Impact | Thời gian chuẩn bị và review, số vòng rework, thời gian cập nhật layout; chưa có baseline thật |
| Success Metric | Giảm ≥50% active person-minutes; không tăng lỗi geometry quan trọng; đạt gate visual, export, edit và kiểm định giới hạn |
| Boundary | Một indoor region tĩnh; chỉ simulation; dữ liệu không đủ phải báo thiếu; không tự mở rộng vùng được xác nhận |
| AI intervention point | 3DGS/segmentation trong reconstruction; LLM chỉ ở chẩn đoán QA từ tool evidence và tri thức được phép |
| Mức chọn | Workflow có CV, rule và bounded agent trong harness; không cần chat |
| Rủi ro & người kiểm tra | Sai scale, bỏ collider, sửa không đồng bộ, hallucination; engineer sửa, reviewer xác nhận và mọi edit sau đó hủy hiệu lực approval cũ |

**Điều thay đổi từ v0:** làm rõ input metric, hai biểu diễn, điểm can thiệp của agent và phạm vi kiểm định. Đây là tiến triển trong lập luận thiết kế; chưa phải thay đổi được xác nhận qua user validation.

## 8. Future-State Workflow

```text
[1] Khai báo bài thử, vùng quan sát, input và quyền dữ liệu
  -> [2] Rule kiểm file, intrinsics, pose, scale và coverage
       không đủ -> NEEDS_INPUT / yêu cầu đo hoặc capture bổ sung
  -> [3] Tạo visual 3DGS + geometry metric trong cùng hệ tọa độ
  -> [4] Tách object, đề xuất proxy; engineer sửa/duyệt geometry
  -> [5] Edit scene theo object ID; cập nhật visual + collision
  -> [6] Tool đo chất lượng, export và chạy simulator probes
       fail -> QA agent chọn phép kiểm -> đề nghị sửa có evidence
               hết budget / thiếu bằng chứng -> human fallback
  -> [7] Reviewer duyệt đúng version -> export release package

Layout thay đổi -> clone version -> edit -> QA lại -> duyệt lại
```

### 8.1 Handoff và kiểm soát

| Handoff | Payload cần có | Kiểm soát |
|---|---|---|
| Capture → pipeline | Artifact hash, calibration, pose, scale source, quyền sử dụng | File validation; không truyền dữ liệu nhạy cảm sang LLM |
| Reconstruction → editor | Splat, geometry, object candidates, unknown regions | Cùng tọa độ; không che giấu vùng thiếu quan sát |
| Editor → simulation | Scene version, mesh/proxy, collider, route config | Export validator; không dùng artifact lệch version |
| QA tools → agent | Metric, lỗi, evidence URI, allowlisted tool names | Agent không sửa metric/GT; dữ liệu được coi là input không đáng tin |
| Agent → engineer | Issue, giả thuyết, kiểm tra tiếp theo, chi phí dự kiến | Không đồng nhất giả thuyết với root cause đã xác nhận |
| Reviewer → release | Reviewer ID, thời điểm, artifact/test/config hashes | Release bất biến; thay scene/config phải QA và duyệt lại |

### 8.2 Trạng thái thất bại cũng là đầu ra hợp lệ

Nếu scale chưa xác lập hoặc nền phía sau vật thể chưa từng được quan sát, hệ thống trả `NEEDS_INPUT` hoặc `BLOCKED`, kèm vị trí và lý do. Không “hoàn thành bằng mọi giá”. Scene nháp/checkpoint được lưu để phục hồi; chỉ phiên bản đã được reviewer duyệt mới được xuất dưới nhãn release. Cách phân biệt draft/release này triển khai yêu cầu HITL của đề gốc mà không làm mất dữ liệu khi job lỗi. [F1]

## 9. Proposed Product Architecture

### 9.1 Hai biểu diễn, một scene graph

```text
Web workspace: capture | splat viewer | object editor | QA | review
                            |
FastAPI control plane: auth, state, manifest, jobs, audit, releases
                            |
Stateful workflow + bounded QA agent + policy / budget harness
          |                 |                       |
   CV / GPU workers    Geometry workers       Simulator worker
   3DGS, SAM2          TSDF, planes, OBB       USD, probes, Nav2
          |                 |                       |
   Visual splats <---- shared object IDs / transforms ----> Physics
                            |
Object store + PostgreSQL + experiment metrics / evidence registry
```

Lõi ứng dụng nên là modular monolith; worker GPU/simulator là tiến trình hoặc container riêng vì phụ thuộc và tài nguyên khác nhau, không phải cớ chia thành nhiều microservice. Job nặng không chạy trong HTTP request. Web chỉ gửi cấu hình đã kiểm tra và theo dõi trạng thái.

### 9.2 Representation contract

`visual/splats.ply` phục vụ review hình ảnh. `geometry/mesh` hoặc proxy phục vụ export/kiểm định. `scene_graph.json` nối object ID với cả hai, chứa transform, class do người kiểm, provenance và coverage. `physics/scene.usda` mô tả geometry/collision target simulator. `qa/` giữ metric, probe result và phạm vi áp dụng.

**Không mặc định một file USD chứa mọi Gaussian là render được ở mọi viewer.** Nerfstudio splat và NuRec neural volume là các đường tích hợp khác nhau. MVP có thể xuất mesh/proxy tiêu chuẩn sang Isaac Sim, giữ splat trong web viewer; nhánh render Gaussian trực tiếp trong simulator chỉ làm khi adapter đã được smoke-test. [W2][W6]

Nếu camera mô phỏng chỉ nhìn mesh/proxy, phải khai báo `sensor_visual_mode=proxy_or_mesh`; không nói camera đang kiểm thử photorealistic 3DGS. Bài navigation/probe MVP đánh giá hình học và workflow, không đánh giá chất lượng perception thị giác hay sim-to-real.

### 9.3 Stack đề xuất và tài nguyên

| Lớp | Chọn cho MVP | Lý do / điều kiện |
|---|---|---|
| Web | React/Next.js, three.js và một splat renderer đã kiểm | Không viết rasterizer từ đầu; object picking dùng proxy ID |
| API/state | FastAPI, Pydantic, PostgreSQL | API có schema, phân quyền builder/reviewer, event log |
| Jobs/artifacts | Queue nền, object storage, worker GPU một job tại một thời điểm | Resume theo stage; tránh train và simulator tranh VRAM |
| Visual/CV | Nerfstudio/gsplat, SAM2 có prompt người dùng | Một backend train; segmentation hỗ trợ chứ không mặc định tự biết class |
| Geometry | Open3D, NumPy/SciPy, USD Python API | Xử lý hình học xác định; export units và colliders rõ |
| QA agent | LangGraph hoặc state-machine tương đương, retrieval giới hạn | Lựa chọn kỹ thuật đề xuất; không phụ thuộc một model LLM cụ thể |
| Simulator | Isaac Sim và một cấu hình robot/Nav2 có sẵn | Khóa version/container sau smoke-test tuần 1 |
| Quan sát | Log có run ID, metric store, trace agent và GPU telemetry | Theo dõi lỗi, chi phí, latency; số đo lấy từ tools |

**Điều kiện phần cứng:** tài liệu Isaac Sim 6.0.1 liệt kê RTX 4080/16 GB VRAM và RAM 32 GB ở mức tối thiểu x86_64, đồng thời lưu ý các GPU không có RT Cores như A100/H100 không được hỗ trợ. Đây là yêu cầu của release đó, không bảo đảm mọi scene của project chạy được. [W10]

Nhóm cần một máy/VM GPU có cấu hình phù hợp và quyền cài driver/container; không mặc định Kaggle/Colab hoặc một GPU CUDA bất kỳ chạy được toàn bộ pipeline. Train CV và simulation có thể chạy tuần tự trên cùng GPU. Báo cáo benchmark phải ghi đúng GPU, driver, simulator, model checkpoint, resolution và scene size.

## 9A. Agent Harness / Control Runtime

### 9A.1 State và quyền sở hữu

Workflow/harness giữ state, không để LLM giữ “sự thật” riêng trong hội thoại. LangGraph có cơ chế persistence/checkpoint; việc chống lặp side-effect và quản lý GPU jobs vẫn do ứng dụng triển khai. [W15]

```text
DRAFT -> INPUT_VALIDATED -> RECONSTRUCTED -> OBJECT_REVIEW
      -> QA_RUNNING -> QA_COMPLETE -> REVIEW_REQUIRED -> RELEASED

Nhánh lỗi: NEEDS_INPUT | BLOCKED | FAILED | CANCELLED
Edit sau QA/duyệt -> NEW_DRAFT_VERSION, không kế thừa approval
```

Một run lưu project ID, scene version, input hashes, reference frame, config hash, model/version, manifest, stage status, job IDs, evidence và approval. Scope validation cũng là dữ liệu: vùng đã kiểm, robot footprint, test suite và ngày/phiên bản scene.

### 9A.2 Harness cần làm gì?

| Thành phần | Hành vi bắt buộc |
|---|---|
| Tool registry | Chỉ cho agent gọi các tool có input/output schema; không shell tùy ý |
| Permission/policy | Không có tool điều khiển robot thật, phát hành scene hoặc đổi acceptance threshold |
| Budget | Đề xuất pilot: tối đa 6 lượt gọi tool/episode, 1 GPU rerun cần duyệt; giới hạn timeout và chi phí theo cấu hình |
| Checkpoint/idempotency | Job key gồm scene/config/input hash; retry không tạo release trùng hoặc chạy lại job đã xong vô ích |
| Human gate | Người dùng duyệt thay đổi geometry quan trọng và mọi GPU rerun ngoài preset ban đầu |
| Evidence store | Lưu tool result bất biến; agent chỉ trích evidence ID đã tồn tại |
| Recovery | Hết budget/lỗi model trả kết quả từng phần; engineer dùng rule report/editor thủ công |
| Eval hook | Replay cùng state và tool fixtures để so agent với rule-only QA; không sửa test sau khi xem kết quả |

### 9A.3 Stop conditions

Dừng và chuyển người khi chưa có scale đáng tin; nghi dữ liệu nhạy cảm; geometry còn thiếu ở vùng robot cần đi; hai bằng chứng mâu thuẫn; tool/model timeout; cần quyền ngoài allowlist; đề nghị bịa phần nền; hoặc cần hạ gate để scene được pass. Agent không được kết luận “an toàn” chỉ vì một lần navigation thành công.

## 10. Thuật toán và phần cần tự xây

### 10.1 Capture, pose và scale

MVP chuẩn hóa RGB/depth/pose theo timestamp và intrinsics; kiểm ảnh mờ, thiếu ảnh, pose NaN, số frame đăng ký và coverage. Các ngưỡng blur/coverage được hiệu chỉnh trên development set, không là tiêu chuẩn universal.

Khi dữ liệu cung cấp pose, sử dụng ở chế độ `pose_source=provided` để kiểm pipeline; kết quả không được quảng bá là nhóm đã giải SLAM. Khi mở rộng RGB-only, COLMAP dùng SfM cho pose và MVS cho dense geometry. Metric scale cần depth/scan, marker hoặc khoảng cách đo thực; không suy ra độ dài mét chỉ từ ảnh và góc nhìn. [W3][W17]

### 10.2 Tái tạo visual bằng 3DGS

3DGS biểu diễn cảnh bằng các Gaussian có vị trí, hình dạng/định hướng, opacity và thuộc tính màu. Nhóm dùng implementation có sẵn, tối ưu trên ảnh train và đánh giá ảnh ở camera giữ lại. Đóng góp đề xuất nằm ở workflow, object association, QA và tích hợp; không tự nhận có kiến trúc 3DGS mới. [W1][W2]

Những vùng có người/đồ vật chuyển động phải loại khỏi phạm vi hoặc mask trước khi train. Không biến xử lý dynamic scene thành yêu cầu ngầm của MVP. Cảnh thiếu texture, phản xạ mạnh, mặt kính hoặc ít parallax là failure case cần công khai.

### 10.3 Geometry metric và collision proxies

Nhánh ưu tiên dùng RGB-D có pose: unproject depth → đưa về frame scene → TSDF fusion → mesh → làm sạch cơ bản. Từ geometry, dùng RANSAC đề xuất plane sàn/tường; dùng bounding box có định hướng hoặc vài primitive cho vật cản đơn giản. Engineer xác nhận loại primitive và phần thể tích được dùng. [W4]

Không coi tâm Gaussian là bề mặt vật thể. Geometry dùng để đo phải lấy từ mesh/depth pipeline xác định; proxy dùng cho physics được đánh giá riêng theo độ sai vật cản/lối đi. Với kệ rỗng, một hộp lớn có thể chặn nhầm lối hợp lệ; giữ nhãn “proxy bảo thủ”, hiển thị thể tích đó và không coi bảo thủ là tự động đúng.

### 10.4 Segmentation và liên kết object qua nhiều view

Người dùng chọn điểm/hộp trên một view, SAM2 hỗ trợ mask và lan truyền qua video. SAM2 không tự cung cấp metric geometry, instance ID ổn định toàn scene hay semantic class đúng cho kho; class do người nhập/kiểm. [W5]

Nhóm xây bước gán mask vào geometry/splats bằng projection, depth/visibility check và đồng thuận nhiều view. Loại phiếu ở biên mask/occlusion; nếu các view không nhất quán, đánh dấu cần sửa. Đầu ra là tập ID/region cùng confidence nội bộ chưa hiệu chuẩn; không trình bày điểm này như xác suất đúng ngoài đời.

### 10.5 Chỉnh sửa và versioning

Mọi hide/show, translation và rotation đều qua object ID, dùng một transform gốc thống nhất cho visual và geometry. Bật/tắt chỉ để xem không nhất thiết đồng nghĩa xóa vật cản: UI phải tách “ẩn khi review” và “loại khỏi phiên bản mô phỏng”. Thay đổi physics phải tạo version và chạy QA lại.

Xóa vật thể có thể lộ vùng nền không quan sát. MVP không dùng ảnh sinh để giả lập ground truth; vùng đó giữ trạng thái unknown, yêu cầu thêm view hoặc engineer dựng proxy có ghi provenance. Đánh giá edit ở vùng đã có dữ liệu; không hứa tái tạo mọi mặt sau của vật thể.

### 10.6 Export và simulator test

Xuất USD bằng API có schema; đặt units, up axis và transform rõ, kiểm references và collider. OpenUSD quản lý metadata đơn vị; không nên phụ thuộc vào mặc định của công cụ. [W14]

Isaac Sim nhận geometry/proxy để chạy collision probes và một bài Nav2 cố định. Navigation là một smoke test có phản hồi, nhưng kết quả phụ thuộc robot, map, localization và controller. Không dùng số “tới đích” thay cho kiểm định scene; cần probe độc lập và so với geometry tham chiếu để tránh scene thiếu vật cản lại được điểm cao. [W8][W9]

### 10.7 Phân chia reuse và đóng góp

**Reuse:** 3DGS, TSDF, SAM2, USD API, robot/Nav2 mẫu. **Nhóm tự xây:** dữ liệu chuẩn hóa, object link giữa hai biểu diễn, transaction/version/approval, QA adapters, evidence-backed diagnosis, benchmark và UX review. **Ngoài scope:** world model, dynamic NeRF, SLAM mới, realistic weather/relighting, policy robot mới và simulator engine mới.

## 11. Input / Output Contract

### 11.1 Input tối thiểu — ví dụ cấu trúc, không phải dataset đã có

```json
{
  "project_id": "rav01_pilot",
  "capture_id": "indoor_capture_001",
  "rgb_uri": "artifact://input/rgb/",
  "intrinsics_uri": "artifact://input/intrinsics.json",
  "poses_uri": "artifact://input/poses.json",
  "pose_source": "provided",
  "depth_uri": "artifact://input/depth/",
  "scale_source": "calibrated_depth",
  "privacy_review": "REQUIRED",
  "allowed_use": "RESEARCH_PILOT_ONLY",
  "target_simulator": "isaac_sim",
  "region_of_interest_uri": "artifact://input/roi.json"
}
```

Hệ thống kiểm tra file, checksum, đơn vị depth, timestamp và quyền sử dụng trước khi chuyển state. URI không phải đường tải ngoài tùy ý; resolver chỉ truy cập artifact thuộc project đã cấp quyền.

### 11.2 Output trước khi kiểm định/duyệt — không tạo số đo giả

```json
{
  "scene_id": "scene_001",
  "version": 1,
  "state": "DRAFT",
  "units": "meters",
  "up_axis": "Z",
  "visual_mode": "gaussian_splat_web",
  "simulation_geometry_mode": "mesh_and_proxies",
  "object_count": null,
  "unknown_regions_uri": "artifact://scene/unknown.json",
  "metrics_uri": null,
  "simulation_test_status": "NOT_RUN",
  "approval": null,
  "deployment_scope": "SIMULATION_ONLY"
}
```

### 11.3 Invariants

Metric chưa chạy là `null/NOT_RUN`, không phải 0 hoặc PASS. Release phải trỏ tới artifact hash và QA hash khớp với version đã duyệt. Unknown region không được tự biến thành free space. Mọi thay đổi geometry/scale/test config làm approval cũ hết hiệu lực. Không đưa robot thật, mạng điều khiển thật hay thông tin định danh vào toolset. Draft được lưu để phục hồi; chỉ bản `RELEASED` mới được dùng như artifact đã duyệt.

## 12. Dataset Strategy — Dữ liệu để phát triển và kiểm thử

### 12.1 Không dùng dữ liệu đường phố để chứng minh pain trong kho

Đề gốc gợi ý nuScenes/KITTI/Waymo Open. Các nguồn đó giữ nguyên ở Phụ lục A; report không coi chúng là dataset bắt buộc. Với scope indoor, chúng không phải bằng chứng phù hợp cho khả năng xử lý sàn/kệ/lối đi trong kho. Việc chọn bộ dữ liệu indoor và RGB-D dưới đây là **đề xuất điều chỉnh cần xác nhận với mentor/BTC**. [F1]

### 12.2 Bộ dữ liệu và mục đích

| Nguồn | Dữ liệu / cách lấy | Dùng cho việc gì? | Giới hạn |
|---|---|---|---|
| TUM RGB-D: `freiburg1_room`; `freiburg1_xyz` để debug | Tải từ trang chính thức; có RGB, depth, trajectory/calibration liên quan [W11][W12] | Một scene real public để chạy pipeline, kiểm pose/depth và render held-out | Là phòng làm việc, không đại diện kho; depth có noise, không phải full mesh GT hoàn hảo |
| Synthetic indoor layouts do nhóm tạo | Script sinh sàn/tường/vật cản; renderer tạo RGB/depth/pose/mask; giữ mesh gốc ở evaluator | Ground truth kiểm geometry, edit, collision và route có thể kiểm soát | Chỉ chứng minh trên môi trường tổng hợp; không thay validation thực tế |
| Replica — mở rộng tùy điều kiện | Theo README/download và điều khoản dataset chính thức [W13] | Cảnh indoor, geometry/semantic reference cho benchmark bổ sung | Phải tự xác nhận định dạng, dựng trajectory/render và quyền dùng; không bắt buộc cho MVP |
| Capture khu vực thử của nhóm — mở rộng | Có sự cho phép; không người/PII; dùng depth hoặc khoảng cách đo đối chiếu | Kiểm tra end-to-end với dữ liệu tự thu và trải nghiệm capture | Chưa có trong đầu vào; không được ghi như đã thu hoặc đã đạt accuracy |

Ở TUM, depth lưu có scale cụ thể và 0 biểu thị thiếu dữ liệu; parser cần theo định nghĩa file thay vì giả định đơn vị ảnh depth là mét. [W12] Với mỗi nguồn, dataset manifest ghi URL, phiên bản/checksum, quyền sử dụng, kích thước thực tải, sequence và phần được đưa vào benchmark.

### 12.3 Dataset tối thiểu đề xuất

**Development:** một layout synthetic và sequence TUM đơn giản để kiểm pipeline. **Đánh giá khóa tham số:** hai layout synthetic khác về bố trí/độ che khuất; một scene public indoor cho kết quả kỹ thuật ngoài dữ liệu tổng hợp. **Tùy chọn:** thêm một khu vực thật do nhóm thu để kiểm capture/scale.

Mỗi layout giới hạn 5–10 vật cản đơn giản và một vùng quan sát có kích thước rõ; không cần hàng trăm scene. Số lượng trên là kế hoạch thu thập, không phải dataset đã được tạo. Nếu chỉ hoàn thành một scene thật, báo cáo là case study với giới hạn đó, không gọi là benchmark đại diện nhà kho.

Artifacts cho mỗi scene gồm: RGB, intrinsics, pose và timestamps; depth/scan được phép dùng; split manifest; object IDs/masks do reviewer kiểm; reference geometry hoặc reference depth; vùng quan sát hợp lệ; yêu cầu edit; robot/test config; provenance và license record.

### 12.4 Train / validation / test và chống leakage

Đối với mỗi scene, dự kiến chia khoảng 70% view cho tối ưu reconstruction, 10% validation và 20% camera view giữ lại để đánh giá; chọn theo đoạn quỹ đạo có khoảng cách, không chỉ chia ngẫu nhiên các frame gần như giống nhau. Tỉ lệ cuối cùng phải bảo đảm train vẫn có coverage và được khóa trước kết quả test.

3DGS được tối ưu riêng cho từng scene. “Test scene” nghĩa là không dùng scene đó để chỉnh pipeline/hyperparameter; vẫn có train views của chính scene để reconstruction, nhưng tuyệt đối không tối ưu bằng ảnh test hoặc geometry GT dành cho evaluator. Báo cáo tách held-out view interpolation với việc xử lý một capture/site mới.

Khi dùng synthetic data, reconstruction worker chỉ nhận những modalities khai báo; evaluator giữ mesh gốc, masks/test views và cấu hình layout kín. Không copy collider gốc sang đầu ra rồi báo là tái tạo thành công. Nếu pose GT được dùng làm input, ghi rõ chế độ đó; chỉ đánh giá ATE khi pose được ước lượng độc lập.

Geometry thật dùng depth/scan giữ lại làm reference trong vùng nhìn chung. Reference dựng lại từ chính depth đã dùng train chỉ phản ánh self-consistency, không phải accuracy độc lập. Nếu không có reference đủ tin cậy, ghi `N/A + lý do` cho metric tương ứng, không lấy tâm Gaussian hay mesh input làm đáp án.

### 12.5 Quyền dữ liệu và khả năng thương mại

Publicly downloadable không tự đồng nghĩa được bán lại. Nhóm lưu điều khoản cho dataset, pretrained weights, model code và asset simulator; không nhúng dữ liệu hạn chế vào bản phát hành công khai. Đối với thương mại, cần dữ liệu có quyền phù hợp và xem lại license của toàn chuỗi. Report không đưa ra kết luận pháp lý về quyền sử dụng từng bộ dữ liệu.

## 13. Failure Modes, Fallback và Boundary

| Failure mode | Detection / evidence | Fallback và người chịu trách nhiệm |
|---|---|---|
| Capture thiếu coverage hoặc blur | Pose registration, ảnh lỗi, bản đồ vùng quan sát | Dừng job nặng; engineer chọn lại frame/thu thêm dữ liệu |
| Scale/axis sai | Khoảng cách kiểm độc lập, gravity/floor, transform checks | Block export; engineer xác nhận reference; không tự chỉnh theo test GT |
| Geometry thiếu vật cản | Depth residual, unknown regions, raycast/reference probes | Đánh dấu vùng cấm dùng; bổ sung capture/proxy có provenance |
| Proxy quá lớn, chặn nhầm lối đi | Sai footprint, route feasible trên reference nhưng fail ở candidate | Engineer tách primitive; không chỉ đo false-free mà bỏ qua false-blocked |
| 2D mask gán nhầm 3D object | Multi-view disagreement, mask reprojection overlay | Sửa mask/group thủ công; đánh giá lại thao tác object |
| Hide/edit chỉ đổi visual | Object transform/version consistency tests | Rollback edit transaction; hủy hiệu lực QA trước đó |
| Bật/tắt object lộ nền chưa quan sát | Coverage map sau edit | Giữ unknown; không inpaint rồi dùng như evidence hình học |
| USD mở được nhưng physics sai | Collider inspection, raycast/contact probes, robot config checks | Giữ DRAFT; engineer sửa, reviewer duyệt lại |
| Navigation thất bại do robot/control | So với scene tham chiếu cùng cấu hình, log planner/localization | Phân loại lỗi control riêng; không đổ mọi lỗi cho reconstruction |
| Agent hallucinate hoặc đổi gate | Evidence lookup, tool policy, config hash | Chặn đề xuất; rule report/manual review; không sửa threshold để pass |
| OOM / timeout / reset worker | Job state, memory/exit code, heartbeat | Resume checkpoint; giảm cấu hình theo preset được duyệt; giữ run lỗi trong thống kê |
| Tài liệu/asset chứa instruction độc hại | Input isolation, allowlist và parser sandbox | Không thực thi script trong asset; quarantine và kiểm lại quyền |

**Giới hạn sử dụng:** scene chỉ phù hợp vùng và test suite đã ghi trong release manifest. Nó không thay khảo sát site, đánh giá rủi ro vận hành, nghiệm thu hệ thống robot hoặc thử nghiệm an toàn ngoài đời. Kết quả trong sim là evidence giới hạn, không phải chứng nhận.

## 14. Pilot Design và phương án đối chứng

### 14.1 Ba nhiệm vụ sản phẩm

**Task A — Tạo scene lần đầu:** cùng input capture, cùng vùng thử, cùng robot; chuẩn bị visual review, geometry/collision và gói export có thể kiểm định. **Task B — Thay đổi layout:** di chuyển một vật cản, thêm một chướng ngại đơn giản; bảo đảm dữ liệu visual/physics và QA đổi đồng bộ. **Task C — Khắc phục QA fail:** từ một lỗi cài sẵn như scale sai, thiếu collider hoặc object grouping lỗi, tìm bằng chứng và đưa scene về trạng thái có thể review.

### 14.2 Đối chứng phải đủ mạnh

| Nhánh | Công cụ được dùng | Câu hỏi được trả lời |
|---|---|---|
| B0 — workflow user hiện tại | CAD/primitive editor, công cụ scan và checklist họ đang dùng | Người dùng có thực sự cần Real2Sim không? |
| B1 — cùng công cụ CV nhưng không có workspace | Cùng 3DGS/TSDF/SAM2, script và editor sẵn có; thao tác/handoff thủ công | Workspace có giảm rework và bàn giao, hay chỉ đóng gói UI? |
| B2 — workspace không có QA agent | Cùng dữ liệu/thuật toán, rule report, object/version controls | Giá trị của hệ thống và CV độc lập với LLM |
| T — workspace có bounded QA agent | B2 + agent chọn tool/evidence với budget cố định | Agent có giảm công sức chẩn đoán đủ để bù chi phí? |

Đối chứng chính về năng suất là workflow tốt nhất phù hợp với cùng yêu cầu đầu ra; không chọn B0 yếu để tạo mức giảm đẹp. Nếu B0 chỉ cần geometry/occupancy đã đạt mục tiêu và nhanh hơn T, phải xem lại nhu cầu visual 3DGS.

### 14.3 Cách tổ chức pilot

Dự kiến 3–5 người tham gia có kinh nghiệm tương ứng; mỗi người làm các task tương đương với thứ tự được đảo giữa các nhánh. Không cho cùng người làm lại y hệt scene rồi coi tốc độ tăng do sản phẩm. Dùng các layout tương đương về số vật cản/độ che khuất; có bước làm quen công cụ như nhau.

Reviewer đánh giá artifact theo rubric đã khóa, ẩn nguồn tạo khi khả thi. Ghi cả mức kinh nghiệm và mọi trợ giúp từ thành viên phát triển. Nếu chỉ thử với bốn người trong team, gọi đó là internal pilot, không suy rộng thành kết quả người dùng chuyên nghiệp.

### 14.4 Lỗi cài sẵn và phiên bản kiểm thử

Tập QA có các phiên bản lỗi: đơn vị scale sai, thiếu collision của một vật cản, ngược trục, asset reference hỏng, object visual/physics lệch version, vùng thiếu quan sát và yêu cầu agent tự hạ ngưỡng. Ground truth là thao tác cài lỗi và điều kiện kiểm tra; cần thêm case bình thường để đo false alarm.

Tách lỗi có thể phát hiện bằng rule khỏi lỗi cần tìm thêm evidence. Agent không được đọc nhãn lỗi kín. Thu tool trace, số lượt gọi, latency, chi phí và tỷ lệ escalated đúng; không chỉ chấm văn phong của phần giải thích.

## 15. Metrics, Instrumentation và Acceptance Criteria

### 15.1 Product metrics — giá trị sử dụng

**Active person-minutes:** tổng phút thao tác của builder, người sửa và reviewer; không giấu effort review. **Time-to-first-valid-simulation:** thời gian thực từ khi input đúng điều kiện được nhận tới khi artifact qua bộ test và được duyệt, gồm queue/retry/compute. **Edit turnaround:** thời gian từ yêu cầu đổi một object đến phiên bản mới qua QA. **Rework:** số thao tác/sửa lại, số vòng reviewer trả và tỷ lệ task bỏ dở.

Mức giảm effort theo từng task:

```text
reduction = (active_time_baseline - active_time_tool)
            / active_time_baseline
```

Báo median reduction theo task/người, khoảng biến thiên và dữ liệu thô; không lấy phần trăm từ một demo đẹp nhất. Thu riêng chi phí GPU/API/storage và thời gian onboarding. Pilot nhỏ không đủ bằng chứng suy rộng ROI cho mọi doanh nghiệp.

### 15.2 Visual reconstruction metrics

| Metric | Cách đo / đơn vị | Giới hạn diễn giải |
|---|---|---|
| PSNR | Render tại held-out camera, cùng resolution/mask; dB; MSE từ RGB theo pipeline đã khóa | Không đo collision, không chứng minh đúng scale |
| SSIM | Cùng cặp render/reference, implementation và tham số cố định | Độ giống cấu trúc ảnh không thay geometry QA |
| LPIPS | Cùng normalization/backbone và vùng hợp lệ; thấp hơn tốt hơn | Phải công bố implementation; không suy thành an toàn |
| Coverage | Tỷ lệ view/vùng ROI đủ quan sát theo protocol | Không tự coi vùng ngoài capture là đúng hoặc trống |

PSNR, SSIM, LPIPS là các chỉ số nằm trong ràng buộc đề gốc; report giữ nguyên nhưng bổ sung protocol để tránh chỉ báo số mà không nói đo như thế nào. [F1] Không tính ảnh test đã dùng để chọn checkpoint tốt nhất; validation làm việc đó.

### 15.3 Geometry, semantics và chỉnh sửa

**Chamfer Distance:** dùng hai tập điểm lấy mẫu từ bề mặt mesh/reference trong cùng ROI nhìn thấy, cùng mật độ và tọa độ mét. Report chọn dạng đối xứng khoảng cách Euclid không bình phương để đơn vị là mét:

```text
CD(P,Q) = 0.5 * mean_p min_q ||p-q||
        + 0.5 * mean_q min_p ||q-p||
```

Ghi rõ số điểm, cách lấy mẫu, mask, registration và dạng công thức; không so số CD từ hai quy ước khác nhau. Không lấy tâm Gaussian làm point cloud GT của bề mặt. Report CD cho reconstruction mesh và sai số proxy trong bài navigation riêng, vì proxy cố ý đơn giản hóa hình học.

**Geometry bổ sung:** precision/recall/F-score tại tolerance đã khóa; p95 surface distance; sai số các đoạn đo độc lập; false-free và false-blocked trên vùng robot cần đi. Registration cố định bằng reference/capture landmarks trước eval; không tự ICP/scale-align theo test GT rồi giấu sai scale.

**Semantic/edit:** IoU mask tại view giữ lại; tỷ lệ gán đúng object; tỷ lệ edit làm đúng object mà không tác động object khác; tỷ lệ visual/physics giữ cùng transform/version; số phút người sửa một object. Đánh giá ít nhất một case vật thể bị che khuất, không chỉ object đứng riêng.

### 15.4 Simulation readiness — không chỉ “robot chạy được”

**Import success:** USD load được và references resolve trên runtime khóa phiên bản. **Collision correctness:** geometry không bị thiếu collider; raycast/contact probes có đáp án độc lập cho mặt sàn/vật cản. **Navigability agreement:** cùng route và footprint, kết luận lối đi có/không hợp lệ phải khớp reference; scene bỏ mất vật cản không được hưởng điểm vì robot đi dễ hơn.

**Navigation success:** với những route được reference xác nhận khả thi, robot tới goal trong timeout, không có collision ngoài điều kiện cho phép. Với route bị chặn, kết quả đúng có thể là không tìm được đường. Cố định localization/controller/sensor profile; báo lỗi do controller tách khỏi lỗi scene. Bài thử chỉ giới hạn vào robot/config/ROI đó, không chứng minh chuyển sang robot thật thành công.

### 15.5 Runtime, agent và cách thu số liệu

| Nhóm | Công cụ thu / record | Cách báo cáo |
|---|---|---|
| GPU/compute | Job start/end, memory telemetry, process exit | Phút/scene, peak VRAM, retry count; gồm cả run thất bại |
| Web rendering | Frame timing sau warm-up, cùng camera path/resolution | Median/p95 frame time và FPS; tách khỏi tốc độ simulation |
| Simulator | Sim time, wall time, contact/raycast logs | Real-time factor, import time, collision probe và route outcome |
| Human effort | Timer + screen record có consent, review/edit events | Active time, wait time và rework theo actor |
| Agent | Structured trace, evidence IDs, token/cost ledger | Tool validity, evidence grounding, correct escalation, cost/episode |
| Artifact | Checksums và manifest | Version tái lập, input/model/config/approval được dùng |

### 15.6 Acceptance gates đề xuất cho pilot

**Tất cả ngưỡng dưới đây là mục tiêu ban đầu, không phải kết quả thực nghiệm hay mức bắt buộc của BTC.** Reviewer cần xác nhận tolerance dựa trên kích thước robot/lối đi và chốt trên development set trước khi chạy test. Không điều chỉnh ngưỡng sau khi xem test để biến fail thành pass.

| Gate | Mục tiêu pilot / phạm vi đo | Nếu không đạt |
|---|---|---|
| G1. Năng suất | Median active person-minutes giảm ≥50% so với đối chứng phù hợp; tính cả review/rework | Product hypothesis chưa đạt; xem lại workflow hoặc bỏ thành phần không tạo giá trị |
| G2. Visual | Trên held-out view vùng hợp lệ: PSNR ≥25 dB, SSIM ≥0,85, LPIPS ≤0,25 là ngưỡng khởi điểm để reviewer xét | Sửa capture/reconstruction; công bố actual và failure, không chỉ chọn scene đẹp |
| G3. Geometry | Thử ban đầu trên ROI synthetic: CD trung bình đối xứng ≤0,05 m; p95 ≤0,10 m; scale error ≤2% trên đoạn đo kín | Không release cho bài thử đó; chốt tolerance chặt hơn nếu clearance yêu cầu |
| G4. Collision/unknown | 0 lỗi thiếu collider quan trọng trong bộ probes đã khóa; vùng chưa quan sát không được tự đánh dấu free | Block release; bổ sung dữ liệu hoặc sửa proxy và ghi provenance |
| G5. Edit consistency | 100% thao tác trong test suite cập nhật đúng object và đồng bộ visual/physics; đổi version phải hủy QA cũ | Sửa transaction/versioning trước khi thêm feature |
| G6. Export | Toàn bộ scene test đã duyệt mở được, resolve reference và giữ units trên runtime mục tiêu | Sửa exporter; USD “mở được” chưa thay G4/G7 |
| G7. Navigation | ≥90% lượt ở route khả thi tới goal; không xuyên vật cản; route bị chặn phải có kết luận phù hợp reference | Phân loại scene/control failure; không bỏ obstacle để tăng tỷ lệ tới đích |
| G8. Interactive review | Mục tiêu ≥20 FPS ở 1280×720 trên phần cứng công bố; p95 phản hồi edit ≤1 giây, không tính tải lần đầu | Giảm scene budget/LOD hoặc tối ưu viewer; không đổi quality gate âm thầm |
| G9. Agent hữu ích | ≥90% episode QA đúng hướng sửa hoặc escalation theo rubric; không có evidence ID bịa được chấp nhận | Dùng rule-only/manual fallback; chưa chứng minh agent cần thiết |
| G10. Quyền và dữ liệu | 100% release có reviewer; 0 lệnh robot thật; 0 chia sẻ trái phép trong bộ kiểm thử | Dừng thử nghiệm, xử lý nguyên nhân và rà lại boundary |

G2/G3 phải được báo **trước chỉnh tay và sau chỉnh tay**, kèm effort tương ứng. G4/G10 là điều kiện release trong phạm vi test hữu hạn, không phải lời bảo đảm không bao giờ có lỗi. Mức giảm wall-clock được báo riêng; mục tiêu active time không cho phép giấu deadline bị chậm vì GPU.

### 15.7 Bộ kiểm thử tối thiểu và reporting

Đề xuất tối thiểu: hai synthetic layouts giữ lại cho eval, mỗi layout 20 collision probes; 10 route có cả khả thi/bị chặn; chạy 3 seeds/cấu hình lặp để kiểm độ ổn định, đối chiếu với reference. Một scene real public báo visual/geometry reference phù hợp và giới hạn dữ liệu. Tối thiểu 20 mask/object observations được review thủ công cho semantic checks.

Số scene nhỏ khiến confidence về tổng quát hóa hạn chế; không coi hàng nghìn pixel hoặc nhiều seed cùng scene là hàng nghìn môi trường độc lập. Báo macro-average theo scene, trường hợp xấu nhất, số mẫu, protocol, phần bị loại và lý do. Nộp file CSV/JSON kết quả thực khi chạy; tại thời điểm report tất cả result vẫn là `NOT_RUN`.

## 16. Security, Privacy và Giá trị nhân văn

### 16.1 Boundary dữ liệu và hệ thống

RAV-01 yêu cầu ẩn danh khuôn mặt/biển số trước xử lý; quy định chung chỉ cho dữ liệu công khai, mô phỏng hoặc đã ẩn danh, không đưa PII/nhạy cảm thật vào hệ thống. [F1] Pilot ưu tiên capture không có người, dữ liệu được phép và không có sơ đồ doanh nghiệp nhạy cảm. Privacy check là cổng chặn trước ingest vào workflow AI, không phải blur sau khi đã gửi dữ liệu lên API ngoài.

RBAC tách builder/reviewer; không dùng shared admin account để demo approval. Worker không nhận script Python tùy ý từ người dùng hoặc USD asset; parse và conversion chạy trong sandbox hạn chế network/path. Không mount dữ liệu riêng ngoài project vào job. LLM nhận metric/log đã lọc và tài liệu cho phép; không tự có quyền vào raw capture nội bộ.

Lưu hash, provenance và audit cho edit/release. Nếu phát hiện raw capture không có quyền chia sẻ, quarantine, thu hồi đường truy cập và xử lý bản sao theo policy; không hứa xóa khỏi mọi nơi chỉ vì xóa một record metadata.

### 16.2 Vai trò con người và ảnh hưởng công việc

Sản phẩm được thiết kế để giảm khâu chuẩn bị lặp lại, giúp kỹ sư có thêm thời gian kiểm thử và phân tích; người thật vẫn xác lập requirement, tolerance, hình học thiếu bằng chứng, quyền sử dụng và phê duyệt cuối. Không dùng số nhân sự giảm làm acceptance hoặc thông điệp bán hàng.

Không thể bảo đảm tuyệt đối cách mọi doanh nghiệp sẽ sử dụng công cụ sau này. Giá trị nhân văn phải được thể hiện bằng quyền kiểm soát và KPI thực: chất lượng kiểm thử, effort tiết kiệm, giảm rework, khả năng nâng năng lực chuyên môn; không tuyên bố AI “thay Simulation Engineer”.

## 17. Kế hoạch 6 tuần / 4 người

### 17.1 Phân vai, không chia thành bốn module cô lập

| Vai trò trong team | Chịu trách nhiệm chính | Phối hợp bắt buộc |
|---|---|---|
| Thành viên A — CV/Reconstruction | Loader, pose/scale, 3DGS, visual eval | Cùng B khóa frame/units; cùng D kiểm scene hiển thị |
| Thành viên B — Geometry/Semantics | TSDF/mesh, segmentation association, proxy/collision | Cùng D kiểm object edit; cùng A kiểm geometry reference |
| Thành viên C — Backend/Harness/Infra | Auth, state/jobs, artifacts, QA agent, audit, deploy | Cùng A/B định tool contract; cùng D dựng E2E từ tuần 1 |
| Thành viên D — Frontend/Simulation | Viewer/editor, USD integration, robot/probe runner | Cần A/B hỗ trợ; không để toàn bộ Isaac/ROS2 học và tích hợp dồn cho một người |

Mỗi acceptance có người thực hiện và người review chéo. Nếu không ai đủ thời gian học geometry/Isaac, scope vẫn có rủi ro cao dù team có 4 người. Một mentor robotics tham gia checkpoint tuần 1/3/5 là điều kiện hỗ trợ nên tìm, chưa phải nguồn lực đã có.

### 17.2 Roadmap có output chạy được

| Tuần | Kết quả phải có | Gate / điều cắt bỏ |
|---|---|---|
| 1 — Validate + vertical slice | Interview bắt đầu; public indoor loader; synthetic layout; proxy USD load được, một collision probe chạy; web/API nhận job | Chốt GPU/runtime/data quyền dùng. Không đạt thì chưa GO product pilot; không đợi cuối khóa mới tích hợp simulator |
| 2 — Reconstruction + benchmark | Một scene 3DGS từ input, hình học metric; held-out render và metric tự tính; baseline task ghi timer | Khóa input format và frame convention; hoãn RGB-only tổng quát |
| 3 — Object + editor | SAM2 có người prompt; một số object gắn ID; hide/show/move và proxy đồng bộ; lưu phiên bản | Ưu tiên 3 lớp floor/wall/obstacle; bỏ open-vocabulary toàn kho và inpainting |
| 4 — Export + QA + review | Gói scene Isaac; probes/route suite; approval gắn version; web chạy E2E | Không native splat trong Isaac nếu adapter chưa ổn; ghi đúng proxy/mesh mode |
| 5 — Bounded agent + user pilot | QA agent đọc evidence, chọn tool có giới hạn; comparison rule-only; task/time logs với user | Không thêm nhiều agent. Nếu không có lợi ích, giữ phần chẩn đoán nhỏ và công khai ablation |
| 6 — Freeze + evaluation + handover | Test split đã khóa; safety/failure runs; deploy web và GPU worker; report actual metrics; video/demo/repo | Không thêm feature mới; sửa lỗi và chứng minh acceptance |

### 17.3 Critical path và scope-cut policy

Critical path là **metric input → hình học đúng → object/collision đồng bộ → simulator test → đo effort**. UI, job/audit và bộ test phải được xây song song, không đợi model “xong hẳn”. Rủi ro object-to-splat association cần spike trước khi hứa sửa mọi object.

Thứ tự cắt khi chậm: chat UI; nhiều sensor/backend; generic phone-video input; native Gaussian rendering trong Isaac; tự động nhận tất cả class; nhiều robot/scenario. Không cắt tỉ lệ/đơn vị, geometry QA, evidence, quyền reviewer hoặc báo cáo task fail. Không đổi metric sau khi biết kết quả.

Nếu tới cuối tuần 4 vẫn chưa có scene metric qua probes trên simulator, không dùng nhãn “simulation-ready application”. Có thể bàn giao mức cơ bản RAV-01 với giới hạn rõ hoặc xin BTC duyệt đổi scope, nhưng product claim phải giảm tương ứng.

## 18. Đối chiếu quy định chung, PLOs và đầu ra RAV-01

### 18.1 Quy định chung phải giữ

Theo file đề tài, mỗi đề tối đa 2 team; nhóm được tinh chỉnh dựa trên thực tế, đề mới cần BTC duyệt/ticket. Sản phẩm phải deploy web/app, có ít nhất 2 vai trò, workflow agentic có state/tool-use, HITL, xử lý lỗi và giới hạn rõ. Dữ liệu chỉ công khai/mô phỏng/ẩn danh; phải có demo chính và lỗi, eval, latency/error/cost, mã nguồn và hướng dẫn bàn giao. [F1]

Report đề xuất giữ mã **RAV-01**, kèm phụ lục scope indoor/AMR để mentor/BTC xác nhận. Bản proposal này không thể tự xác nhận còn suất đăng ký, được duyệt điều chỉnh hay đã đáp ứng các kiểm tra sản phẩm.

### 18.2 PLO coverage và evidence cần tạo

| PLO | Thiết kế đáp ứng | Evidence nghiệm thu |
|---|---|---|
| PLO1 — Kiến trúc AI Agent | QA agent giới hạn, context theo scene/run, tool contracts và policy | State graph; trace của run thành công, lỗi và escalation |
| PLO2 — Multi-Agent khi cần | MVP một agent; chỉ tách Capture QA/Sim QA nếu context/tool riêng thật sự giúp ích | Quyết định kiến trúc; ablation một/hai agent nếu có, không tạo agent hình thức |
| PLO3 — RAG khi cần | Retrieval trên tool manuals, cấu hình và case QA đã duyệt; lọc version, rerank và dẫn evidence | Bộ câu hỏi/query có đáp án, retrieval hit/grounding; nếu không cần RAG thì nêu lý do |
| PLO4 — Business Analysis | Persona, 4 lenses, problem statement, baseline và chi phí effort ròng | Interview hợp lệ, PRD/user stories, before/after task measurements |
| PLO5 — Hạ tầng/vận hành | Web/API online, job worker GPU/simulator, metrics và recovery | Deploy URL, tài khoản demo, job logs, cost/latency/error report |
| PLO6 — Safety/control | Dữ liệu an toàn, tool allowlist, simulation-only, approval gắn hash | Threat model, prompt-injection/tool misuse tests, audit review |
| PLO7 — Eval/optimization | Visual, geometry, edit, simulator và productivity metrics | Dataset/split manifests, scripts, raw results, failure analysis |
| PLO8 — AI coding/teamwork | PR có review, tests cho code sinh, owner và decision log | Repo/CI, ADR, test history; thành viên tự trình bày đóng góp |

PLO2/PLO3 trong file có điều kiện “khi bài toán cần”; không suy thành mọi project phải dùng nhiều agent hoặc RAG ở mọi bước. Ba mặt CP1 (giá trị), CP2 (triển khai), CP3 (lõi AI) phải được chứng minh đồng thời. [F1]

### 18.3 Basic / advanced: giữ, thu hẹp và hoãn

| Yêu cầu từ RAV-01 | Phạm vi trong proposal | Trạng thái cần nộp |
|---|---|---|
| Web dựng một scene mẫu từ dữ liệu công khai | Một scene indoor public với input/provenance rõ | Cam kết cơ bản; phải thực chạy |
| Xoay/zoom và bật/tắt vật thể | Splat viewer + proxy picking; object IDs đã xác nhận | Cam kết cơ bản; không chỉ bật/tắt cả scene |
| Ít nhất 2 vai trò; kỹ sư duyệt scene | Builder/reviewer, draft và release tách riêng | Cam kết cơ bản; log duyệt gắn version |
| PSNR/SSIM/Chamfer; ràng buộc còn có LPIPS | Giữ đủ, ghi protocol và reference; báo N/A nếu không có reference thay vì bịa | Phải có nguồn reference hợp lệ cho benchmark cần chứng minh |
| Pipeline tới scene chỉnh sửa được | Một input profile, vài object tĩnh và thao tác giới hạn | Nâng cao chọn lọc |
| Export CARLA/Isaac để chạy closed-loop | Chọn Isaac; mesh/proxy + một robot/Nav2; không full AV replay | Nâng cao chọn lọc; cần xác nhận mức scope với BTC |
| Chèn agent động và đổi thời tiết | Không đưa vào MVP indoor tĩnh | Hoãn có công bố, không tuyên bố đạt toàn bộ nâng cao |
| Benchmark nhiều scene; tối ưu train/render | Synthetic nhỏ + scene real public; công bố hardware/budget | Nâng cao chọn lọc, số lượng nhỏ và giới hạn rõ |

**Kết luận đối chiếu:** proposal hướng tới toàn bộ đầu ra cơ bản và một phần nâng cao có giá trị; không khẳng định hoàn thành toàn bộ mô tả nâng cao của RAV-01. Chỉ benchmark/demonstration thực sau 6 tuần mới cho phép đánh dấu các dòng là đạt.

## 19. Giá trị thương mại, nghiên cứu và điểm mạnh/yếu

### 19.1 Khách hàng, giá trị lặp lại và cách thu phí cần kiểm chứng

Phân khúc giả thuyết là đội simulation hoặc integrator xử lý nhiều site/layout và cần artifact review được. Giá trị bán là công sức chuẩn bị/đối soát tiết kiệm, không phải số lượng Gaussian hay số agent.

Có thể thử mô hình trả theo site/scene, gói nhóm kèm compute, hoặc triển khai trên hạ tầng khách hàng. Không chọn thuê bao tháng chỉ vì là “SaaS”: với khách hàng cập nhật scene rất ít, giá theo dự án có thể phù hợp hơn. Chưa có price discovery, paid pilot hoặc willingness-to-pay thật trong report.

Công thức để kiểm chứng economics của một task:

```text
Loi ich rong = chi phi cong suc baseline
             - chi phi cong suc voi tool
             - compute/API/storage
             - phan bo setup, training va support
```

Các đầu vào lấy từ người dùng và log pilot; không tự gán giá lao động/GPU để quảng bá ROI. Nếu cost hoặc effort chuyển đổi lớn hơn lợi ích, product không đáng bán dù đạt PSNR tốt.

### 19.2 Điểm mạnh, điểm yếu và điều chưa biết

| Nhóm | Nhận định | Việc phải làm |
|---|---|---|
| Điểm mạnh | Có visual demo, geometry khách quan, workflow review và khả năng mở rộng nghiên cứu | Làm E2E và công bố raw metric, không chỉ video đẹp |
| Điểm mạnh | Nhiều thành phần reuse; không cần robot thật để kiểm prototype | Giữ phạm vi an toàn, chú thích simulator-only |
| Điểm yếu | Geometry/scale/object association khó; GPU/runtime setup có thể làm chậm tiến độ | Spike trong tuần 1–3; ưu tiên input có pose/depth |
| Điểm yếu | NuRec và công cụ scene hiện có tạo cạnh tranh; pipeline tổng hợp không tự tạo khác biệt | So với workflow cùng công cụ; đo effort thật, không claim chưa ai làm |
| Chưa biết | AMR users có cần splat/visual fidelity hay 2D/CAD đã đủ | Interview cả user và reviewer trước khi chốt feature |
| Chưa biết | Nhu cầu trả phí, tần suất dùng, chi phí hỗ trợ/export dài hạn | Pilot thực, pricing interview, lần sử dụng tiếp theo |
| Chưa biết | Kết quả từ phòng nhỏ có áp dụng được cho kho thật không | Không suy rộng; bổ sung site đại diện sau khóa |

### 19.3 Hướng nghiên cứu ứng dụng

Các câu hỏi khả thi sau MVP: (1) overlay vùng chưa quan sát có giúp reviewer phát hiện lỗi tốt hơn không; (2) segmentation đa view giảm bao nhiêu effort tạo object/collider; (3) proxy bảo thủ đánh đổi false-free/false-blocked thế nào; (4) QA agent chọn phép kiểm có giảm compute và thời gian chẩn đoán so với rule plan cố định không.

Một nghiên cứu tốt phải có đối chứng và hold-out, không chỉ đổi LLM hoặc thêm một node. Chất lượng neural rendering và chất lượng navigation cần đo riêng. Chưa có kết quả mới hoặc đóng góp thuật toán đã chứng minh trong report này.

## 20. Readiness, Risks and Decision

### 20.1 Readiness hiện tại

| Câu hỏi | Trạng thái | Điều kiện để chuyển trạng thái |
|---|---|---|
| Actor/workflow rõ ở mức proposal? | Có giả thuyết cụ thể | Xác nhận với operator và reviewer thật |
| Baseline và pain evidence đã có? | NOT YET | Interview + task timing có consent và dữ liệu được phép |
| Dataset đã được tải/tạo và QA? | NOT YET | Manifest, license record, parser và split kiểm tra được |
| GPU/Isaac compatibility đã được chứng minh? | NOT YET | Smoke-test import + collision probe trên máy team sẽ dùng |
| Architecture/metrics/boundary đã được xác định? | Có thiết kế | Implement và chạy test; tài liệu không thay bằng chứng runtime |
| Scope mới đã được BTC/mentor xác nhận? | Chưa có xác nhận trong tài liệu | Chốt indoor input/target/output và phần nâng cao hoãn |
| Có thể GO vận hành thực tế? | Không | Phải có pilot đại diện, review phù hợp và đánh giá độc lập |

### 20.2 Quyết định đề xuất

**GO cho feasibility spike và user discovery trong tuần đầu.** **GO có điều kiện cho pilot 6 tuần** khi data, GPU, reviewer và phạm vi đề tài đã được xác nhận. **NOT YET cho production hoặc tuyên bố scene đủ an toàn để triển khai robot thật.**

RAV-01 đáng thử ở phạm vi này vì có đường đo quality và effort tương đối rõ, nhưng chưa có đủ evidence để kết luận đây là công cụ người dùng chắc chắn cần. Điều kiện “đáng làm” không phải model render được, mà là người dùng giải quyết đúng việc nhanh hơn với mức sai số có thể chấp nhận.

### 20.3 Kill / pivot conditions

Nếu user chỉ cần occupancy/CAD, chuyển giá trị về chuẩn hóa/QA geometry hoặc chọn bài toán khác. Nếu không có GPU/simulator và hết tuần 1 chưa xử lý được, không mở rộng thêm feature. Nếu đồng bộ object/collision làm rework tăng, ưu tiên sửa data model trước AI. Nếu agent không hơn rule-only QA, hạ autonomy và công bố kết quả ablation. Nếu tới cuối pilot không có lợi ích ròng, kết luận chưa chứng minh product hypothesis thay vì đổi metric để làm đẹp báo cáo.

## 21. Smallest Pilot That Can Prove or Kill the Idea

### 21.1 Pilot nhỏ nhất

Một khu vực synthetic có ground truth, một scene public indoor để kiểm reconstruction; ba loại object floor/wall/obstacle; một cấu hình AMR và một target Isaac Sim. Pilot đầu không cần nhiều GPU, nhiều robot, nhiều người dùng đồng thời hoặc đổi thời tiết.

Task quyết định là: **tạo scene → dịch chuyển một vật cản → xuất → phát hiện đúng thay đổi trong collision/route tests → reviewer duyệt**, đồng thời đo active time so với cùng công cụ làm thủ công. Nếu task đó chưa nhanh/chắc hơn, chưa có lý do mở rộng sang toàn kho.

### 21.2 Kịch bản demo cuối khóa — kế hoạch, chưa phải kết quả

1. Nạp capture manifest; UI chỉ ra nguồn scale, vùng được quan sát và dữ liệu thiếu nếu có.
2. Xem visual reconstruction, metric held-out và geometry/collision overlay cùng tọa độ.
3. Chọn một object, kiểm bằng chứng mask/geometry; sửa nhãn hoặc proxy khi cần.
4. Di chuyển object; version mới cập nhật cả visual và collider, approval cũ hết hiệu lực.
5. Export candidate và chạy collision probes/route checks; show một lỗi cài sẵn.
6. QA agent gọi một tool phù hợp, dẫn evidence và đề nghị sửa; engineer quyết định.
7. Chạy lại QA; reviewer duyệt đúng version; tải gói scene cùng manifest và báo cáo.
8. Mở package trên runtime mục tiêu và đối chiếu với input/version trong UI.

Không quay video một lần thành công rồi mô tả như mọi input đều chạy được. Demo phải có đường thất bại, checkpoint/resume và giải thích điều gì đang chạy live, điều gì là artifact tạo trước.

## 22. Repository và Deliverables

```text
rav01-real2sim/
  README.md
  docs/
    problem-deep-dive-report.md
    PRD.md
    ARCHITECTURE.md
    THREAT_MODEL.md
    EVAL_PLAN.md
    SCOPE_AGREEMENT.md
    ADR/
  apps/
    api/
    web/
  pipeline/
    ingest/
    reconstruction/
    geometry/
    objects/
    export_usd/
    qa/
  runtime/
    jobs/
    agent_harness/
    policies/
  simulator/
    robot_configs/
    probes/
    routes/
  datasets/
    manifests/
    splits/
    licenses/
  evals/
    visual/
    geometry/
    editing/
    productivity/
    agent/
  tests/
  deploy/
```

Dataset nặng, checkpoints và scene artifacts ở object store có version; repository giữ manifests, scripts và dữ liệu mẫu được phép. Không commit capture nội bộ hay model weight chưa có quyền phân phối.

**Gói bàn giao sản phẩm:** web deploy có hai vai trò; hướng dẫn setup và GPU/runtime đã dùng; dữ liệu demo hợp lệ; script tái lập benchmark; raw results và failure cases; model/config hashes; scene package; architecture; threat model; AI/agent traces; chi phí/latency; nhật ký quyết định; video và tài khoản demo. Những mục này là đầu ra cần làm, không phải đã được report tạo ra. [F1]

**Gói report theo mẫu:** executive summary; actor/persona/pain; four-lens scan; current/future workflow; PS v0/v1; existing solutions; Rule/Workflow/Agent; harness; I/O contract; dataset/eval; boundary/fallback; acceptance; readiness/decision. Cấu trúc kế thừa logic của [F2]–[F5], không thay nội dung PTNT-03 bằng cách đổi tên cơ học.

## 23. Kết luận đề tài

**Đề xuất chọn RAV-01 với scope indoor AMR có kiểm soát, không giữ nguyên toàn bộ tham vọng đường/kho/thời tiết/agent động.** Sản phẩm nhắm vào công sức biến capture thành scene kiểm tra được và công sức cập nhật scene, không chỉ tái tạo ảnh 3D.

Lõi kỹ thuật gồm 3DGS, geometry metric, segmentation có người hỗ trợ, scene graph đồng bộ, export và QA. Agent là trợ thủ chẩn đoán trong workflow; chat và multi-agent không phải đích đến. Kỹ sư vẫn sở hữu yêu cầu, tolerance và approval.

Điều kiện thành công là **giảm công sức ròng, giữ độ đúng cần thiết và làm rõ giới hạn sử dụng**. Kết quả đẹp nhưng mất nhiều thời gian sửa hơn, hoặc scene thiếu vật cản nhưng robot vẫn tới đích, không được coi là thành công. Report đủ để thảo luận và bắt đầu feasibility pilot; quyết định tiếp tục sản phẩm phải dựa trên evidence thu được.

## 24. Checklist theo worksheet và report mẫu

| Nội dung | Vị trí trong report | Trạng thái |
|---|---|---|
| 4 lenses; scan nhiều vấn đề; top 3 cards | 2A | Có phân tích giả thuyết, chưa thay scan cá nhân bằng trải nghiệm thật |
| Persona, pain, mission, giá trị thường xuyên | 2, 2B | Có; tần suất và willingness-to-pay chưa validate |
| Workflow trước/sau, actor/input/output/handoff | 3, 8 | Có thiết kế; baseline phải đo |
| Problem Statement v0/v1 | 4, 7.4 | Có đầy đủ trường; không giả danh kết quả khảo sát |
| Research tool và nguồn | 6, References | Có tách nguồn công khai khỏi đề gốc |
| Rule/Workflow/Agent, harness, HITL | 7, 9A, 13, 16 | Có ranh giới quyền và fallback |
| Dataset, I/O, metrics, acceptance | 11, 12, 14, 15 | Có protocol; chưa có data/run results thực |
| GO / NOT YET / NO-GO | 20 | Quyết định theo điều kiện và kill criteria |
| PLO, basic/advanced, kế hoạch 6 tuần | 17, 18 | Có đối chiếu và phần hoãn rõ |
| Nhật ký pitch/challenge/hội tụ, reflection cá nhân | Bổ sung bởi nhóm sau hoạt động thật | Không được bịa tên người, cuộc họp hoặc đóng góp |

Worksheet yêu cầu pitch/challenge và reflection phản ánh sự tham gia thật của từng học viên. Report này không viết thay trải nghiệm cá nhân hoặc tạo biên bản nhóm chưa diễn ra. [F2] Câu hỏi tự soi phù hợp: evidence nào khiến tôi đổi scope; tôi đã kiểm giả thuyết nào; AI đề nghị gì mà tôi bác bỏ; tác động thật của tôi lên artifact cuối là gì?

## Phụ lục A. Nội dung RAV-01 trong ngân hàng đề

**Nguồn:** sheet “Tất cả 382 đề”, STT 337, mã RAV-01. Phần dưới giữ nội dung các trường của đề; chỉ đổi cách dàn trang. [F1]

**Khối:** Robot & xe tự hành (Vinfast).  
**Mã đề:** RAV-01.  
**Tên đề tài:** Real2Sim Studio - Công cụ dựng lại cảnh đường/kho từ video & LiDAR thành scene mô phỏng chỉnh sửa được.  
**Max team / đề tài:** 2.

**Thực trạng:** Kỹ sư AV/robotics cần rất nhiều cảnh mô phỏng đa dạng để huấn luyện và kiểm thử policy, nhưng dựng scene 3D thủ công trong CARLA/Isaac rất tốn công, còn dữ liệu thật quay được lại không chỉnh sửa được (không thêm được người đi bộ, xe cắt ngang, đổi thời tiết).

**Vấn đề:** Xây dựng công cụ real2sim tái tạo lại một đoạn đường hoặc góc kho từ video RGB và/hoặc point cloud LiDAR thành một scene mô phỏng bằng 3D Gaussian Splatting/NeRF, cho phép kỹ sư chèn/xóa/di chuyển vật thể (agent, chướng ngại), đổi ánh sáng - thời tiết, rồi export sang định dạng dùng lại được để mô phỏng.

**Ràng buộc:** kỹ sư phải review và duyệt scene tái tạo (human-in-the-loop) trước khi đưa vào tập huấn luyện; mọi thử nghiệm policy chỉ chạy trên mô phỏng, không điều khiển xe/robot thật; chất lượng tái tạo phải đo được bằng PSNR/SSIM/LPIPS và độ khớp hình học (Chamfer distance) so với ground truth; tối ưu thời gian huấn luyện GS và độ trễ render (mục tiêu render tương tác được trên 1 GPU); dữ liệu thu thập phải ẩn danh biển số và khuôn mặt trước khi xử lý.

**Tech stack gợi ý:**

- Python, PyTorch.
- 3D Gaussian Splatting (nerfstudio/gsplat), NeRF.
- Open3D, PCL để xử lý point cloud.
- nuScenes/KITTI/Waymo Open làm dữ liệu đầu vào.
- CARLA/Isaac Sim để export & mô phỏng.
- SAM2 để tách vật thể.
- FastAPI backend.
- React/Next.js + three.js/WebGL để trực quan và chỉnh sửa scene 3D.
- DVC + MLflow quản lý phiên bản scene.
- Docker + GPU.

**Cơ bản:** web app dựng lại 1 scene mẫu từ dữ liệu công khai, trình xem 3D trên trình duyệt, cho phép xoay/zoom và bật/tắt vật thể, có ≥2 vai trò (người dựng scene và kỹ sư duyệt), báo cáo metric PSNR/SSIM/Chamfer, HITL duyệt scene trước khi lưu.

**Nâng cao:** pipeline khép kín từ video/LiDAR ra scene chỉnh sửa được, chèn agent động và đổi thời tiết, export tự động sang CARLA/Isaac để chạy closed-loop, benchmark chất lượng tái tạo trên nhiều scene và tối ưu tốc độ render/thời gian train.

## Phụ lục B. Thuật ngữ sử dụng

| Thuật ngữ | Nghĩa trong report |
|---|---|
| AMR | Robot di động tự hành; ở đây là robot mẫu chỉ chạy trong simulator |
| Real2Sim | Chuyển quan sát của môi trường thật thành biểu diễn dùng cho mô phỏng |
| 3DGS / splat | Biểu diễn hình ảnh 3D bằng các Gaussian; không tự đồng nghĩa mesh/collider |
| Collision proxy | Hình học đơn giản hóa dùng tính va chạm; phải công khai sai số và phần bị xấp xỉ |
| Scene graph | Cấu trúc object, hierarchy, transform và liên kết giữa các biểu diễn |
| Ground truth / reference | Dữ liệu dùng đối chiếu; GT synthetic khác độ tin cậy với scan thực bị nhiễu |
| ROI | Vùng được xét/kiểm định; không suy kết quả sang phần ngoài vùng này |
| HITL | Người tham gia kiểm tra/quyết định tại cổng quan trọng |
| Harness | Lớp quản lý state, quyền, budget, jobs, evidence và approval quanh agent |
| Simulation-ready | Đạt một bộ kiểm định và mục đích mô phỏng đã khai báo, không phải an toàn phổ quát |

## References

### Tài liệu được cung cấp

**[F1]** `AI20K_Ngan_hang_de_Khoa_4.xlsx` — sheet “Quy định & Mục lục”; sheet “Tất cả 382 đề”, STT 337, RAV-01. Nguồn cho đề gốc, quy định chung, PLO và mức đầu ra.

**[F2]** `01-worksheet.md` — Day 02 Lab: nguyên tắc problem-first, 4 lenses, Problem Card, workflow, validation, PS v0/v1, Rule/Workflow/Agent và decision/reflection.

**[F3]** `02-deliverable-example.md` — ví dụ Weekly Report; nguồn tham chiếu cách lập luận và trình bày, không phải evidence cho persona robotics.

**[F4]** `02-deep-dive-report.md` — ví dụ AI-assisted Feedback for Programming Labs; nguồn cấu trúc 6 fields, I/O contract, fallback, pilot và acceptance gates.

**[F5]** `AutoBridge_Problem_Deep_Dive_Report_v2.md` và `.docx` — report PTNT-03 đã tạo; tham chiếu cấu trúc, persona painpoint, mission và harness. Không dùng metrics hay thị trường PTNT-03 làm evidence cho RAV-01.

### Nguồn kỹ thuật công khai — truy cập 16/09/2026

**[W1]** Kerbl và cộng sự — 3D Gaussian Splatting for Real-Time Radiance Field Rendering, SIGGRAPH 2023.  
https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/

**[W2]** Nerfstudio — Splatfacto: training, viewer và Gaussian splat export.  
https://docs.nerf.studio/nerfology/methods/splat.html

**[W3]** COLMAP — Tutorial: Structure-from-Motion và Multi-View Stereo.  
https://colmap.github.io/tutorial

**[W4]** Open3D — RGB-D integration / TSDF.  
https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html

**[W5]** Meta — SAM 2 official repository: promptable image/video segmentation, checkpoints và license.  
https://github.com/facebookresearch/sam2

**[W6]** NVIDIA — Omniverse NuRec: neural reconstruction và rendering integrations.  
https://developer.nvidia.com/omniverse/nurec

**[W7]** NVIDIA — Isaac Sim overview.  
https://developer.nvidia.com/isaac/sim/

**[W8]** NVIDIA — Physics Simulation Fundamentals.  
https://docs.isaacsim.omniverse.nvidia.com/latest/physics/simulation_fundamentals.html

**[W9]** NVIDIA — ROS 2 Navigation tutorial.  
https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/robot_control/tutorial_ros2_navigation.html

**[W10]** NVIDIA — Isaac Sim 6.0.1 Requirements; ví dụ release được kiểm tra tài liệu, chưa phải runtime đã cài của nhóm.  
https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/requirements.html

**[W11]** TUM Computer Vision Group — RGB-D Dataset Download.  
https://cvg.cit.tum.de/data/datasets/rgbd-dataset/download

**[W12]** TUM Computer Vision Group — RGB-D File Formats.  
https://cvg.cit.tum.de/data/datasets/rgbd-dataset/file_formats

**[W13]** Meta — Replica Dataset official README/download.  
https://github.com/facebookresearch/Replica-Dataset/blob/main/README.md

**[W14]** OpenUSD — Encoding Stage Linear Units.  
https://openusd.org/release/api/group___usd_geom_linear_units__group.html

**[W15]** LangGraph — Persistence / checkpoints.  
https://docs.langchain.com/oss/python/langgraph/persistence

**[W16]** CARLA — official simulator overview.  
https://carla.org/

**[W17]** COLMAP — Frequently Asked Questions: model alignment và các vấn đề reconstruction.  
https://colmap.github.io/faq.html

Các URL `latest` có thể thay đổi; khi triển khai phải ghi lại version/docs snapshot trong repo. Không coi việc kiểm tra tài liệu là đã chạy thử software, đã tải dataset hay đã vượt acceptance.