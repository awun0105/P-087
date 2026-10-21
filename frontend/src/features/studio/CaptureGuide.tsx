"use client";

import { Camera, X } from "lucide-react";

import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/shadcn/dialog";
import { Button } from "@/components/studio/primitives";

const CAMERA_SETTINGS = [
  ["Định dạng", ".mp4 hoặc .mov", "Dùng video MP4 hoặc QuickTime để tải lên."],
  ["Tỉ lệ khung", "16:9, cầm điện thoại nằm ngang", "Hệ thống giữ nguyên tỉ lệ, không cắt khung. Khung ngang bao được nhiều tường và đồ đạc hơn trong mỗi frame."],
  ["Độ phân giải", "1080p hoặc 4K đều được", "Trình duyệt mặc định thu về tối đa 1080p trước khi tải lên; có thể chọn 720p để file nhẹ hơn. Hệ thống không phóng to, nên quay dưới 1080p sẽ mất chi tiết."],
  ["Tốc độ khung", "30 fps", "Khi chuẩn bị video trên trình duyệt, tốc độ được giới hạn ở 30 fps. Quay 60 fps không tăng số frame được giữ lại ở bước này."],
  ["HDR", "Tắt", "Video HDR chưa được hỗ trợ ở bước chuẩn bị trên trình duyệt. Nếu iPhone đang quay HDR / Dolby Vision, vào Cài đặt → Camera → Quay video và tắt Video HDR."],
  ["Ống kính", "Dùng một ống 1x suốt video", "Không zoom, không đổi sang 0.5x giữa chừng. Giữ cùng một ống kính giúp hệ thống tính camera nhất quán."],
  ["Lấy nét / phơi sáng", "Khoá lại", "Trên iPhone, giữ tay lên màn hình đến khi hiện AE/AF Lock. Độ sáng nhảy giữa các frame làm ghép ảnh kém đi."],
  ["Độ dài", "Khoảng 2–3 phút cho một phòng", "Với cấu hình quay đi trong nhà lấy 3 frame mỗi giây, tối đa 600 frame tương đương khoảng 200 giây. Quay dài hơn thì frame bị lấy thưa ra; số này phụ thuộc cấu hình xử lý."],
  ["Dung lượng", "Dưới 2 GB", "Giới hạn tải lên mặc định là 2 GB; giới hạn thực tế có thể do người quản trị cấu hình."],
] as const;

export function CaptureGuide() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="secondary"><Camera aria-hidden />Hướng dẫn quay/chụp</Button>
      </DialogTrigger>
      <DialogContent showCloseButton={false} className="flex max-h-[85dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
        <DialogHeader className="shrink-0 border-b border-line px-5 py-4 pr-16 text-left">
          <DialogTitle>Hướng dẫn quay/chụp</DialogTitle>
          <DialogDescription>Chuẩn bị video và số đo thực tế trước khi dựng scene.</DialogDescription>
        </DialogHeader>
        <DialogClose asChild>
          <Button variant="ghost" size="icon" className="absolute top-2 right-2" aria-label="Đóng hướng dẫn"><X aria-hidden /></Button>
        </DialogClose>
        <div className="min-h-0 space-y-6 overflow-y-auto px-5 py-5 text-sm leading-relaxed">
          <section aria-labelledby="capture-camera-settings">
            <h2 id="capture-camera-settings" className="mb-3 text-base font-semibold">Thông số máy quay</h2>
            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full min-w-[640px] border-collapse text-left">
                <caption className="sr-only">Thông số khuyến nghị khi quay video dựng scene</caption>
                <thead className="bg-paper-sunken">
                  <tr>{["Mục", "Nên dùng", "Lý do"].map((label) => <th key={label} scope="col" className="px-3 py-2 font-semibold">{label}</th>)}</tr>
                </thead>
                <tbody>
                  {CAMERA_SETTINGS.map(([item, recommendation, reason]) => (
                    <tr key={item} className="border-t border-line align-top">
                      <th scope="row" className="w-32 px-3 py-3 font-medium">{item}</th>
                      <td className="w-52 px-3 py-3">{recommendation}</td>
                      <td className="px-3 py-3 text-ink-muted">{reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section aria-labelledby="capture-recording">
            <h2 id="capture-recording" className="mb-3 text-base font-semibold">Cách quay</h2>
            <ol className="list-decimal space-y-2 pl-5">
              <li>Dọn phòng và bật đủ đèn trước khi quay. Đèn sáng đều, tránh ngược sáng từ cửa sổ.</li>
              <li>Đi chậm, khoảng nửa bước mỗi giây. Hai frame liền nhau phải trùng nhau nhiều. Quay nhanh làm ảnh bị nhoè và cảnh có thể bị tách thành nhiều đoạn rời.</li>
              <li>Đi một vòng liền mạch dọc theo tường, camera hướng vào giữa phòng; sau đó quay thêm từ giữa phòng hướng ra ngoài. Không dừng quay rồi quay tiếp.</li>
              <li>Quay kỹ chỗ có khe và vật cản chính, tức là những chỗ bạn sẽ đo bằng thước. Lia qua mỗi chỗ từ 2–3 góc khác nhau.</li>
              <li>Cho sàn vào khoảng 1/3 dưới khung hình. Hệ thống cần thấy sàn để đặt mặt sàn.</li>
              <li>Tránh quay cận vào mặt trơn một màu như tường trắng hay kính vì thiếu điểm để ghép ảnh. Tránh người trong cảnh; nếu có khuôn mặt hoặc biển số, hãy làm mờ trước khi tải lên.</li>
            </ol>
          </section>
          <section aria-labelledby="capture-measurements">
            <h2 id="capture-measurements" className="mb-2 text-base font-semibold">Đo bằng thước</h2>
            <p className="mb-3 text-ink-muted">Làm trước hoặc sau khi quay, nhưng trước khi dời đồ đạc.</p>
            <ul className="list-disc space-y-2 pl-5">
              <li>2–3 đoạn: chọn hai điểm dễ nhận ra trên scene, ví dụ hai góc mặt bàn hay mép tủ. Ghi số mét, chính xác tới cm.</li>
              <li>2–3 khe: đo bề rộng hẹp nhất ở độ cao robot đi qua. Ghi robot có qua được hay không. Nên có ít nhất 1 khe qua được và 1 khe không qua được.</li>
              <li>Robot: chiều rộng, khoảng an toàn, chiều cao thấp nhất và cao nhất.</li>
              <li>Chụp ảnh từng chỗ đo, có cả thước trong ảnh. Lúc chọn điểm trên scene, dùng ảnh để nhớ đã đo từ đâu tới đâu và làm bằng chứng.</li>
              <li>Ghi thêm: tên phòng, thời gian bạn bắt đầu làm và ước lượng số phút dựng bằng tay để nhập vào ô “Mốc làm tay”.</li>
            </ul>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
