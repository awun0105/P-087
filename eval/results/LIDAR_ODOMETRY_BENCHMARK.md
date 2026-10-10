# Benchmark: KISS-ICP trên TorWIC (độ trôi quỹ đạo và độ khớp bản đồ)

- **Ngày đo:** 2026-10-10 · **Máy:** laptop Quadro T2000, KISS-ICP chạy bằng **CPU** · **Phiên bản:** `kiss-icp 1.3.0`, hồ sơ mặc định `rec17-default-v1` (`voxel 0.25 m`, tầm 0–80 m)
- **Mã đo:** `eval/pose/lidar_odometry_benchmark.py` · **Số liệu thô:** `eval/results/lidar_odometry_torwic.json`
- **Dữ liệu:** 5 kịch bản TorWIC (`TorWIC_Raw_Scenes`), mỗi chuỗi lấy tối đa 600 scan đầu (giới hạn tổng điểm của sản phẩm là 100 triệu)

> Đây là bản đo **hiện trạng** (baseline). Không có tham số nào được chỉnh, không có bước ghép COLMAP. Chưa phải held-out qualification của AUD-24.S5.

## 1. Câu hỏi và cách đo

**Câu hỏi:** khi người dùng nộp video + scan `.pcd` thô chưa registered (hướng R5/R6), phần LiDAR ước lượng đường đi và dựng bản đồ chính xác tới đâu?

**Hình dung đời thường:** giống vẽ sơ đồ nhà bằng cách đi dọc nhà và đếm bước chân. Có ba thứ cần phân biệt: *đường bạn đã đi*, *sơ đồ bạn vẽ ra*, và *bản vẽ kiến trúc chính thức*. Benchmark kiểm hai việc: đếm bước có đúng không, và sơ đồ cuối có khớp bản vẽ chính thức không.

### 1.1 Bảng đặt tên

| Tên | Là gì | Nguồn |
|---|---|---|
| **A. Quỹ đạo thực** | đường robot thật sự đi | `traj_gt.txt` (có sẵn trong dataset) |
| **B. Quỹ đạo KISS-ICP** | đường phần mềm *đoán* ra từ các scan | KISS-ICP chạy trên `lidar_scans/*.pcd` |
| **C. Bản đồ thực** | bản đồ chuẩn của dataset | `groundtruth_map.ply` |
| **D. Bản đồ ghép bằng A** | các scan đặt đúng chỗ theo đường thực; là **trần** tốt nhất đạt được | tự ghép từ `.pcd` + A |
| **E. Bản đồ ghép bằng B** | các scan đặt theo đường KISS-ICP đoán; là thứ sản phẩm thực sự dựng ra | tự ghép từ `.pcd` + B |

### 1.2 Bảng cái gì so với cái gì

| # | So sánh | Câu hỏi nó trả lời | Chỉ số | Bảng kết quả |
|---|---|---|---|---|
| 1 | **B so với A** | KISS-ICP đoán đường đi có đúng không? | ATE (lệch vị trí), trôi %, RPE (sai mỗi bước) | 2.1 |
| 2 | **D so với C** | Mức tốt nhất có thể đạt được khi đường đi đúng tuyệt đối là bao nhiêu? | khoảng cách điểm → bề mặt chuẩn | 2.2 (cột "trần") |
| 3 | **E so với C** | Bản đồ mà KISS-ICP dựng ra đúng đến đâu? | như trên | 2.2 (cột "KISS-ICP") |
| 4 | **E so với D** | Phần lỗi *do KISS-ICP gây thêm* là bao nhiêu? | hiệu hai cột trên | 2.2 (cột "gây thêm") |

Phép so 1 chỉ dùng A và B, **không đụng `.ply`**. `.ply` chỉ xuất hiện ở các phép so 2 và 3.

### 1.3 Sơ đồ luồng

```
scan .pcd ──► KISS-ICP ──► B (quỹ đạo đoán) ──┐
                                              ├─► ghép scan thành bản đồ ──► E ──┐
scan .pcd ──► A (quỹ đạo thực) ───────────────┤                                 ├─► so với C (.ply)
                                              └─► ghép scan thành bản đồ ──► D ──┘
                                  A ◄── so sánh với B ──► ATE, trôi, RPE
```

### 1.4 Phương pháp thực nghiệm (từng bước)

1. **Chuẩn bị scan.** Đọc từng `.pcd`, bỏ điểm không hợp lệ và điểm sát tâm cảm biến (< 0,5 m). Lấy tối đa 600 scan đầu, tự giảm khi tổng điểm vượt 90% giới hạn sản phẩm (100 triệu).
2. **Chạy KISS-ICP** trong interpreter cô lập (`kiss-icp 1.3.0`, hồ sơ mặc định, CPU) → được B.
3. **Đo quỹ đạo (1).** Căn B vào A bằng một phép xoay + tịnh tiến **chỉ ở pose đầu tiên**; không fit tỉ lệ, không căn cả đường, để sai số cộng dồn vẫn lộ ra. Tính ATE, trôi (% quãng đường) và RPE trên 1 và 10 bước.
4. **Dựng hai bản đồ.** Đặt từng scan (lấy 1/5, cắt tầm 40 m, giảm mẫu voxel 10 cm) theo A để có D và theo B để có E.
5. **Đo bản đồ (2, 3).** Chỉ xét điểm trong 8 m quanh đường đi. Với mỗi điểm, đo khoảng cách tới điểm gần nhất của C; báo trung bình, trung vị, phân vị 95 và % điểm trong 10/20 cm.
6. **Lặp lại trên 5 chuỗi** với cùng tham số (không chỉnh gì), để xem kết quả có ổn định giữa kho/hành lang, thuận/ngược chiều, hai ngày quay.

**Vì sao thiết kế như vậy:**
- Cột D (trần) cần thiết vì bản đồ chuẩn C không hoàn hảo; nếu không có D thì không biết phần lệch là do KISS-ICP hay do chính phép so.
- Căn chỉ ở pose đầu để đánh giá trung thực: căn cả đường sẽ "giấu" sai số trôi.
- Không chỉnh tham số, vì chỉnh trên chính tập đo sẽ cho con số đẹp giả.

## 2. Kết quả

### 2.1 Quỹ đạo (B so với A)

| Kịch bản | Môi trường | Scan | Điểm/scan | Đường đi | Lệch cuối đường | **Trôi** | Sai/bước | Sai/10 bước | Xoay/10 bước |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 01 Aisle_CW | kho | 600 | 84 k | 43,8 m | 0,77 m | **1,76%** | 1,2 cm | 2,5 cm | 0,29° |
| 03 Aisle_CCW | kho, ngược chiều | 600 | 85 k | 45,9 m | 0,97 m | **2,12%** | 1,5 cm | 4,8 cm | 0,27° |
| 05 Aisle_CW lần 2 | kho, ngày khác | 470 | 191 k | 34,1 m | 0,34 m | **0,99%** | 0,7 cm | 1,6 cm | 0,20° |
| 02 Hallway thẳng | văn phòng | 600 | 84 k | 46,7 m | 0,47 m | **1,00%** | 2,3 cm | 4,4 cm | 0,67° |
| 04 Hallway toàn khu | văn phòng | 600 | 94 k | 45,6 m | 0,92 m | **2,01%** | 1,2 cm | 2,5 cm | 0,28° |
| **Trung bình** | | | | | 0,69 m | **1,58%** | 1,4 cm | 3,6 cm | 0,34° |

### 2.2 Bản đồ ghép so với `groundtruth_map.ply` (lệch trung bình, cm)

| Kịch bản | Ghép bằng quỹ đạo **thực** (trần) | Ghép bằng **KISS-ICP** | KISS-ICP gây thêm | Điểm trong 20 cm (thực → KISS) |
|---|---:|---:|---:|---:|
| 01 Aisle_CW | 20,4 | 31,6 | +11,2 | 68,9% → 44,6% |
| 03 Aisle_CCW | 21,1 | 31,5 | +10,4 | 66,6% → 45,7% |
| 05 Aisle_CW lần 2 | 20,7 | 22,4 | **+1,7** | 72,1% → 68,1% |
| 02 Hallway thẳng | 22,6 | 38,2 | +15,6 | 67,7% → 40,6% |
| 04 Hallway toàn khu | 19,8 | 31,6 | +11,8 | 70,6% → 43,3% |

### 2.3 Chi phí

| | Giá trị |
|---|---|
| Thời gian KISS-ICP (600 scan, 84 k điểm) | 22–24 giây (CPU) |
| Thời gian (470 scan, 191 k điểm) | 61 giây |
| Bộ nhớ đỉnh | 0,13–0,18 GB |

## 3. Insight

1. **Trôi ổn định ~1–2% quãng đường trên cả 5 tập** (kho/hành lang, thuận/ngược, hai ngày). Kết quả ở một tập đại diện được cho các tập còn lại; hiện tượng này là đặc tính của phương pháp chứ không phải may rủi của một chuỗi.
2. **Từng bước rất chính xác (1–2 cm, dưới 0,7°), lỗi nằm ở cộng dồn.** Đi càng xa càng lệch; không có cơ chế kéo về (loop closure, IMU, tham chiếu ngoài). Cải thiện hợp lý nhất là thêm thông tin ngoài (COLMAP, R4) chứ không phải chỉnh từng bước.
3. **Lệch cuối đường 0,3–1,0 m không biến thành bản đồ hỏng tương ứng.** Bản đồ chỉ lệch thêm ~10–16 cm so với trần. Khi đường đi đúng tuyệt đối thì lỗi cuối đường là một điểm, còn phần lớn bản đồ nằm ở đoạn lệch ít hơn.
4. **"Trần" ~20 cm là số trung bình bị kéo lên bởi một cái đuôi, không phải sai số đồng đều.** Điều tra trên tập 01 (D so với C, 3,4 triệu điểm):
   - **Không phải lệch khung toàn cục:** ICP cứng 6 bậc tự do chỉ cải thiện 17,3 → 16,9 cm (dịch 2,8 cm, xoay 0,24°).
   - **Không phải độ thưa của `.ply`:** khoảng cách lân cận của chính `.ply` có trung vị 3,8 cm (sàn đo ~2–4 cm).
   - **Là đuôi dài:** trung vị chỉ **9,1 cm**, nhưng 90% = 42 cm, 99% = 106 cm; **7,9% điểm lệch > 50 cm**, bỏ chúng thì trung bình còn 12,1 cm.
   - **Tập trung ở độ cao 0–1,5 m** (41% số điểm, trung bình 21–32 cm, trung vị 14–17 cm), trong khi sàn (< 0 m) chỉ 10 cm, trần/tường cao (> 1,5 m) 9–11 cm. Gần cảm biến (1–5 m) cũng tệ hơn xa (5–10 m): 17,9 so với 11,6 cm.
   - **Giả thuyết (chưa kiểm):** vùng 0–1,5 m là hàng hoá, pallet, kệ thấp và vật di động, có thể đã khác so với lúc dựng `.ply`; ngoài ra có thể là tạp âm ở cận cảnh. Chưa tách được hai nguyên nhân.
   - **Hệ quả cho cách báo cáo:** nên dùng **trung vị và % trong 10/20 cm** làm chỉ số chính, không dùng trung bình.
5. **Scan dày hơn cho kết quả tốt hơn rõ** (tập 05: 191 k điểm, +1,7 cm so với +10–16 cm). Nhưng tập 05 cũng ngắn hơn (34 m) nên **chưa tách được** ảnh hưởng của mật độ và độ dài; cần thí nghiệm riêng.
6. **Hành lang thẳng có sai số mỗi bước cao nhất (2,3 cm, 0,67°)** và bản đồ tệ nhất (+15,6 cm), dù trôi cuối đường thấp. Phù hợp với giả thuyết hành lang thẳng ít đặc trưng dọc trục (chưa kiểm).
7. **Giới hạn của sản phẩm chặt hơn con số trong bảng này.** Script benchmark nâng trần tổng điểm lên 100 triệu (mức tối đa hợp đồng cho phép) để chạy được 600 scan, nhưng hồ sơ mặc định của sản phẩm (`default_lidar_odometry_profile`) dùng **25 triệu**. Với scan 84 nghìn điểm sản phẩm nhận ~**300 scan**, với scan 191 nghìn điểm chỉ ~**130 scan**; vượt thì job bị từ chối. Bộ nhớ đỉnh của KISS-ICP chỉ 0,13–0,18 GB nên giới hạn này là ngưỡng thận trọng, không phải ràng buộc bộ nhớ thực tế.

## 4. Ý nghĩa và ảnh hưởng

| Câu hỏi | Trả lời |
|---|---|
| **Vì sao phải đo?** | Không đo thì chỉ biết "chạy xong, không báo lỗi", không biết kết quả đúng tới đâu. Số đo cho phép nói thật với người dùng và quyết định có nên cấp phép hướng R5/R6 cho môi trường production. |
| **Ảnh hưởng tới sản phẩm?** | Quỹ đạo ước lượng dùng được cho cảnh vài chục mét (trôi ≈ 1–2%). Với hành trình hàng trăm mét sai số sẽ lên cỡ mét, nên cần nguồn tham chiếu ngoài hoặc cảnh báo người dùng. |
| **Ảnh hưởng tới kế hoạch ghép COLMAP?** | Có mốc để chứng minh lợi ích: ghép chỉ đáng làm nếu kéo trôi xuống dưới ~1% và bản đồ xuống gần trần 20 cm **trên các chuỗi chưa chỉnh**. |
| **Ảnh hưởng tới kiểm định?** | Đây là bằng chứng sơ bộ, chưa thay được held-out qualification (AUD-24.S5, AUD-17), vì chưa có ngưỡng chấp nhận và chưa tách tập chỉnh/tập đo. |

## 5. Giới hạn của phép đo

- **Chưa held-out:** chưa chỉnh tham số nên không có rủi ro học thuộc, nhưng cũng chưa có ngưỡng đạt/trượt định trước.
- **Chỉ một thiết bị** (Ouster OS1 của TorWIC) và 600 scan đầu mỗi chuỗi (30–60 giây, ~45 m).
- **Nguyên nhân đuôi của phép đo bản đồ chưa tách được** (insight 4); chỉ loại trừ được lệch khung và độ thưa.
- **Tổng điểm 100 triệu trong script khác 25 triệu của sản phẩm** (insight 7): kết quả quỹ đạo vẫn đúng cho dữ liệu đó, nhưng sản phẩm hiện không nhận chừng ấy scan.
- **Phép đo bản đồ là bản của riêng bước này** (lấy mẫu 1/5 scan, voxel 10 cm), không phải `eval/geometry/surface_error.py` (công cụ đó chấm bản 3DGS của một job).
- Không kiểm hiệu quả của deskew (TorWIC `.pcd` không có timestamp từng điểm) hay IMU.

## 6. Việc tiếp theo (đề xuất)

1. Tách nguyên nhân đuôi ở độ cao 0–1,5 m (vật đã đổi chỗ so với `.ply` hay tạp âm cận cảnh), ví dụ so hai lần quay cùng kho (01 và 05) với nhau.
2. Thí nghiệm tách mật độ scan và độ dài chuỗi (insight 5).
3. Ghép với quỹ đạo COLMAP (R6) và đo lại bằng đúng script này trên 5 tập.
4. Chạy chuỗi dài hơn (toàn bộ chuỗi, chia đoạn) để xem trôi có tuyến tính theo quãng đường không.

## 7. Chỉnh voxel và phân rã sai số (thí nghiệm bổ sung, 2026-10-10)

**Chỉnh một tham số trên tập 01 (600 scan), kiểm trên 02–05 chưa dùng để chỉnh.** Chỉ `voxel_size_m` có tác dụng; tầm tối thiểu/tối đa (1–2 m, 20–40 m) gần như không đổi kết quả.

| Tập | Trôi 0,25 → 0,5 → 1,0 (%) | Bản đồ trong 20 cm 0,25 → 0,5 → 1,0 (%) | Thời gian (s) |
|---|---|---|---|
| 01 (tập chỉnh) | 1,76 → 0,93 → 0,89 | 44,6 → 52,2 → 54,8 | 25 → 9 → 6 |
| 02 | 1,00 → 0,94 → 0,85 | 40,6 → 42,3 → 46,7 | 24 → 7 → 4 |
| 03 | 2,12 → 1,03 → 0,69 | 45,7 → 52,4 → 59,0 | 30 → 9 → 6 |
| 04 | 2,01 → 1,38 → 1,23 | 43,3 → 50,0 → 55,5 | 29 → 8 → 6 |
| 05 | 0,99 → 0,89 → 0,67 | 68,1 → 69,1 → 71,0 | 74 → 17 → 8 |

Giá phải trả: sai/10 bước tăng (trung bình ~3,6 → ~4,7 cm ở voxel 1,0).

**Phân rã sai số cuối đường (01 và 03, mét):**

| Tập | Voxel | Dọc đường | Ngang | **Chiều cao (z)** | Tỉ lệ bước ước/thực | Xoay có dấu / bước |
|---|---:|---:|---:|---:|---:|---:|
| 01 | 0,25 | -0,04 | 0,25 | **+0,73** | 1,002 ± 0,043 | +0,027° |
| 01 | 0,50 | -0,07 | 0,12 | **+0,38** | 0,995 ± 0,051 | +0,021° |
| 01 | 1,00 | -0,03 | 0,11 | **+0,37** | 0,996 ± 0,099 | +0,011° |
| 03 | 0,25 | +0,01 | 0,33 | **+0,92** | 1,07 ± 0,55 | +0,013° |
| 03 | 0,50 | +0,04 | 0,18 | **+0,43** | 1,07 ± 0,55 | +0,007° |
| 03 | 1,00 | +0,17 | 0,09 | **+0,25** | 1,08 ± 0,57 | -0,016° |

**Insight:**
1. **Trôi chủ yếu là trôi theo chiều cao (z)**, không phải đi ngắn/dài hay xoay. Ở voxel mặc định, 0,7–0,9 m của sai số cuối đường nằm ở z; dọc đường chỉ vài cm.
2. **Voxel lớn giảm gần một nửa trôi z** ở cả hai tập, đây là nguồn của phần "trôi giảm".
3. **Giả thuyết "lỗi bước có hệ thống bị bù trừ" không được ủng hộ:** tỉ lệ bước ≈ 1 và thiên lệch xoay có dấu rất nhỏ ở mọi voxel. Còn lại là hai hiệu ứng: z trôi ít hơn và sai số dọc đường từng đoạn nhiễu hơn (độ lệch chuẩn tỉ lệ bước tăng gấp đôi ở voxel 1,0), nên cột "sai/10 bước" xấu đi.
4. **Robot di chuyển trên sàn phẳng nên trôi z cỡ 0,4–0,9 m là không hợp lý về vật lý**; ràng buộc phẳng/mặt sàn (sản phẩm đã có bước tìm sàn) là hướng cải thiện có lợi hơn chỉnh voxel. Chưa thử.
5. Cơ chế vì sao voxel lớn làm giảm trôi z **chưa được kiểm chứng**.
