# Định vị lại Real2Sim Studio: Từ một bài demo 3D thành sản phẩm giải quyết vấn đề thực tế

Tôi nghĩ dự án của team có tiềm năng, nhưng vấn đề hiện nay là team đang mô tả công nghệ mà mình xây dựng, thay vì mô tả một công việc cụ thể mà người dùng đang gặp khó khăn khi thực hiện.

Đây là lý do cả hai cách pitching trước đều chưa đủ thuyết phục:

- “Chuyển video nhà kho thành scene 3D” mô tả đầu vào và đầu ra, nhưng chưa giải thích tại sao khách hàng cần scene đó và họ thiệt hại gì nếu không có nó.
- “Giúp mọi người lưu lại kỷ niệm hoặc căn phòng dưới dạng 3D” dễ hiểu hơn, nhưng chưa chứng minh người dùng có nhu cầu đủ lớn, đủ thường xuyên, hoặc đủ cấp thiết để trả tiền.

Tôi đề xuất không chuyển Real2Sim thành một ứng dụng lưu giữ kỷ niệm, cũng không cố giữ nhà kho làm domain duy nhất khi dữ liệu hiện tại không hỗ trợ tốt.

Thay vào đó, hãy giữ robot simulation làm thị trường mục tiêu, nhưng định vị lại sản phẩm thành:

> Real2Sim Studio giúp các nhóm phát triển robot tạo nhanh một môi trường thử nghiệm mô phỏng từ video quay nơi robot dự kiến hoạt động. Họ có thể thay đổi cách bố trí đồ vật và kiểm tra những tình huống khác nhau trước khi thử nghiệm trên robot thật.

Điểm mạnh của định vị này là bạn không còn phải chứng minh rằng sản phẩm chỉ dùng được trong nhà kho. Một căn phòng, văn phòng, hành lang hay khu vực lưu trữ đều có thể là một môi trường thử nghiệm hợp lệ.

Quan trọng hơn, giá trị không nằm ở việc tạo ra mô hình 3D, mà nằm ở việc giúp kỹ sư thử nghiệm những thay đổi trong thế giới thực mà chưa cần thực hiện chúng ngoài đời.

Đó cũng là nền tảng để phát triển ý tưởng mà bạn gọi là “trí tưởng tượng cho robot”. Nhưng tôi sẽ tách rõ đâu là sản phẩm có thể chứng minh ngay và đâu là tầm nhìn dài hạn.

## 1. Bài toán này có thật không, hay team đang tự nghĩ ra nhu cầu?

Có bằng chứng khá rõ rằng chuẩn bị môi trường 3D để thử nghiệm robot là một nhu cầu thật.

Năm 2025, NVIDIA đã công bố quy trình sử dụng bản sao số của nhà máy và kho hàng để mô phỏng hoạt động robot trước khi triển khai ngoài thực tế. Đến tháng 9/2026, NVIDIA tiếp tục mô tả việc chuẩn bị scene cho simulation là công việc nhiều bước và dễ sai: phải gán nhãn vật thể, tạo hình học va chạm, thiết lập thuộc tính vật lý và kiểm tra khả năng xuất sang USD.

Nhưng có một phát hiện rất quan trọng:

NVIDIA đã có công cụ chuyển ảnh chụp bằng điện thoại thành scene 3D trong Isaac Sim từ năm 2025. Quy trình Omniverse NuRec dùng COLMAP và Gaussian reconstruction, sau đó đưa dữ liệu vào Isaac Sim. NVIDIA còn phát triển các công cụ bổ trợ để tách hoặc loại vật thể khỏi scene.

Vậy nên:

Không thể lấy “video/ảnh → 3D → Isaac Sim” làm lợi thế cạnh tranh duy nhất của Real2Sim Studio.

Cũng không thể tuyên bố không có sản phẩm nào làm việc này. Polycam đã hỗ trợ dựng và chỉnh sửa Gaussian splats từ ảnh/video; Scaniverse cũng cung cấp dữ liệu 3D và mesh phục vụ các ứng dụng không gian, kể cả robotics.

Điều đó không làm mất giá trị của dự án. Nó chỉ giúp xác định chính xác hơn phần nào của quy trình đáng để team tập trung giải quyết.

### Điểm cần tập trung: Từ mô hình 3D nhìn được đến môi trường thử nghiệm dùng được

Hãy tưởng tượng một kỹ sư chuẩn bị cho robot giao hàng chạy trong một văn phòng mới.

CÔNG VIỆC HIỆN TẠI

Robot sắp hoạt động ở địa điểm mới

Kỹ sư cần có môi trường mô phỏng gần giống nơi robot thực sự sẽ chạy.

Vấn đề

Có video hoặc ảnh hiện trường không đồng nghĩa với việc đã có một mô hình đủ thông tin để robot nhận biết vật cản, tránh va chạm và thử các cách bố trí khác nhau.

CÔNG VIỆC PHẢI LÀM THÊM

Dựng hoặc nhập mô hình, căn chỉnh kích thước, tách vật thể, tạo va chạm, sửa lỗi và thiết lập scene trong simulator.

Cơ hội cho Real2Sim Studio

Hỗ trợ tự động hóa những bước chuẩn bị đó, cho phép kỹ sư kiểm tra và sửa kết quả, rồi đưa môi trường vào mô phỏng nhanh hơn.

Đó là một pain point cụ thể hơn rất nhiều so với “dựng 3D tốn thời gian”.

Nó cũng giải thích được vì sao team phải nghiên cứu object segmentation, metric scale, collision, scene editing và Isaac Sim: tất cả những phần đó đều phục vụ cùng một công việc của người dùng.

Tuy nhiên, các tài liệu ngành mới xác nhận có nhu cầu đối với loại công việc này. Chúng chưa chứng minh nhóm khách hàng mục tiêu sẽ chọn hoặc trả tiền cho sản phẩm của team. Phần đó vẫn cần phỏng vấn và đo lường.

## 2. Chọn đúng người dùng: Đừng bắt đầu bằng “tất cả những ai cần 3D”

Tôi đề xuất so sánh bốn hướng sản phẩm như sau:

| Hướng                                                      | Pain point                                                                    | Phù hợp pipeline                                  | Đánh giá                            |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------- |
| A. Dựng kho 3D cho kỹ sư robot                             | Tốn công tạo môi trường thử nghiệm sát nhà kho thực tế                        | Cao, nhưng thiếu dữ liệu phù hợp                  | Giữ làm ứng dụng mở rộng            |
| B. Tạo môi trường thử nghiệm cho robot hoạt động trong nhà | Mỗi địa điểm triển khai cần kiểm tra không gian, vật cản và cách bố trí riêng | Rất cao                                           | Nên chọn làm trọng tâm              |
| C. Chuyển video thành 3D cho người không biết dựng hình    | Muốn có mô hình 3D dễ dàng                                                    | Cao về kỹ thuật, nhưng khác biệt sản phẩm chưa rõ | Không nên chọn làm trọng tâm        |
| D. Lưu giữ kỷ niệm, căn phòng dưới dạng 3D                 | Muốn lưu giữ và khám phá không gian đã qua                                    | Phù hợp phần 3DGS, nhưng ít cần collision/Isaac   | Không phù hợp với sản phẩm hiện tại |

Đây là đánh giá chiến lược dựa trên khả năng của team và các sản phẩm trên thị trường, chưa phải kết quả nghiên cứu khách hàng.

### Nhóm khách hàng mục tiêu nên chọn

[AI vs Junior developer](https://images.openai.com/static-rsc-4/tcIAZDGLL3Mm3A4YFhyz3ZONssueNZ1g8D_E9HgNVtkn7FZwLBCCjdMOu-AL6gKALX_StoJkw9fONdbBcmXMs7AE7mZ-QAUvEMUqjvwBXyBiQMWJjo_nSa0RKRzMbQXr0pWE4lEpuwqFi85qxxLxZUlYEgYBubpMhEnbe3a2P0A?purpose=inline)

## Kỹ sư tích hợp robot di động trong nhà

Robotics Integration Engineer / Simulation Engineer

Công việc của họ: Đưa robot có khả năng tự di chuyển vào một không gian thực tế như văn phòng, hành lang, bệnh viện hoặc nhà kho.

Khó khăn cần khảo sát: Mỗi địa điểm có kích thước và vật cản khác nhau. Trước khi thử robot thực, họ có thể phải chuẩn bị một mô hình môi trường mới, căn chỉnh nó và kiểm tra các tình huống có thể xảy ra.

Người có thể quyết định mua: Trưởng nhóm phát triển robot, quản lý tích hợp hệ thống hoặc doanh nghiệp cung cấp giải pháp robot cho nhiều khách hàng.

Tôi không chọn người vận hành kho làm người dùng chính của MVP, bởi người đó có thể biết mình muốn robot làm gì nhưng thường không trực tiếp xây dựng môi trường trong Isaac Sim.

Tệp người dùng ban đầu không cần phải là hàng triệu người. Với một sản phẩm B2B chuyên môn, điều quan trọng hơn là một nhóm khách hàng có vấn đề xảy ra thường xuyên và đủ tốn kém để họ muốn trả tiền giải quyết.

Quy mô thị trường có thể mở rộng sau này, nhưng chưa nên đưa ra con số TAM hoặc doanh thu khi chưa khảo sát.

## 3. Một câu chuyện thực tế để thuyết phục ban giám khảo

Tôi đề xuất dùng robot giao nhận nội bộ trong văn phòng hoặc phòng thí nghiệm làm câu chuyện demo đầu tiên.

[LuckiBot Pro AutoDoor | Roboter mit Fachsystem](https://images.openai.com/static-rsc-4/VYroMvu6pbjs-WQs8BrdmC12LHN45qdjyE5N5obVehVcDOm2WWohxUicbb3o3LSGxpspv2sYGbzIF0qZWkVwxMl0PaHvDbiewBUDqzIHK9xH8YNi_tRoH_SlShbzGjSJ9KmJKca1UVWKhlQASkhn4osGIBozoNwoZ_6bnvSZmKI?purpose=inline)

[Drift: Simulation based evaluations for 10x faster robot deployments](https://images.openai.com/static-rsc-4/KIgviH4suEp4V6OpbmlZEw_iTrtpMY-WocWelAONtrzEOzZFVLStVTi2DrdKK-M1g2WGy7sbFwPEctWD_2_Vr9EjRBEJRXViGVIwrBEXqN675c-jwLRtqrrSJIm_lGONr7zWyTkmmdmMy0mtgIe9QvevWYvjiMQqngUXp4fIAKM?purpose=inline)

[ROS 2 Powered Digital Twin for Facility Robotics](https://images.openai.com/static-rsc-4/k-s6K4GCwaPinqXF1m5ttX9vw_CGdMzH1vl94N-OtayfgkFcIe7IYCq8AKAqWz0GT-z4x8A2DG5dR45x6BTDfWLhlyfM7QFa_kWkvFu1R_TwWgeOG3Tkgbot5EvMi05yC3Q1YKnG1HTCrjKcq8LQca7xYjy-vIXnfR-tSL8u5i0?purpose=inline)

10

Các hình là minh họa cho kịch bản sản phẩm đề xuất.

### Tình huống

Một công ty sản xuất robot giao hàng muốn đưa robot vào hoạt động tại một tòa nhà văn phòng. Robot cần tự đi từ nơi nhận hàng đến các phòng làm việc.

Khi đến khảo sát, kỹ sư có thể có video quay hành lang và phòng làm việc. Nhưng video đó chưa phải là một môi trường để thử hệ thống điều hướng và va chạm của robot.

Kỹ sư cần trả lời những câu hỏi như:

> Robot có đi qua được khoảng trống giữa bàn và tường không? Nếu đặt thêm một chiếc tủ ở đây, đường đi sẽ thay đổi thế nào? Nếu hành lang bị chắn, robot có tìm được đường khác không?

Họ có thể dựng một môi trường thủ công trong simulator, dùng bản vẽ có sẵn hoặc sử dụng các công cụ quét 3D. Nhưng mỗi cách đều có chi phí chuẩn bị và giới hạn riêng.

Real2Sim Studio được đề xuất để rút ngắn bước chuyển từ dữ liệu khảo sát sang môi trường có thể chỉnh sửa và kiểm tra.

### Cách demo khiến người xem hiểu ngay giá trị

[WeWork Sapir - Daily Office - 6p](https://images.openai.com/static-rsc-4/8b6rd6u4NEcyHoLhRpo8KyEOWja0CiLZndQvXeup-9XaNfxdV8wG2t_RANG0S9IZSPcWl8JWFxafGADpAXfkyYaGgkVK7s5cVLzKPZXTko2_QyIzixxlKa86u3ffBUWhnS3MgjG8kQzugKVf5IAOiJaEoLrfOMFaHkujgVHXa3E?purpose=inline)

Kịch bản A — Lối đi thông thoáng

Robot thử đi từ cửa đến vị trí nhận hàng.

[The Best Virtual Office Space at  Orient Tower  ✔ MatchOffice](https://images.openai.com/static-rsc-4/xl6M1oT5EhHH2RzrzMR-OXoi8-1f2WJxQ0Xd_GSZOMEC_W1MbTiyZ-pJ4kqus2WFV0k5R4BmFrF3HLdFGtTblrJwyRvsznwCu9k_hOv0F6nM5LMoC2Y_CwxBoMMYHG_rG5XbGAYUnbgLOgd4Cg1v33iDg4CyNuVvpSLELA8HHnU?purpose=inline)

Kịch bản B — Thay đổi vị trí bàn

Kỹ sư kéo bàn vào lối đi, sau đó chạy lại cùng bài thử.

Điều giám khảo cần thấy: Cùng một địa điểm, cùng một robot, nhưng hai cách bố trí khác nhau có thể cho kết quả thử nghiệm khác nhau.

Thao tác kéo bàn không phải giá trị cuối cùng. Giá trị là kiểm tra được hệ quả của việc kéo bàn.

Lưu ý rằng đây là kịch bản mục tiêu, không phải một bài kiểm thử Isaac Sim mà team đã hoàn tất. Để biến nó thành bằng chứng, team cần cho một robot chạy thực sự trong hai scene, tốt nhất là dùng cùng một bộ điều khiển.

Điều này khả thi để nghiên cứu thêm vì tài liệu Isaac Sim đã có ví dụ robot Nova Carter kết hợp ROS 2 Nav2 để điều hướng và tránh vật cản trong nhà kho.

## 4. Vậy việc đổi sang Hugging Face có thực sự gây concept drift không?

Có, nếu team vẫn tuyên bố sản phẩm được thiết kế và chứng minh cho nhà kho, nhưng toàn bộ demo lại là phòng khách hoặc phòng bếp mà không giải thích lý do.

Nhưng nếu định vị là công cụ tạo môi trường thử nghiệm cho robot di động trong nhà, thì phòng, hành lang, văn phòng và nhà kho đều thuộc cùng một nhóm bài toán không gian.

Tôi đề xuất phân chia dữ liệu theo mục đích:

| Nguồn dữ liệu                                         | Vai trò nên dùng                                                           | Điều cần lưu ý                                                                                               |
| ----------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Hugging Face `room`, `kitchen`, `playroom`            | Kiểm thử tách vật thể, chỉnh sửa, collision, xuất scene                    | Có thể dùng Gaussian dựng sẵn; không được gọi đó là bằng chứng video→3D end-to-end nếu bỏ qua reconstruction |
| Video tự quay tại phòng học, văn phòng hoặc phòng lab | Demo đầu vào thực tế của sản phẩm                                          | Cần quay đủ góc, có quyền ghi hình, đo một vài kích thước thật                                               |
| TUM RGB-D `freiburg1_room`                            | Đối chiếu pose, scale và các bước xử lý hình học                           | Có RGB, depth và quỹ đạo tham chiếu; không nhất thiết tối ưu cho demo hình ảnh đẹp                           |
| Isaac Sim warehouse assets                            | Kiểm thử tính tổng quát sang kho hoặc tạo dữ liệu tổng hợp có ground truth | Không được trình bày video render từ simulator là footage nhà kho thật                                       |

TUM RGB-D cung cấp các chuỗi RGB-D thực cùng dữ liệu tham chiếu, trong đó có `freiburg1_room`.

Đặc biệt, Isaac Sim hiện đã có warehouse scenes và công cụ Synthetic Data Recorder, cho phép ghi RGB từ camera di chuyển trong môi trường mô phỏng. Đây là cách tốt để tạo benchmark nhà kho có hình học gốc dùng đối chiếu, dù không thay thế được kiểm thử từ cảnh thật.

### Kế hoạch dataset tôi chọn cho team

[3d render of modern office and working space](https://images.openai.com/static-rsc-4/HvbCr16f2QTJ3B1ngrp-OhH_JAiaMIkd4to4CNr90ls9nyntcUMSNfOd6DX8pTioa1QG9GhRzI410I7R6eh9usKEqaxe8ux-L-P5yS7TL3_XNH0hJSiKa776HqKBlVGSP7uV7yEQcf1bpZA2dU2fwEMP0Ir7aL52TLPhvQgr-LoFbyLuu57hN2OsZ72q8S8D?purpose=inline)

Demo chính: Room hoặc phòng tự quay

Cho giám khảo xem chuyển từ dữ liệu quan sát sang scene chỉnh sửa được, sau đó kiểm tra va chạm.

[엔비디아 '아이작 ROS' 소프트웨어 최신 업데이트...자율이동로봇 위한 오픈 소스로 도구와 기능 제공 < 플랫폼 < AI Tech < 기사본문 - 인공지능신문](https://images.openai.com/static-rsc-4/wiP4WUoIg57WXpd-BnPK30rTcuZvHejjYafM_5Y2-tGbXAdBCI2iB6HG0N3KONnQZSZIdAdEtWchgvo1RyvuWaV8WiHUzTCi-1ZDAofGCTBL_v72YHSqdQAJFv3bWT6Ie34u_H1pcpiLTFGm0ThQw4R8vCEYen84RiEzMiBgkeQ?purpose=inline)

Benchmark mở rộng: Warehouse

Kiểm tra pipeline có xử lý được các vật như kệ hàng, kiện hàng và lối đi hẹp hay không.

Điều tôi muốn thay đổi là phân biệt dữ liệu dùng để chứng minh năng lực kỹ thuật và dữ liệu dùng để chứng minh một ứng dụng kinh doanh. Chúng không nhất thiết phải là một bộ dữ liệu duy nhất.

## 5. Điều gì khiến Real2Sim Studio đáng dùng thay vì các công cụ hiện có?

Đây là câu hỏi mà mentor hoặc ban giám khảo giỏi rất có thể sẽ hỏi.

Vì các đối thủ hiện nay đã có năng lực đáng kể, tôi không khuyên team trả lời bằng câu “chúng em là công cụ đầu tiên chuyển video thành scene 3D”.

Thay vào đó, hãy định vị theo quy trình làm việc cụ thể:

| Công cụ/nhóm công cụ             | Thế mạnh hiện có                                                                 | Hướng giá trị team cần chứng minh                                                                     |
| -------------------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Polycam, Scaniverse              | Ghi lại không gian dưới dạng 3D, tạo mesh hoặc Gaussian splats                   | Quy trình chuẩn bị và kiểm tra scene cho một bài toán robot cụ thể                                    |
| NVIDIA NuRec + Isaac Sim         | Tái tạo dữ liệu thực, xuất sang simulator; hệ sinh thái có công cụ xử lý asset   | Trải nghiệm chỉnh sửa từng vật, quản lý collision và kiểm tra thay đổi trong một workflow dễ thao tác |
| Công cụ dựng hình/scene thủ công | Linh hoạt, kiểm soát chi tiết cao                                                | Giảm lượng công việc thủ công khi đã có video khảo sát                                                |
| Real2Sim Studio                  | Đã có nền tảng tách Gaussian, review object, Move/Rotate, collider và USD export | Cần chứng minh tính chính xác, thời gian tiết kiệm và hiệu quả của workflow so với các phương án trên |

Đây là giả thuyết về lợi thế sản phẩm, chưa phải lợi thế đã được benchmark.

Thực tế NVIDIA đã có Asset Harvester để tách asset và World Labs Marble cũng cung cấp Gaussian cùng collider mesh để đưa vào Isaac Sim. Do đó, không nên khẳng định đối thủ hoàn toàn thiếu các khả năng này.

Phần team có thể tạo khác biệt là một quy trình phù hợp với người dùng mục tiêu: quay hiện trường → tái tạo → kiểm tra và sửa từng vật → xây dựng các tình huống mới → xuất và kiểm thử.

## 6. “Trí tưởng tượng cho robot” — Có thể là tầm nhìn rất đáng theo đuổi

Tôi thích hướng đặt vấn đề này ở góc độ sản phẩm, nhưng cần định nghĩa chính xác.

Không phải robot tự tưởng tượng ra mọi thứ. Thay vào đó, hệ thống cung cấp khả năng tạo và kiểm tra những phiên bản giả định của môi trường thực tế.

Thế giới mà robot đã quan sát

Video quay một căn phòng tại thời điểm hiện tại

Real2Sim Studio

Tạo scene có cấu trúc, kích thước và hình học va chạm

Tương lai A

Bàn ở vị trí cũ

Tương lai B

Bàn chắn lối đi

Tương lai C

Thêm vật cản mới

Chạy cùng một robot trong các tình huống

So sánh kết quả trước khi thay đổi môi trường thật

Có thể gọi đây là Counterfactual Simulation — mô phỏng tình huống giả định: Nếu thế giới khác đi thì chuyện gì sẽ xảy ra?

Tôi đề xuất chia tầm nhìn thành hai mức.

Sản phẩm gần hạn: Người dùng tự thay đổi môi trường trong Studio, sau đó chạy mô phỏng để kiểm tra.

Tầm nhìn dài hạn: Hệ thống có thể tự đề xuất các kịch bản cần kiểm thử dựa trên nhiệm vụ của robot. Ví dụ, nếu robot phải vận chuyển hàng qua một hành lang, hệ thống tạo nhiều cách sắp xếp vật cản và kiểm tra xem cách nào làm robot thất bại.

Cách phát triển này có cơ sở nghiên cứu: các world models cho Physical AI đang hướng tới việc hiểu, dự đoán và tạo ra những diễn biến có thể xảy ra trong thế giới vật lý.

Nhưng cần tách biệt: Real2Sim Studio hiện tại chưa phải một world model dự đoán tương lai tự động. Nó đang xây dựng lớp môi trường 3D có thể chỉnh sửa và mô phỏng — một nền tảng hữu ích cho hướng đó.

Tôi sẽ sử dụng thông điệp:

> Real2Sim Studio — Tái tạo thế giới thực, thử nghiệm những tình huống chưa xảy ra.

Câu này vừa diễn đạt rõ năng lực hiện tại, vừa mở ra tầm nhìn tương lai.

## 7. Cần chứng minh điều gì để giám khảo thực sự tin?

Không nên chỉ demo Gaussian đẹp, kéo được chiếc bàn và có khung collision. Những điều đó chứng minh thành công kỹ thuật, chưa chứng minh giá trị kinh doanh.

Team cần đo kết quả công việc của người dùng.

| Câu hỏi giám khảo quan tâm                     | Bằng chứng team nên chuẩn bị                                                                |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Có thực sự tiết kiệm thời gian không?          | So sánh thời gian dựng một scene thủ công và thời gian dùng Real2Sim để đạt cùng tiêu chuẩn |
| Môi trường có đủ chính xác để thử robot không? | Đối chiếu khoảng cách đo thật và kích thước scene; kiểm tra vật cản thật/giả                |
| Chỉnh sửa có nhanh không?                      | Đo thời gian Move/Rotate một vật rồi tạo scene có collision đúng, so với sửa thủ công       |
| Có sử dụng được ngoài Studio không?            | Import package thực vào Isaac Sim và chạy một bài thử với robot                             |
| Có áp dụng ngoài một scene demo không?         | Kiểm thử thêm scene khác, ghi lại rõ trường hợp thành công và thất bại                      |

Khi đo thời gian, nên tách thời gian chờ máy xử lý với thời gian kỹ sư phải thao tác. Một pipeline có thể chạy máy khá lâu nhưng vẫn tiết kiệm nhiều thời gian làm việc thủ công; ngược lại cũng có thể xử lý nhanh nhưng tốn nhiều công sửa lỗi.

Ngoài ra, cần giữ các giới hạn kỹ thuật hiện tại trong scope nghiệm thu. Các PR-01 đến PR-04 đã cải thiện rõ browser collision và scene lifecycle, nhưng vẫn còn khả năng lỗi Gaussian membership, collision ownership tại vùng nối bàn–sàn, và chưa có bằng chứng E2E trực tiếp trong Isaac Sim. Chỉ nên nói bài toán được giải quyết ở mức nào sau khi kiểm thử các trường hợp này.

### Một điểm quan trọng về pain point

Đừng giả định kỹ sư luôn phải dựng 3D từ đầu. Một số nhóm đã có CAD, bản đồ SLAM, thư viện asset hoặc các công cụ như NuRec.

Pain point mạnh nhất có thể nằm ở những địa điểm chưa có scene mô phỏng phù hợp, hoặc những lần cần nhanh chóng cập nhật scene theo thay đổi thực tế.

Để chứng minh, tôi khuyên team phỏng vấn khoảng 5–8 người thuộc nhóm phát triển robot, tích hợp robot hoặc giảng viên/nghiên cứu viên robotics. Các câu hỏi cần xoay quanh lần gần nhất họ tạo môi trường thử nghiệm, công cụ đã dùng, công đoạn mất nhiều công nhất, tần suất lặp lại và hệ quả nếu scene không chính xác.

Nếu không tìm được người dùng nào thực sự gặp vấn đề đó thường xuyên, cần điều chỉnh persona thay vì cố bảo vệ giả định ban đầu.

## 8. Cách pitching tôi đề xuất với mentor và ban giám khảo

Đây là cách tôi sẽ kể câu chuyện để cả người không làm 3D cũng hiểu.

> Hãy tưởng tượng một công ty muốn đưa robot giao hàng tự động vào một tòa nhà mới. Trước khi cho robot hoạt động, các kỹ sư cần kiểm tra xem robot có di chuyển được trong không gian đó không, có va chạm với bàn ghế, tường hoặc bị chặn khi cách bố trí thay đổi hay không.
>
> Họ có thể sử dụng môi trường mô phỏng, nhưng để có được một môi trường phản ánh đúng địa điểm thực tế, họ còn phải chuẩn bị mô hình, căn chỉnh kích thước và thiết lập các vật thể để robot tương tác.
>
> Real2Sim Studio được phát triển để rút ngắn công việc đó. Từ dữ liệu quay không gian thật, hệ thống hỗ trợ dựng lại thành một môi trường 3D, cho phép người dùng chọn và thay đổi từng vật thể, đồng thời chuẩn bị hình học va chạm để đưa vào phần mềm mô phỏng robot.
>
> Ví dụ, thay vì phải di chuyển một chiếc bàn ngoài đời để thử xem robot còn đi qua được hay không, kỹ sư có thể thay đổi nó trong môi trường ảo và chạy lại bài thử.
>
> Trước mắt, team tập trung xây dựng và kiểm chứng quy trình này trên các không gian trong nhà. Về lâu dài, chúng em muốn phát triển hệ thống thành một nền tảng giúp robot được thử nghiệm trong nhiều tình huống giả định trước khi gặp chúng ở thế giới thật.

Bản pitching này tránh ba vấn đề: không tuyên bố thị trường chưa ai làm, không dùng quá nhiều thuật ngữ 3D và không hứa rằng sản phẩm hiện tại đã tự động giải quyết hoàn toàn bài toán robot.

## 9. Những quyết định tôi muốn team chốt ngay

| Hạng mục          | Định hướng đề xuất                                                                                                                                                    |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Định vị sản phẩm  | Real2Sim Studio — Công cụ hỗ trợ tạo và chỉnh sửa môi trường mô phỏng cho robot từ dữ liệu quan sát thực tế                                                           |
| Primary persona   | Kỹ sư phát triển hoặc tích hợp robot di động trong các không gian trong nhà, đặc biệt khi chưa có scene phù hợp với địa điểm triển khai                               |
| Use case đầu tiên | Robot giao nhận nội bộ cần kiểm tra đường đi và va chạm khi cách bố trí bàn ghế hoặc vật cản thay đổi                                                                 |
| Demo              | Một không gian Room thực tế → tạo scene → chỉnh sửa vật thể → kiểm tra collision → xuất Isaac Sim → thử cùng một robot trong hai bố trí, khi các bước E2E đã sẵn sàng |
| Tầm nhìn dài hạn  | Một công cụ tạo các tình huống giả định từ môi trường thực, giúp robot được thử nghiệm trước trong nhiều điều kiện khác nhau                                          |

### Kết luận

Tôi không nghĩ vấn đề của Real2Sim Studio là thiếu tính ứng dụng. Những thành phần đang xây dựng — Gaussian reconstruction, tách vật thể, chỉnh sửa, collision và USD export — đều có vai trò hợp lý trong một sản phẩm hỗ trợ mô phỏng robot.

Nhưng sản phẩm không nên được định nghĩa bằng tập hợp những công nghệ đó.

Tôi sẽ giữ nguyên định hướng robotics, mở rộng địa điểm thử nghiệm từ warehouse-only sang indoor environments, chọn đúng một tình huống sử dụng và đo giá trị bằng kết quả kiểm thử robot, thời gian chuẩn bị scene và độ chính xác hình học.

Như vậy, nhà kho trở thành một trong những nơi sản phẩm có thể ứng dụng, không còn là điều kiện quyết định sự tồn tại của sản phẩm. Và dữ liệu Room không nhất thiết là concept drift: nó là bước kiểm chứng một use case trong cùng nhóm môi trường, miễn là bạn diễn đạt rõ điều gì đã được chứng minh.

Thông điệp cần giữ xuyên suốt là:

> “Chúng tôi không chỉ giúp người dùng nhìn lại một không gian dưới dạng 3D. Chúng tôi muốn giúp họ thay đổi không gian đó trong môi trường ảo, thử xem điều gì sẽ xảy ra và giảm bớt công sức thử nghiệm ngoài thực tế.”

Đó là một hướng có bài toán rõ hơn, khách hàng rõ hơn và vẫn giữ được phần lớn giá trị kỹ thuật mà team đã đầu tư.