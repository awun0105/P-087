# RAV-01 — Real2Sim Workspace

*Báo cáo phân tích đề tài: giúp kỹ sư chuẩn bị môi trường thử robot từ dữ liệu khảo sát*

**Phạm vi đề xuất:** Một khu vực trong nhà tĩnh, một tầng; có sàn, tường và một số vật cản. Nhóm 4 người thực hiện trong 6 tuần. Sản phẩm chỉ phục vụ thử nghiệm trên máy tính, không điều khiển robot thật.

**Ý chính:** Người kỹ sư không chỉ cần một bản sao 3D để nhìn. Họ cần một bản sao có kích thước, vật cản và trạng thái kiểm tra rõ ràng để thử một bài toán robot cụ thể. Real2Sim Workspace được đề xuất để giảm công việc dựng, sửa và kiểm tra bản sao đó.

## 1. Trước hết, đề tài này giúp ai làm việc gì?

### Bắt đầu từ một tình huống cụ thể

Hãy xét một tình huống minh họa: một đội kỹ sư chuẩn bị thử robot di chuyển trong một góc kho. Trong khu vực đó có sàn, tường, các kệ và một vài kiện hàng. Họ muốn thử một đường đi từ vị trí A đến vị trí B, rồi kiểm tra điều gì thay đổi khi một vật cản được chuyển sang chỗ khác. Đây là ví dụ để giải thích phạm vi đề xuất, không phải một dự án khách hàng đã được khảo sát.

Robot trong ví dụ thuộc nhóm AMR, tức robot di động tự hành. Tuy nhiên, nhóm làm RAV-01 **không chế tạo robot và cũng không viết lại toàn bộ phần mềm điều khiển robot**. Nhóm sử dụng một robot mẫu và một cấu hình điều hướng có sẵn trong môi trường thử trên máy tính. Công việc của đề tài nằm ở phía còn lại: chuẩn bị khu vực mà robot sẽ được đặt vào để chạy thử. [1, mục 2, 10 và 21]

Phần mềm mô phỏng, trong phạm vi báo cáo là **Isaac Sim**, đóng vai trò môi trường chạy thử. Có thể hình dung nó là nơi kỹ sư đặt một robot ảo vào một không gian ảo, cho robot chạy và quan sát kết quả. Nhưng phần mềm này không tự biết góc kho đang khảo sát trông thế nào, rộng bao nhiêu, có vật cản ở đâu. Những thông tin đó phải được đưa vào bằng một mô hình môi trường.

Mô hình môi trường này thường được gọi là **scene**. Trong ví dụ, scene không phải cả một thành phố hoặc toàn bộ nhà máy: nó chỉ là bản sao của khu vực nhỏ có sàn, tường, kệ và kiện hàng mà đội kỹ sư cần thử. **Real2Sim** có nghĩa là chuyển dữ liệu quan sát môi trường thật thành một biểu diễn có thể dùng trong mô phỏng. [1, mục 9, 10 và phụ lục B]

### Vì sao có video của kho vẫn chưa đủ?

Video cho biết cảnh nhìn như thế nào từ những góc máy đã quay. Nhưng để thử đường đi của robot, phần mềm còn cần biết phần nào là mặt sàn, phần nào là khối vật cản, chúng nằm ở đâu và có kích thước bao nhiêu. Nó cũng cần biết khi robot chạm vào một vật cản thì phải tính là va chạm, chứ không để robot đi xuyên qua vật đó.

Hãy lấy một chiếc kệ làm ví dụ. Trên màn hình, ta có thể nhìn thấy chiếc kệ rất rõ. Tuy nhiên, nếu phần dữ liệu mô tả khối vật cản của kệ bị thiếu, hình ảnh chiếc kệ vẫn hiện ra nhưng robot trong phép thử có thể đi xuyên qua. Ngược lại, nếu mô tả kệ bằng một khối quá lớn, phần mềm có thể coi một lối đi thực tế còn trống là đã bị chặn. **Nhìn giống và dùng đúng là hai yêu cầu khác nhau.** [1, mục 10.3 và 15.4]

Đây là lý do đề tài không nên dừng ở “tải video lên, dựng được một cảnh 3D đẹp”. Đầu ra có giá trị phải giúp người kỹ sư chuẩn bị được dữ liệu môi trường phù hợp với bài thử, biết chỗ nào đáng tin và chỗ nào cần sửa hoặc đo thêm.

### Người dùng chính và người được hưởng lợi

Người sử dụng chính được đề xuất là **kỹ sư chuẩn bị môi trường mô phỏng**. Công việc của họ là nhận dữ liệu khảo sát, dựng bản sao, chỉnh sửa và bàn giao một phiên bản dùng được cho bài thử. Một kỹ sư khác hoặc trưởng nhóm sẽ kiểm tra và duyệt phiên bản đó. Người phụ trách tích hợp robot xác định bài thử cần gì: robot nào, đường đi nào, vùng nào phải kiểm tra và sai số nào chấp nhận được. [1, mục 2.1]

Vì vậy, sản phẩm cần giúp cả người làm lẫn người kiểm. Nếu nó giúp người dựng tiết kiệm thời gian nhưng lại khiến người duyệt phải kiểm tra, sửa lại rất nhiều, tổng công sức chưa chắc giảm. Mục tiêu là giảm **tổng công việc của cả quá trình**, không chỉ làm một bước trông nhanh hơn.

Các vai trò và tình huống trên vẫn là giả thuyết sản phẩm. Báo cáo gốc chưa có phỏng vấn, nhật ký công việc hay số liệu khách hàng xác nhận mức độ khó khăn của họ. Đó là phần cần kiểm chứng trước khi kết luận sản phẩm thật sự đáng bán. [1, mục 5]

## 2. Khi chưa có ứng dụng, người kỹ sư phải làm những gì?

Quy trình dưới đây là cách diễn giải chi tiết hơn của quy trình dự kiến trong báo cáo gốc. Nó cần được đối chiếu với người làm thực tế; không phải mọi đội robot đều làm giống hệt nhau. Một đội đã có bản vẽ thiết kế sạch có thể làm nhanh hơn nhiều so với đội chỉ có ảnh hoặc dữ liệu quét. [1, mục 3]

**Bước 1 — Chốt khu vực cần dựng và việc cần thử.**

Trước khi dựng 3D, người kỹ sư phải hỏi: cần mô phỏng khu vực nào, robot sẽ đi đâu, và cần kiểm tra điều gì? Trong ví dụ góc kho, yêu cầu có thể là giữ lại sàn, tường, các kệ nằm quanh đường A–B và một kiện hàng sẽ được di chuyển để tạo bố trí khác. Những phần nằm ngoài khu vực thử không nhất thiết phải dựng.

Đầu ra của bước này là một yêu cầu có thể kiểm tra được. Nếu chưa chốt yêu cầu, người dựng có thể mất công làm đẹp những chi tiết không ảnh hưởng đến bài thử, hoặc bỏ sót một vật cản quan trọng. Người duyệt cũng sẽ không có căn cứ rõ ràng để nói bản sao đã đạt hay chưa.

**Bước 2 — Nhận ảnh, dữ liệu quét và thông tin kích thước.**

Người khảo sát cung cấp những gì họ có: ảnh hoặc video, dữ liệu chiều sâu, dữ liệu quét, bản vẽ hoặc số đo. Ảnh màu cho biết bề ngoài; dữ liệu chiều sâu cho biết khoảng cách từ camera đến các bề mặt mà nó quan sát. Nếu có dữ liệu chiều sâu đi kèm ảnh màu, bộ dữ liệu đó được gọi là **RGB-D**.

Người dựng cần kiểm tra dữ liệu có đủ nhìn thấy vùng phải thử không. Ví dụ, chỉ quay mặt trước chiếc kệ thì chưa biết chắc phần phía sau nó có gì. Họ cũng phải xác định đơn vị kích thước. Video đơn thuần không bảo đảm tự suy ra đúng khoảng cách theo mét. Trong phiên bản đề xuất, nhóm ưu tiên dữ liệu có chiều sâu, vị trí camera hoặc tham chiếu đo được để không biến việc đo kích thước thành một bài toán chưa giải quyết. [1, mục 6.3, 10.1 và 12]

**Bước 3 — Dựng hình dạng và đưa mọi thứ về cùng vị trí, kích thước.**

Người kỹ sư dùng công cụ dựng 3D hoặc xử lý dữ liệu quét để tạo sàn, tường và vật cản. Họ phải bảo đảm mọi thành phần cùng dùng một hệ tọa độ, hiểu đơn giản là cùng một cách xác định gốc vị trí, các hướng và đơn vị đo. Nếu một phần hiểu đơn vị là mét còn phần khác hiểu theo đơn vị khác, cảnh có thể nhập được nhưng kích thước bị sai.

Đầu ra chưa chỉ là một bức ảnh đẹp. Nó phải có thông tin hình dạng đủ để các bước sau phân biệt lối đi và vật cản. Những vùng không có dữ liệu quan sát phải được giữ như vùng chưa biết, không được mặc định là khoảng trống an toàn cho robot.

**Bước 4 — Chỉ rõ vật nào là một đối tượng và phần nào gây va chạm.**

Để di chuyển riêng một kiện hàng, phần mềm cần biết các phần dữ liệu nào thuộc kiện hàng đó. Công việc chia vùng dữ liệu theo vật thể được gọi là **tách vật thể**. Sau đó, kỹ sư đặt tên hoặc nhãn cho nó và tạo hình học dùng để kiểm tra va chạm.

Hình học va chạm có thể đơn giản hơn hình ảnh. Chẳng hạn, một kiện hàng gần dạng hộp có thể dùng một khối hộp để tính va chạm. Tuy nhiên, người kỹ sư vẫn phải kiểm tra khối hộp có đúng vị trí và kích thước không. Với một chiếc kệ có nhiều khoảng rỗng, dùng một hộp lớn bao toàn bộ kệ có thể không phù hợp với bài thử. [1, mục 10.3–10.5]

**Bước 5 — Đưa cảnh vào phần mềm mô phỏng, chạy kiểm tra, sửa rồi bàn giao.**

Người dựng đưa dữ liệu môi trường vào Isaac Sim, đặt robot mẫu và chạy các phép kiểm tra đã thống nhất. Nếu file lỗi, vật thể nằm sai vị trí, sàn không đúng hoặc robot đi xuyên vật cản, họ phải quay lại tìm lỗi và sửa. Người duyệt sau đó kiểm tra cả cảnh và kết quả thử trước khi cho phép sử dụng phiên bản đó.

Công việc chưa kết thúc vĩnh viễn sau lần đầu. Nếu kiện hàng được chuyển chỗ, người dựng phải cập nhật bản sao và kiểm tra lại. Nếu họ chỉ đổi phần hình ảnh mà quên đổi phần dùng tính va chạm, phép thử tiếp theo sẽ chạy trên một môi trường không nhất quán. Đây là một lý do công sức bảo trì cũng phải nằm trong bài toán, không chỉ công sức dựng lần đầu.

> **Điểm đau cần kiểm chứng:** Người kỹ sư phải tự nối dữ liệu khảo sát, hình ảnh 3D, hình dạng vật cản và kết quả thử qua nhiều công đoạn. Phần tốn công có thể nằm ở việc làm cho chúng đúng và khớp nhau, rồi sửa lại mỗi khi có thay đổi — không nhất thiết nằm ở thời gian máy chạy thuật toán dựng 3D.

### Nhìn vấn đề qua bốn lăng kính của worksheet

| Lăng kính | Áp dụng vào tình huống góc kho |
|---|---|
| **Lặp lại** | Khi có khu vực mới hoặc đổi bố trí, kỹ sư lại phải chuẩn bị, sửa và kiểm tra bản sao. Cần hỏi họ việc này thực tế xảy ra bao nhiêu lần. |
| **Tốn thời gian** | Cần đo công sức căn kích thước, tách vật thể, sửa hình học va chạm, nhập cảnh và kiểm tra lại. Không tự gán một số giờ khi chưa quan sát. |
| **AI có thể hỗ trợ tốt hơn** | AI thị giác có thể hỗ trợ dựng hình ảnh và khoanh vùng vật thể. Trợ lý chẩn đoán có thể giúp tìm phép kiểm tra tiếp theo khi lỗi khó xác định. Các phép đo vẫn phải do thuật toán thực hiện. |
| **Khó khăn của người khác** | Người nhận bản sao cũng gặp việc phải kiểm lại dữ liệu, hỏi chỗ thiếu thông tin hoặc trả lại bản chưa đạt. Cần phỏng vấn cả người dựng và người nhận, không chỉ người phát triển ứng dụng. |

Bốn lăng kính trên giúp đặt câu hỏi đúng, chưa thay thế bằng chứng. Bản gốc cũng xác định một phép thử quan trọng: nếu quy trình hiện có của khách hàng đã nhanh và đáp ứng yêu cầu, thêm Real2Sim có thể không mang lại lợi ích. [1, mục 2A; 3]

## 3. Real2Sim Workspace sẽ thay đổi quy trình đó như thế nào?

Ứng dụng được đề xuất không hứa làm thay toàn bộ người kỹ sư. Nó chuẩn bị các kết quả trung gian, nối chúng lại và kiểm tra những điều có thể kiểm tra bằng chương trình, để con người tập trung vào vùng dữ liệu chưa chắc chắn và quyết định chuyên môn.

Có thể nhìn toàn bộ công việc theo chuỗi sau:

```text
Dữ liệu khảo sát + yêu cầu bài thử
                ↓
Kiểm tra dữ liệu có đủ điều kiện sử dụng không
                ↓
Dựng hình ảnh 3D và hình dạng môi trường
                ↓
Người kỹ sư kiểm, sửa và chỉnh từng vật thể
                ↓
Chương trình chạy các phép kiểm tra trong mô phỏng
                ↓
Người duyệt xác nhận phiên bản và phạm vi được dùng
```

**Bước 1 — Người kỹ sư tạo một công việc mới và đưa dữ liệu vào.**

Thay vì bắt đầu bằng một cuộc trò chuyện với chatbot, họ mở trang tạo cảnh, chọn bộ ảnh/chiều sâu và khai báo khu vực cần thử. Hệ thống phải cho biết dữ liệu thuộc khu vực nào, lấy từ đâu, dùng đơn vị gì và đã được phép sử dụng hay chưa. Với dữ liệu mẫu, những thông tin này có thể được chuẩn bị trong một tệp đi kèm.

Hệ thống kiểm những lỗi đầu vào trước khi chạy tác vụ nặng: file thiếu, dữ liệu vị trí camera không hợp lệ, chưa có nguồn xác nhận kích thước, hoặc phần cần dựng chưa được quan sát đủ. Khi phát hiện vấn đề, nó yêu cầu bổ sung cụ thể. Nó không được cứ chạy để cuối cùng trả về một cảnh trông hoàn chỉnh nhưng không đủ căn cứ sử dụng. [1, mục 8 và 11]

**Bước 2 — Hệ thống dựng hai loại dữ liệu phục vụ hai mục đích khác nhau.**

Loại thứ nhất là **hình ảnh 3D để người dùng xem và đối chiếu**. Bản thiết kế dùng 3D Gaussian Splatting, gọi tắt là 3DGS, cho phần này. Ở mức cần hiểu để đọc đề tài, đó là một phương pháp học cách biểu diễn cảnh từ nhiều ảnh để hiển thị cảnh ở các góc nhìn khác.

Loại thứ hai là **hình dạng môi trường để phần mềm tính toán**: mặt sàn ở đâu, tường ở đâu, vật cản chiếm phần không gian nào. Bản thiết kế đề xuất lấy thông tin này từ dữ liệu chiều sâu hoặc dữ liệu quét. Hai loại dữ liệu phải cùng vị trí, kích thước và phiên bản. Một loại giúp kiểm bằng mắt; loại còn lại phục vụ các phép kiểm tra vật lý. Không có bước đổi đuôi file nào tự biến hình ảnh 3D đẹp thành mô hình va chạm đúng. [1, mục 9.1–9.2 và 10]

**Bước 3 — Người kỹ sư xem đề xuất và sửa đúng phần cần sửa.**

Trên màn hình, người dùng nhìn thấy cảnh 3D cùng danh sách vật thể. Họ chọn một kiện hàng và kiểm xem phần được khoanh có đúng là kiện hàng đó không. Công cụ tách vật thể có thể hỗ trợ việc khoanh vùng, nhưng người dùng vẫn phải xác nhận, nhất là khi hai vật thể che khuất nhau.

Tiếp theo, họ bật lớp hiển thị khối va chạm để so với hình ảnh. Nếu khối quá rộng, họ sửa kích thước; nếu gán nhầm hai kiện hàng thành một vật thể, họ tách lại. Các vùng chưa đủ dữ liệu được làm nổi rõ để người duyệt biết giới hạn của kết quả. Giá trị mong muốn là họ sửa một đề xuất đã có, thay vì phải dựng và kết nối mọi thứ từ đầu. Nếu sửa đề xuất còn lâu hơn tự làm, phần hỗ trợ này chưa đạt mục tiêu.

**Bước 4 — Khi đổi bố trí, ứng dụng cập nhật mọi phần liên quan cùng nhau.**

Giả sử người dùng chuyển một kiện hàng sang bên cạnh lối A–B. Sau thao tác, ứng dụng phải di chuyển cả hình ảnh của kiện hàng lẫn khối dùng để tính va chạm. Kết quả kiểm tra cũ không được tiếp tục hiển thị là còn hiệu lực, vì môi trường đã thay đổi. Hệ thống lưu thành một phiên bản mới để có thể kiểm tra và so lại với bản trước.

Cũng cần tách hai hành động dễ nhầm: **ẩn vật thể để nhìn cho rõ** và **loại vật thể khỏi bố trí mô phỏng**. Hành động thứ nhất chỉ phục vụ quan sát; hành động thứ hai làm thay đổi bài thử và phải kiểm tra lại. Nếu việc xóa một kiện hàng làm lộ vùng phía sau chưa từng được quay, ứng dụng phải báo vùng đó chưa biết, không tự tạo một mặt sàn rồi coi như dữ liệu thật. [1, mục 10.5]

**Bước 5 — Hệ thống đưa cảnh vào Isaac Sim và chạy phép kiểm tra.**

Trước hết, nó kiểm xem cảnh có mở được đúng không, kích thước và vật cản có được giữ khi chuyển sang phần mềm mô phỏng không. Sau đó, nó thực hiện các phép kiểm tra tại những vị trí đã chọn. Ví dụ, vị trí có một vật cản trong dữ liệu tham chiếu phải được nhận là có vật cản trong bản sao; lối đi còn trống không được bị chặn nhầm bởi một khối dựng quá lớn.

Cuối cùng mới chạy bài thử robot mẫu. Với đường đã biết là đi được, robot cần tới đích theo điều kiện đã thống nhất. Với đường bị chặn, không tìm được đường có thể mới là kết quả đúng. **Robot tới đích không tự chứng minh bản sao đúng:** một bản sao bỏ sót hết vật cản có thể khiến robot đi dễ hơn nhưng lại hoàn toàn không phản ánh khu vực cần thử. [1, mục 15.4]

**Bước 6 — Khi có lỗi, ứng dụng giúp điều tra; khi đạt, con người mới duyệt.**

Nếu kết quả không đúng, màn hình cần chỉ rõ phép kiểm tra nào thất bại và liên kết tới phần dữ liệu liên quan. Trợ lý AI có thể đề nghị kiểm lại kích thước, vị trí vật thể, dữ liệu va chạm hoặc phiên bản đang được dùng. Nó không được chỉ trả một câu chung chung như “cần cải thiện chất lượng cảnh”.

Sau khi người kỹ sư sửa và chạy kiểm tra lại, người duyệt xem phiên bản, kết quả và những vùng chưa được xác nhận. Chỉ khi người này đồng ý, ứng dụng mới xuất bản cảnh kèm hồ sơ kiểm tra để đội khác sử dụng. Những bản nháp vẫn được lưu để tiếp tục công việc, nhưng không mang nhãn “đã duyệt”. Một lần sửa sau đó phải dẫn tới kiểm tra và duyệt lại. [1, mục 8.2 và 11.3]

### Như vậy, công việc nào thực sự được giảm?

Người dùng vẫn chịu trách nhiệm chọn bài thử, xác nhận chỗ thiếu dữ liệu và quyết định bản sao có phù hợp hay không. Phần cần giảm là thao tác chuẩn bị dữ liệu, khoanh vật thể, nối hình ảnh với hình dạng va chạm, cập nhật nhiều tệp sau một lần sửa và tự tìm lại bằng chứng kiểm tra.

Đầu ra mà họ nhận được không chỉ là một tệp 3D. Đó là **một phiên bản môi trường kèm các vật thể có thể chỉnh sửa, dữ liệu để mở trong mô phỏng và hồ sơ cho biết đã kiểm gì, ai duyệt, còn giới hạn gì**. Người dùng không phải mất thêm một vòng tự chứng minh từ đầu trước khi dùng nó trong bài thử đã định.

**Sứ mệnh đề xuất:** Giảm công sức chuẩn bị và cập nhật môi trường thử, để kỹ sư dành nhiều thời gian hơn cho thiết kế thí nghiệm và phân tích hành vi robot. Không lấy giảm số kỹ sư hoặc thay người duyệt làm thước đo thành công. [1, mục 2B và 16]

## 4. Nhóm sẽ làm đến đâu, và AI thực sự nằm ở chỗ nào?

### Giữ một bài toán nhỏ nhưng làm đủ đầu đến cuối

Đề RAV-01 gốc cho phép dựng cảnh đường hoặc kho, dùng video hoặc LiDAR, chỉnh vật thể và hướng tới mô phỏng với CARLA hoặc Isaac Sim. Phiên bản đề xuất trong báo cáo thu hẹp về **một khu vực trong nhà tĩnh**, dùng **một phần mềm mô phỏng là Isaac Sim**. Đây là lựa chọn phạm vi, không phải khẳng định Isaac Sim luôn tốt hơn CARLA. [1, mục 6.2–6.3; 2]

Lý do thu hẹp là để nhóm có thể chứng minh trọn một việc: nhận dữ liệu, dựng cảnh, sửa một vật cản, kiểm tra lại và bàn giao. Không nhận đồng thời việc dựng đường giao thông, tái hiện xe đang chuyển động, thay đổi thời tiết, tạo nhiều robot và xây mô hình điều khiển mới.

| Việc cần hoàn thành trong phiên bản đầu | Việc chưa nhận làm |
|---|---|
| Dựng một khu vực nhỏ, sàn và tường tương đối đơn giản, một số vật cản tĩnh | Dựng đúng toàn bộ kho, nhà máy hoặc đường phố bất kỳ |
| Dùng ảnh màu có thông tin camera, cùng chiều sâu hoặc dữ liệu đo phù hợp | Hứa rằng video điện thoại bất kỳ luôn đủ để dựng đúng kích thước |
| Chọn, bật/tắt và di chuyển vật thể đã được kiểm; cập nhật dữ liệu va chạm tương ứng | Xóa vật thể rồi tự dựng hoàn hảo những phần trước đó bị che khuất |
| Xuất cảnh cho một bài thử robot mẫu; người kiểm tra duyệt phiên bản | Điều khiển robot thật, chứng nhận an toàn hoặc tự động cho phép triển khai ngoài đời |

Thay đổi từ “đường hoặc kho” sang “khu vực trong nhà”, cùng cách chọn dữ liệu và phần nâng cao hoãn lại, cần được ghi rõ để mentor/BTC xác nhận. Không được tự coi đã đáp ứng toàn bộ mô tả nâng cao chỉ vì phiên bản nhỏ chạy thành công. [1, mục 18]

### Bên trong hệ thống: mỗi công nghệ phục vụ một việc cụ thể

**Phần dựng hình ảnh** dùng 3DGS đã có sẵn, không tự phát minh thuật toán mới. Nó nhận ảnh và thông tin camera để tạo phần cảnh người dùng có thể xoay nhìn. **Thông tin camera** ở đây gồm cách camera tạo ảnh và vị trí/hướng của camera khi chụp từng ảnh. Nếu thiếu những thông tin này, phải có bước ước lượng; công cụ COLMAP là hướng mở rộng được báo cáo gốc nêu. Phiên bản đầu ưu tiên dữ liệu có thông tin camera để giảm rủi ro. [1, mục 10.1–10.2]

**Phần dựng hình dạng** ghép dữ liệu chiều sâu ở các góc nhìn về cùng một không gian, tạo bề mặt và đề xuất sàn, tường, khối vật cản. Báo cáo gốc nêu Open3D và các thuật toán ghép chiều sâu, tìm mặt phẳng cho công việc này. Điều người đọc cần nắm không phải tên mọi thuật toán, mà là vai trò: biến các số đo khoảng cách thành hình dạng có thể kiểm tra trong mô phỏng. Phần hình dạng này không được suy ra chỉ bằng cách lấy những điểm hiển thị của 3DGS làm bề mặt thật. [1, mục 10.3]

**Phần tách và chỉnh vật thể** sử dụng SAM2 để hỗ trợ khoanh vùng sau khi người dùng chỉ điểm hoặc khung. Nhóm vẫn phải tự xây phần liên kết vùng ảnh với vật thể 3D, lưu tên vật thể và cập nhật đồng thời các biểu diễn khi chỉnh sửa. Đây là một công việc kỹ thuật quan trọng, không phải cứ nối SAM2 vào 3DGS là có ngay trình chỉnh sửa hoàn chỉnh. [1, mục 10.4–10.5]

**Phần ứng dụng** quản lý công việc nền, giao diện xem/sửa, phiên bản, kết quả kiểm tra và phê duyệt. Backend FastAPI nhận yêu cầu; các tiến trình xử lý riêng thực hiện tác vụ nặng; giao diện web hiển thị tiến độ. Khi đổi một vật thể, hệ thống phải biết kết quả nào còn dùng lại được và kiểm tra nào phải chạy lại. Nếu phần này thiếu, người dùng vẫn phải tự nối và kiểm mọi bước, dù từng thuật toán riêng lẻ chạy tốt. [1, mục 9]

### Rule, workflow, agent và harness khác nhau ở đây ra sao?

**Rule là các quy tắc rõ ràng do lập trình viên đặt.** Ví dụ: thiếu dữ liệu kích thước thì không cho xuất bản đã kiểm; số đo phải do chương trình tính; phiên bản đã thay đổi thì kết quả duyệt cũ hết hiệu lực. Không cần LLM suy nghĩ lại những điều này mỗi lần chạy.

**Workflow là trình tự xử lý có trạng thái.** Hệ thống biết công việc đang ở bước nhận dữ liệu, dựng cảnh, chờ sửa vật thể hay chờ người duyệt. Nếu một tác vụ thất bại, nó giữ phần đã làm và cho tiếp tục từ bước phù hợp. Workflow trả lời “đang làm đến đâu và bước hợp lệ tiếp theo là gì?”.

**Agent là trợ lý được phép lựa chọn bước điều tra trong một phạm vi nhỏ.** Ví dụ, cảnh đã nhập được nhưng phép thử vật cản thất bại. Trợ lý có thể đọc kết quả, chọn kiểm kích thước hoặc đối chiếu vị trí giữa hình ảnh và khối va chạm, rồi đưa ra đề nghị có bằng chứng. Nó không tự đặt số đo, tự hạ tiêu chuẩn hoặc tự ký duyệt cảnh. Một bộ quy tắc có thể đủ cho lỗi đơn giản; chỉ giữ agent nếu nó giúp xử lý trường hợp khó tốt hơn. [1, mục 7 và 9A]

**Harness là lớp kiểm soát bao quanh agent.** Với nền tảng IT, có thể hiểu nó là phần ứng dụng quản lý quyền gọi công cụ, thời gian chạy, ngân sách, lưu trạng thái và nhật ký. Nó không phải một “mô hình thông minh” khác. Trong thiết kế này, agent không có công cụ điều khiển robot thật hoặc duyệt kết quả của chính nó; khi hết quyền hay hết ngân sách, công việc trở về cho con người.

Vì vậy, kết luận kiến trúc là: **thuật toán thị giác và hình học làm phần tái tạo; quy tắc và workflow quản lý quy trình; một agent hỗ trợ chẩn đoán lỗi dưới sự kiểm soát của harness; con người quyết định ở các điểm quan trọng.** Không cần giao diện chat. Nút “Phân tích lỗi” bên cạnh kết quả kiểm tra có thể phù hợp hơn một chatbot nằm giữa sản phẩm.

### Một giới hạn kỹ thuật không được giấu

Trong phiên bản đầu, hình ảnh 3DGS có thể được xem trên web, còn Isaac Sim sử dụng mô hình bề mặt và các khối vật cản được xuất sang. **Không được nói camera của robot đang nhìn hình ảnh 3DGS nếu thực tế nó chỉ nhìn mô hình hình học đơn giản.** Đưa Gaussian vào hiển thị trực tiếp trong simulator là một nhánh tích hợp riêng, không phải điều mặc nhiên xảy ra khi xuất file. [1, mục 9.2]

Điều đó vẫn cho phép kiểm tra quy trình dựng/sửa cảnh và hình học của một bài thử giới hạn. Nhưng nó chưa chứng minh chất lượng nhận diện bằng camera trong môi trường giống ảnh thật, và càng chưa chứng minh robot sẽ hoạt động đúng ngoài đời.

## 5. Lấy dữ liệu ở đâu và làm sao biết sản phẩm có ích?

### Dữ liệu dùng để xây không giống dữ liệu dùng để chứng minh

Bản thiết kế đề xuất bắt đầu bằng **TUM RGB-D**, một nguồn dữ liệu trong nhà có ảnh màu, chiều sâu và thông tin liên quan đến camera/quỹ đạo. Sequence `freiburg1_xyz` dùng để kiểm những bước đầu; `freiburg1_room` là lựa chọn để thử một cảnh phòng thực. Các tên này đã được nêu trong báo cáo gốc; chưa có kết quả chứng minh nhóm đã tải, xử lý hay tái tạo chúng thành công. [1, mục 12.2]

Dữ liệu phòng giúp nhóm kiểm tra chương trình có xử lý được dữ liệu quan sát thật không. Nó **không chứng minh sản phẩm phù hợp với kho thực tế**, cũng không tự cung cấp một bản mô hình hình học hoàn hảo để chấm mọi chỉ số. Thông tin chiều sâu có thể thiếu hoặc nhiễu; cần ghi rõ phần nào đủ tin để đối chiếu.

Bên cạnh đó, nhóm tự tạo vài bố trí trong nhà trên máy tính: sàn, tường và khoảng 5–10 vật cản đơn giản, đúng phạm vi đã đề xuất. Từ bố trí đó, tạo ảnh, chiều sâu và góc camera làm đầu vào thử nghiệm. Nhóm giữ lại mô hình gốc như **đáp án tham chiếu**, thường gọi là ground truth. Sau khi hệ thống dựng lại cảnh từ ảnh/chiều sâu, có thể so kết quả với bố trí gốc để biết sai ở đâu. [1, mục 12.3–12.4]

Điều quan trọng là chương trình tái tạo không được nhận trực tiếp đáp án này. Nếu sao chép khối vật cản gốc sang kết quả rồi công bố là tái tạo đúng, phép đánh giá không còn ý nghĩa. Việc tạo dữ liệu tổng hợp giúp chủ động có đáp án kỹ thuật, nhưng không thay thế việc kiểm chứng khó khăn thật của người dùng.

Một khu vực thật do nhóm tự khảo sát hoặc một nguồn indoor bổ sung như Replica là hướng sau đó, nếu đủ điều kiện và quyền sử dụng. Không cần mở thêm nhiều dataset trước khi một bộ dữ liệu nhỏ đã chạy xuyên suốt. Đường dẫn dữ liệu kế thừa từ báo cáo gốc được đặt ở cuối tài liệu để tra cứu. [1, mục 12]

### Cần trả lời riêng hai câu hỏi

**Câu hỏi thứ nhất: bản sao có đúng trong phạm vi đã cam kết không?** Để trả lời, phải kiểm hình ảnh, hình dạng, thao tác chỉnh sửa và kết quả mô phỏng. Một chỉ số duy nhất không trả lời được tất cả.

Với hình ảnh, giữ lại một số góc chụp không dùng để tối ưu mô hình. Yêu cầu hệ thống hiển thị cảnh từ các góc đó, rồi so với ảnh gốc. PSNR, SSIM và LPIPS là ba thước đo mức giống nhau theo các cách khác nhau. Người đọc không cần thuộc công thức để hiểu mục đích: **kiểm xem cảnh tái tạo có thể hiện đúng các góc nhìn chưa được dùng để học hay không**. Chúng không nói chiếc kệ có đúng kích thước hoặc có ngăn robot đi xuyên qua hay không. [1, mục 12.4 và 15.2]

Với hình dạng, dùng bề mặt hoặc số đo tham chiếu để so. **Chamfer Distance** trong báo cáo đo khoảng cách giữa hai tập điểm lấy trên bề mặt: kết quả dựng lại và dữ liệu đối chiếu. Khoảng cách thấp hơn thể hiện chúng khớp hơn theo phép đo đó. Tuy nhiên, sai một chi tiết nhỏ ở ngay lối đi vẫn có thể quan trọng dù sai số trung bình thấp, nên phải kiểm thêm kích thước và các vật cản liên quan trực tiếp tới bài thử. [1, mục 15.3]

Với chỉnh sửa, yêu cầu người dùng chọn và di chuyển một vật thể rồi kiểm cả hình ảnh, dữ liệu va chạm và phiên bản. Với mô phỏng, kiểm riêng những chỗ có vật cản, chỗ còn trống và đường robot đi. Mọi kết quả phải đi kèm phạm vi: kiểm scene nào, phần nào của scene, với robot nào và cấu hình nào. Không suy rộng một lần thử thành lời bảo đảm cho mọi trường hợp.

**Câu hỏi thứ hai: dùng ứng dụng có giảm tổng công sức không?** Đây mới là câu hỏi quyết định sản phẩm có đáng dùng. Một pipeline đạt chỉ số hình ảnh cao nhưng khiến người dùng sửa cả buổi chưa giải quyết được mục tiêu đề tài.

Nhóm cần cho người tham gia làm các nhiệm vụ tương đương bằng quy trình họ đang dùng và bằng ứng dụng. Ba nhiệm vụ đề xuất là dựng một cảnh lần đầu, thay đổi vị trí một vật cản, và sửa một lỗi đã cài sẵn. Đối chứng phải được dùng công cụ hợp lý: nếu người dùng đã có bản vẽ CAD, không bắt họ bỏ bản vẽ để tự dựng lại từ đầu nhằm làm ứng dụng trông vượt trội. [1, mục 14]

Đồng hồ phải ghi tổng thời gian người dựng, người sửa và người duyệt thực sự thao tác. Tách riêng thời gian máy chạy và thời gian chờ bàn giao. Nếu một người tiết kiệm được thời gian nhưng chuyển việc sang người khác, hoặc giảm thao tác nhưng phải đợi GPU quá lâu, báo cáo phải thể hiện cả hai mặt. Cũng phải ghi các nhiệm vụ không hoàn thành, không chỉ lấy những lần chạy tốt nhất.

### Những kết quả nào mới được coi là đạt?

Mục tiêu năng suất được giữ từ báo cáo gốc là **giảm ít nhất 50% tổng thời gian thao tác**, có tính phần kiểm và sửa lại, so với quy trình đối chứng phù hợp. Đây là mục tiêu cần đo, không phải kết quả đã đạt. Trước khi thử, nhóm và người duyệt phải thống nhất cách đo và khóa tiêu chuẩn; không đổi tiêu chuẩn sau khi thấy kết quả. [1, mục 15.6]

| Cần chứng minh | Cách hiểu kết quả |
|---|---|
| **Đúng dữ liệu** | Hình ảnh đủ khớp ở góc nhìn giữ lại; kích thước và hình dạng đạt mức sai số đã thống nhất. Thiếu dữ liệu phải báo thiếu. |
| **Sửa cảnh không làm lệch dữ liệu** | Chỉnh đúng vật thể; hình ảnh và dữ liệu va chạm thay đổi đồng bộ; kết quả duyệt cũ hết hiệu lực sau thay đổi. |
| **Dùng được cho bài thử đã định** | Cảnh mở được, vật cản/lối đi không bị mô tả sai trong bộ kiểm; robot được thử với cấu hình và phạm vi công bố. |
| **Thực sự bớt công** | Tổng thời gian chuẩn bị, sửa và duyệt giảm; chi phí máy chạy và thời gian chờ không bị giấu. |
| **Có kiểm soát** | Người thật duyệt phiên bản; agent không tự bịa bằng chứng hoặc mở quyền; không điều khiển robot thật. |

Các ngưỡng kỹ thuật cụ thể được giữ ở Phụ lục A, thay vì để chúng làm đứt mạch giải thích. Chỉ số đạt trên vài cảnh vẫn là bằng chứng thử nghiệm giới hạn, chưa đủ để khẳng định sản phẩm phù hợp mọi kho hoặc khách hàng.

### Làm sao biết khó khăn của người dùng là thật?

Trước khi đầu tư toàn bộ sáu tuần, nhóm cần tìm 3–5 người từng chuẩn bị hoặc nhận bàn giao môi trường thử robot, theo kế hoạch trong bản gốc. Hỏi về lần làm gần nhất, dữ liệu họ đã dùng, thao tác nào phải làm lại và một trường hợp bản sao bị trả về. Nếu được phép, quan sát một nhiệm vụ thật hoặc xem các tệp đã được làm sạch thông tin nhạy cảm.

Câu hỏi quan trọng không chỉ là “anh/chị có thích ứng dụng này không?”, mà là “quy trình hiện tại đã giải quyết việc gì, còn bước nào tốn công, và kết quả thế nào thì anh/chị chấp nhận?”. Nếu họ chỉ cần bản đồ 2D thể hiện ô trống/vật cản, hoặc đã có mô hình thiết kế đủ dùng, dựng thêm 3DGS có thể là chi phí thừa. Đây là khả năng cần chấp nhận, không phải điều nên che đi để bảo vệ ý tưởng. [1, mục 2.3 và 5]

## 6. Trong sáu tuần, nhóm bốn người hoàn thành theo hướng nào?

Mục tiêu không phải xây mọi phần riêng lẻ rồi ghép vào cuối khóa. Ngay tuần đầu cần có một chuỗi nhỏ chạy được: đưa một môi trường đơn giản vào phần mềm mô phỏng, kiểm một vật cản và hiển thị trạng thái công việc. Điều này phát hiện sớm vấn đề dữ liệu, máy GPU hoặc phần mềm không tương thích. [1, mục 17]

| Tuần | Kết quả cần nhìn thấy được |
|---|---|
| **1** | Bắt đầu gặp người dùng; đọc được dữ liệu indoor; đưa một cảnh hình học đơn giản vào Isaac Sim và chạy một phép kiểm vật cản. Giao diện và backend nhận được công việc. |
| **2** | Tạo được hình ảnh 3D và hình dạng có kích thước; giữ lại góc chụp để đánh giá; ghi thời gian của một nhiệm vụ đối chứng. |
| **3** | Người dùng chọn và sửa được một số vật thể; di chuyển vật thể làm phần hình ảnh và phần va chạm đổi cùng nhau; có lưu phiên bản. |
| **4** | Xuất được cảnh, chạy các phép kiểm trong mô phỏng và có luồng người kiểm duyệt. Công việc đi từ đầu vào đến đầu ra, không còn chỉ là các notebook riêng. |
| **5** | Thêm trợ lý chẩn đoán có giới hạn; so với cùng hệ thống không có agent; thử các nhiệm vụ và đo công sức người tham gia. |
| **6** | Không thêm tính năng mới; chạy bộ đánh giá đã khóa, sửa lỗi, triển khai web, hoàn thiện dữ liệu mẫu, hướng dẫn và video demo. |

Một người phụ trách dữ liệu và dựng hình ảnh; một người phụ trách hình dạng và liên kết vật thể; một người phụ trách backend, tác vụ nền, quyền và agent; người còn lại phụ trách giao diện và nối phần mềm mô phỏng. Đây là phân công đầu mối, không phải bốn phần cô lập: người làm hình dạng phải cùng người làm giao diện và mô phỏng kiểm ngay việc di chuyển một vật thể. [1, mục 17.1]

**Ưu tiên giữ lại** là kích thước đúng, vật cản kiểm được, chỉnh sửa đồng bộ, phiên bản rõ và người duyệt có bằng chứng. Khi chậm tiến độ, cắt giao diện chat, nhiều loại cảm biến, nhiều robot, tự nhận diện mọi loại vật thể hoặc hiển thị Gaussian trực tiếp trong simulator. Không cắt phần kiểm tra rồi tiếp tục gọi sản phẩm là môi trường mô phỏng đã sẵn sàng sử dụng.

Nếu hết tuần 1 vẫn chưa có máy và phần mềm chạy được phép thử nhỏ, chưa nên hứa hoàn thành toàn bộ phiên bản đề xuất. Nếu hết tuần 4 vẫn chưa xuất được cảnh qua bộ kiểm, phải giảm phạm vi và thông báo lại với mentor/BTC. Mức cơ bản RAV-01 vẫn có thể là phương án bàn giao, nhưng phải nói đúng những gì đã và chưa làm được. [1, mục 17.3]

## 7. Kết luận: ứng dụng này đáng làm trong điều kiện nào?

**RAV-01 đáng thử, nhưng chưa có đủ bằng chứng để nói kỹ sư chắc chắn sẽ cần dùng.** Điểm mạnh của hướng này là có thể kiểm tra cả chất lượng kỹ thuật lẫn công sức con người trên một công việc cụ thể. Nhóm không phải tự chế tạo robot để bắt đầu, và nhiều thuật toán nền đã được dự kiến tái sử dụng. [1, mục 19–20]

Điểm khó không chỉ là làm ra hình ảnh 3D. Khó ở việc hình ảnh, hình dạng, vật thể chỉnh sửa và kết quả thử cùng phản ánh một phiên bản môi trường. Nếu liên kết đó kém, sản phẩm chỉ chuyển công việc từ “dựng thủ công” sang “sửa đầu ra AI”, chưa chắc giúp được ai.

Các công cụ tái tạo và dựng môi trường đã xuất hiện trong phần nghiên cứu của báo cáo gốc. Do đó, không nên giới thiệu đề tài bằng câu “chưa ai biến ảnh thành mô phỏng”. Câu hỏi có giá trị hơn là: **với đúng nhóm người dùng và đúng bài thử, hệ thống này có giảm các bước chuẩn bị, sửa và bàn giao so với cách họ đang làm không?** Khả năng trả phí chỉ là giả thuyết cho đến khi có người dùng và kết quả thử chứng minh. [1, mục 6 và 19]

Khách hàng tiềm năng được đề xuất là đội xử lý nhiều khu vực hoặc nhiều lần đổi bố trí. Họ có thể dùng khi có nơi triển khai mới, cập nhật vật cản hoặc kiểm lại một bản sao bị lỗi. Không cần ép thành ứng dụng dùng mỗi ngày: nếu công việc phát sinh theo dự án, việc trả phí theo khu vực/dự án có thể đáng thử hơn thuê bao tháng. Quan trọng là mỗi lần dùng phải tạo lợi ích đủ rõ để họ tự chọn dùng tiếp, không phải bị giữ lại vì không xuất được dữ liệu.

Định nghĩa ngắn gọn của bài toán sau khi thu hẹp là:

> **Kỹ sư chuẩn bị môi trường thử robot cần biến dữ liệu khảo sát của một khu vực trong nhà thành bản sao có kích thước, vật cản và kết quả kiểm tra rõ ràng với ít công sức sửa lại hơn. Real2Sim Workspace hỗ trợ quá trình đó; kỹ sư vẫn chọn mục đích thử, xác nhận chỗ chưa chắc chắn và duyệt kết quả cuối.**

Quyết định giữ từ bản gốc là **bắt đầu khảo sát và thử khả thi; chỉ tiếp tục pilot khi có dữ liệu phù hợp, môi trường tính toán chạy được, người kiểm và phạm vi được xác nhận**. Chưa dùng kết quả này làm căn cứ tự động triển khai robot thật. Nếu quy trình hiện có nhanh hơn, nếu người dùng không cần phần hình ảnh 3D, hoặc nếu thời gian sửa/duyệt không giảm, phải thu hẹp hay đổi hướng thay vì thêm nhiều AI hơn. [1, mục 20]

Sản phẩm chỉ có ý nghĩa khi người dùng hoàn thành đúng công việc với ít công sức hơn và biết rõ giới hạn của kết quả. Một cảnh đẹp, một nút tự động hoặc một bản demo robot chạy được chưa đủ để kết luận điều đó.

## Phụ lục A. Tiêu chí nghiệm thu để tra cứu khi triển khai

**Đây là các mục tiêu pilot đã có trong báo cáo gốc, không phải kết quả thực nghiệm hay ngưỡng bắt buộc do BTC ban hành.** Người kiểm cần xác nhận sai số phù hợp với bài thử và khóa cách đánh giá trước khi chạy dữ liệu kiểm tra. Không được thấy kết quả chưa đạt rồi hạ ngưỡng để cho qua. [1, mục 15.6]

| Nhóm kiểm tra | Mục tiêu và cách sử dụng |
|---|---|
| **Năng suất** | Trung vị mức giảm tổng phút thao tác đạt ít nhất 50% so với đối chứng phù hợp; tính cả người dựng, người sửa và người duyệt. Báo riêng thời gian chờ, máy chạy và nhiệm vụ thất bại. |
| **Hình ảnh** | Ngưỡng khởi điểm trên các góc nhìn giữ lại: PSNR ≥25 dB, SSIM ≥0,85, LPIPS ≤0,25. Chúng kiểm mức giống ảnh, không thay kiểm hình dạng và vật cản. |
| **Hình dạng** | Trên vùng dữ liệu tổng hợp được đánh giá: Chamfer đối xứng trung bình ≤0,05 m; phân vị 95 của sai số bề mặt ≤0,10 m; sai số tỉ lệ ≤2% trên đoạn đo đối chiếu. Công bố phép đo và vùng so sánh. |
| **Vật cản và vùng chưa biết** | Không có lỗi thiếu khối va chạm quan trọng trong bộ kiểm đã khóa; vùng chưa được quan sát không tự chuyển thành vùng trống. Vẫn kiểm cả trường hợp dựng khối quá lớn làm chặn nhầm lối đi. |
| **Chỉnh sửa** | Toàn bộ thao tác trong bộ kiểm phải sửa đúng vật thể, đồng bộ hình ảnh với phần va chạm, tạo phiên bản và hủy hiệu lực kết quả kiểm/duyệt cũ khi có thay đổi liên quan. |
| **Xuất cảnh** | Toàn bộ cảnh thử đã duyệt phải mở được trên môi trường phần mềm mục tiêu, tìm đủ tệp liên quan và giữ đúng đơn vị. Việc mở được file chưa chứng minh các vật cản đúng. |
| **Robot chạy thử** | Ít nhất 90% lượt trên các đường đã xác nhận khả thi tới được đích; không đi xuyên vật cản. Đường bị chặn phải có kết luận phù hợp dữ liệu đối chiếu. Lỗi điều khiển robot phải phân biệt với lỗi môi trường. |
| **Tương tác** | Mục tiêu hiển thị ≥20 khung hình/giây ở 1280×720 trên máy công bố; 95% phản hồi chỉnh sửa không quá 1 giây, không tính tải lần đầu. Báo riêng với tốc độ mô phỏng. |
| **Agent** | Ít nhất 90% tình huống kiểm lỗi được đưa đúng hướng sửa hoặc chuyển đúng cho con người theo bảng chấm đã khóa. Không chấp nhận bằng chứng bịa. Cần so với quy trình không có agent. |
| **Quyền và dữ liệu** | Mọi bản phát hành có người duyệt; không lệnh điều khiển robot thật; không chia sẻ dữ liệu trái phép trong bộ thử. Các con số 0 lỗi không phải bảo đảm tuyệt đối ngoài phạm vi đã kiểm. |

**Thiết kế bộ thử đã đề xuất:** một bố trí tổng hợp để phát triển; hai bố trí khác giữ lại để đánh giá; một cảnh indoor công khai để kiểm với dữ liệu thật. Mỗi bố trí đánh giá có 20 phép kiểm vật cản; bộ đường thử có cả đường đi được và bị chặn, cùng các lần chạy lặp. Kiểm thêm ít nhất 20 quan sát vật thể/vùng ảnh do người kiểm xác nhận. Đây là kế hoạch, chưa phải dữ liệu đã tạo. [1, mục 12.3 và 15.7]

**Cách tránh tự chấm theo đáp án đã nhìn thấy:** giữ ảnh kiểm tra và mô hình hình học gốc ở phần đánh giá; không dùng chúng để chọn tham số tối ưu. 3DGS vẫn được học từ một phần ảnh của từng cảnh, nhưng ảnh giữ lại không được đưa vào quá trình đó. Với dữ liệu thật, phần hình dạng dùng làm đối chiếu phải được phân biệt với chính dữ liệu đã dùng để dựng. Không có nguồn đối chiếu độc lập thì nói rõ chưa đo được, không ghi số thay thế. [1, mục 12.4]

**Ba bài thử sản phẩm:** tạo cảnh lần đầu; thay đổi một vật cản; sửa một lỗi đã cài sẵn. Cho phép người tham gia dùng công cụ hiện có hợp lý, đảo thứ tự những nhiệm vụ tương đương để giảm ảnh hưởng do đã quen bài, và lưu cả thời gian sửa của người duyệt. Thử nội bộ với bốn thành viên không được gọi là kết quả của khách hàng chuyên nghiệp. [1, mục 14]

## Phụ lục B. Đối chiếu với cấu trúc báo cáo và yêu cầu khóa học

### Problem Statement: sáu thông tin cần có

| Thành phần | Nội dung của đề tài đã thu hẹp |
|---|---|
| **Ai gặp vấn đề?** | Kỹ sư chuẩn bị môi trường mô phỏng cho đội robot di động; người kiểm/nhận bàn giao cũng chịu phần công sức liên quan. |
| **Họ đang làm gì?** | Nhận yêu cầu, thu dữ liệu, dựng bản sao, xác nhận kích thước/vật cản, đưa vào mô phỏng, kiểm tra, sửa và bàn giao. |
| **Vướng ở đâu?** | Làm cho dữ liệu quan sát trở thành môi trường dùng được; giữ hình ảnh và hình dạng va chạm khớp nhau; kiểm và sửa sau mỗi thay đổi. |
| **Ảnh hưởng gì?** | Tốn công chuẩn bị, sửa và duyệt; có thể kéo dài thời gian bắt đầu bài thử. Mức tác động thực tế chưa được đo. |
| **Thành công được đo thế nào?** | Giảm tổng công sức theo mục tiêu pilot, đồng thời đạt các kiểm tra hình ảnh, hình dạng, chỉnh sửa và mô phỏng đã thống nhất. |
| **Giới hạn là gì?** | Một vùng indoor tĩnh, một cấu hình robot mẫu, chỉ trong mô phỏng; con người xác nhận thông tin thiếu và duyệt phiên bản. |

Ở mức v0, bài toán là giảm công sức chuẩn bị bản sao có thể kiểm tra. V1 làm rõ hơn cách can thiệp: dữ liệu có kích thước tham chiếu, hai loại biểu diễn liên kết, công cụ kiểm tra độc lập và một agent chỉ hỗ trợ chẩn đoán. Đây là bước làm rõ thiết kế trong báo cáo gốc, không phải kết quả của một vòng phỏng vấn đã diễn ra. [1, mục 4 và 7.4]

### Phần giữ lại và phần hoãn của RAV-01

Giữ mục tiêu cơ bản: web dựng ít nhất một cảnh từ dữ liệu công khai, xem xoay/zoom, bật/tắt vật thể, ít nhất hai vai trò, báo cáo PSNR/SSIM/Chamfer và người duyệt trước khi phát hành. Ràng buộc gốc còn yêu cầu LPIPS, hiệu năng và dữ liệu được ẩn danh trước xử lý. [1, phụ lục A; 2]

Nâng cao có chọn lọc: chỉnh một số vật thể tĩnh, xuất cảnh sang Isaac Sim và chạy một bài thử giới hạn, đo trên nhiều cảnh nhỏ. Hoãn chèn tác nhân động, đổi thời tiết và tái hiện giao thông. Trong đề gốc, “agent động” là đối tượng chuyển động trong cảnh mô phỏng; không nên nhầm với “agent AI” hỗ trợ chẩn đoán trong ứng dụng. Phạm vi điều chỉnh cần mentor/BTC xác nhận. [1, mục 18.3 và phụ lục A]

### Năng lực thể hiện qua sản phẩm

| Năng lực / PLO | Bằng chứng nhóm cần tạo |
|---|---|
| **1. Kiến trúc agent** | Một tình huống agent chọn công cụ kiểm tra, lưu trạng thái và chuyển người khi thiếu căn cứ. |
| **2. Nhiều agent khi cần** | Giải thích vì sao một agent đủ cho phiên bản đầu; chỉ tách vai nếu lợi ích được thể hiện. |
| **3. Truy xuất tài liệu khi cần** | Khi trợ lý tra hướng dẫn hoặc lỗi cũ, trả đúng tài liệu/phiên bản và chỉ rõ bằng chứng; có bộ câu hỏi để kiểm. |
| **4. Phân tích giá trị** | Người dùng cụ thể, khó khăn được xác nhận, quy trình trước/sau và số liệu công sức. |
| **5. Triển khai và vận hành** | Web truy cập được, tác vụ nền chạy, có trạng thái lỗi, tiếp tục công việc và số liệu thời gian/chi phí. |
| **6. An toàn và kiểm soát** | Dữ liệu hợp lệ, phân quyền, người duyệt, công cụ giới hạn, không robot thật. |
| **7. Đánh giá và tối ưu** | Bộ dữ liệu và phép đo được khóa, kết quả thật, trường hợp thất bại và cách cải tiến. |
| **8. Làm việc nhóm và AI coding** | Phân công, kiểm tra mã, lịch sử review, quyết định thiết kế và đóng góp thực của từng thành viên. |

Quy định chung còn yêu cầu demo chính và demo lỗi, mã nguồn, dữ liệu mẫu được phép, hướng dẫn sử dụng, tài khoản demo, kiến trúc và các kết quả đánh giá. Bản báo cáo là kế hoạch để làm ra những đầu ra đó, không thay thế sản phẩm đã chạy. Phần scan cá nhân, pitch/challenge và reflection phải được bổ sung từ trải nghiệm thật của học viên theo worksheet, không tạo biên bản hoặc thành tích chưa có. [2–5]

### Nguồn của bản diễn giải

**[1]** `RAV01_Real2Sim_Problem_Deep_Dive_Report.md`, phiên bản 1.0 ngày 16/09/2026. Nguồn chính cho phạm vi, quyết định thiết kế, kế hoạch dữ liệu, phép đo, ngưỡng nghiệm thu và giới hạn. Các ví dụ góc kho/kiện hàng trong bản này là tình huống minh họa cho thiết kế đó, không phải evidence khách hàng.

**[2]** `AI20K_Ngan_hang_de_Khoa_4.xlsx`: quy định chung, PLO và đề RAV-01. Nội dung RAV-01 cũng được chép trong Phụ lục A của nguồn [1].

**[3]** `01-worksheet.md`: bốn lăng kính, vấn đề trước giải pháp, quy trình, đo lường, giới hạn và quyết định tiếp tục/dừng.

**[4]** `02-deliverable-example.md`: cách đi từ khó khăn cụ thể tới quy trình trước/sau và kết quả phải đo.

**[5]** `02-deep-dive-report.md`: cách trình bày Problem Statement, ranh giới con người, thử nghiệm và tiêu chí nghiệm thu.

**Đường dẫn dữ liệu đã được dẫn trong báo cáo gốc:** [TUM RGB-D — tải dữ liệu](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/download), [TUM RGB-D — định dạng tệp](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/file_formats). Khi triển khai, nhóm cần kiểm quyền sử dụng, định dạng và dữ liệu thực tải; chưa có kết quả chạy RAV-01 được công bố trong báo cáo này.
