/**
 * Toàn bộ chữ của landing nằm ở đây để sửa nội dung không phải đụng vào bố cục.
 * Hỗ trợ song ngữ Tiếng Việt (mặc định) và Tiếng Anh.
 *
 * Nguồn định vị: BRAINSTORM.md và MASTER_PITCH.md (cập nhật 18/10/2026).
 * Phân biệt năng lực đã triển khai, nghiệm thu thực tế và tầm nhìn dài hạn.
 * Quy tắc: Không nhắc tên phần mềm 3D thương mại cụ thể;
 * không đưa số liệu, logo hay claim chưa có bằng chứng (UX spec §8 P8, D-05).
 */

import type { Language } from "@/lib/i18n";

export type Status = "done" | "building" | "later";
export type TrackState = "current" | "partial" | "later";

export type WorkflowStep = {
  code: string;
  title: string;
  actor: string;
  body: string;
  output: string;
  status: Status;
  image?: string;
};

export const CONTENT_VI = {
  STATUS_LABEL: {
    done: "Đã triển khai",
    building: "Đang làm",
    later: "Giai đoạn sau",
  } as Record<Status, string>,

  NAV: [
    { href: "#context", label: "Bối cảnh" },
    { href: "#problem", label: "Bài toán" },
    { href: "#solution", label: "Giải pháp" },
    { href: "#workflow", label: "Quy trình" },
    { href: "#progress", label: "Tiến độ" },
    { href: "#roadmap", label: "Dùng ở đâu" },
    { href: "#start", label: "Bắt đầu" },
  ],

  HERO: {
    eyebrow: "Real2Sim Studio · Chuẩn bị môi trường mô phỏng robot",
    titleLead: "Từ video không gian thực",
    titleEmphasis: "đến scene 3D có thể chỉnh sửa.",
    lead:
      "Tái tạo không gian, chỉnh sửa từng vật thể, kiểm tra hình học va chạm và chuẩn bị scene cho thử nghiệm robot trong một workflow thống nhất.",
    note:
      "Khởi đầu với robot di động trong nhà: phòng, văn phòng, hành lang hoặc kho nhỏ. Tầm nhìn: để robot thử nghiệm trong thế giới ảo trước khi bước vào thế giới thực.",
    benefits: [
      "Tái tạo từ dữ liệu quan sát thực",
      "Chỉnh sửa vật thể và collider",
      "Kiểm tra trước khi mô phỏng",
    ],
    pillars: ["Visual", "Geometry", "Physics"],
    sceneLabel: "ví dụ: lối đi trong kho, nhìn từ trên",
  },

  HERO_CHAIN: [
    { label: "Video RGB", detail: "MP4, camera di chuyển", tone: "ink" },
    { label: "3DGS", detail: "Bản xem hình ảnh", tone: "geometry" },
    { label: "Hệ mét", detail: "Xác nhận khoảng cách tham chiếu", tone: "geometry" },
    { label: "Vật thể + collider", detail: "Xác nhận, di chuyển, xoay", tone: "ochre" },
    { label: "Gói OpenUSD", detail: "Chuẩn bị cho simulator", tone: "sage" },
  ] as const,

  CONTEXT: {
    index: "01 / Bối cảnh",
    titleLead: "Robot chạy thử trong máy",
    titleEmphasis: "trước khi tới địa điểm mới.",
    lead:
      "Khi thử robot tại một địa điểm mới, kỹ sư cần kiểm tra lối đi, vật cản và những thay đổi bố trí. Với bài kiểm tra cần hình học 3D hoặc va chạm, họ cần chuẩn bị môi trường ảo tương ứng với địa điểm thực.",
    steps: [
      { title: "Chuẩn bị môi trường ảo", body: "Tái tạo phòng, hành lang hoặc kho nhỏ, rồi kiểm tra kích thước và vật cản." },
      { title: "Robot chạy thử", body: "Đưa scene đã kiểm tra vào simulator để thử robot với bài kiểm tra cụ thể." },
      { title: "So sánh các bố trí", body: "Đánh giá tình huống trước và sau khi đổi vị trí vật cản, trước khi thay đổi ngoài thực tế." },
    ],
    waysTitle: "Hai cách chuẩn bị môi trường 3D",
    ways: [
      {
        name: "Dựng tay",
        verdict: "Chủ động kiểm soát chi tiết",
        body: "Dựng từ CAD hoặc asset có sẵn khi có dữ liệu phù hợp. Kỹ sư vẫn cần đối chiếu bố trí với địa điểm muốn thử.",
      },
      {
        name: "Quay video, để máy dựng 3D",
        verdict: "Bắt đầu từ quan sát thực",
        body:
          "Dùng video khảo sát khi chưa có CAD phù hợp, sau đó kiểm tra tỉ lệ, vật thể và collision để chuẩn bị cho bài mô phỏng.",
      },
    ],
  },

  PROBLEM: {
    index: "02 / Bài toán",
    titleLead: "Từ không gian thực",
    titleEmphasis: "đến scene dùng để thử robot.",
    lead:
      "Tái tạo hình ảnh 3D là bước đầu. Kỹ sư còn cần kích thước, cấu trúc vật thể, hình học va chạm và dữ liệu phù hợp với simulator. Công sức chuẩn bị và cập nhật scene là vấn đề Real2Sim tập trung giải quyết.",
    analogy: {
      title: "Từ bản tái tạo đến scene có thể kiểm tra",
      have: {
        label: "Bản 3D từ video",
        like: "phục vụ quan sát",
        body: "Tái hiện những gì camera nhìn thấy. Cần kiểm tra thêm tỉ lệ, cấu trúc vật thể và collision.",
      },
      need: {
        label: "Thứ robot cần",
        like: "phục vụ một bài kiểm tra cụ thể",
        body: "Vật thể được quản lý riêng, có kích thước và hình học va chạm đã kiểm tra cho bài thử.",
      },
    },
    issuesTitle: "Bốn chỗ còn vướng",
    issues: [
      {
        title: "Vật thể chưa có cấu trúc",
        body: "Một bản tái tạo có thể chưa tách riêng bàn, kệ hoặc vật cản để chỉnh sửa.",
        effect: "Cần thêm bước phân tách và xác nhận trước khi đổi bố trí.",
      },
      {
        title: "Thiếu va chạm cho từng vật",
        body: "Gaussian thể hiện hình ảnh; bài mô phỏng cần hình học va chạm phù hợp.",
        effect: "Collider thiếu hoặc sai có thể làm robot đi xuyên vật hoặc bị chặn ở vùng trống.",
      },
      {
        title: "Chưa chắc đúng kích thước",
        body: "Video RGB đơn mắt không tự bảo đảm tỉ lệ mét. Cần khoảng cách tham chiếu và phép kiểm độc lập.",
        effect: "Đánh giá khoảng hở và đường đi có thể sai nếu chưa kiểm tra tỉ lệ.",
      },
      {
        title: "Scene cần cập nhật khi đổi bố trí",
        body: "Di chuyển bàn, kệ hoặc vật cản làm thay đổi môi trường thử nghiệm.",
        effect: "Cần cập nhật hình ảnh, vị trí vật thể và collision cho cùng một phiên bản scene.",
      },
    ],
    consequence:
      "Kỹ sư cần một quy trình kết nối tái tạo, chỉnh sửa và kiểm tra scene để chuẩn bị các tình huống thử robot.",
    personasTitle: "Ai đang chịu nỗi đau này",
    personas: [
      {
        role: "Kỹ sư mô phỏng",
        tag: "Người dựng scene",
        highlight: "Chuẩn bị & cập nhật",
        highlightNote: "scene cần phù hợp với địa điểm và bài kiểm tra robot",
        pains: [
          "Chuẩn bị geometry và xác nhận tỉ lệ kích thước",
          "Tách vật thể, tạo vùng va chạm qua nhiều công cụ",
          "Cập nhật scene khi vị trí đồ vật thay đổi",
        ],
        handoff: "Giao scene cho kỹ sư robot",
      },
      {
        role: "Kỹ sư tích hợp robot",
        tag: "Người chạy robot",
        highlight: "Nhìn đúng ≠ chạy đúng",
        highlightNote: "scene đẹp vẫn có thể sai đơn vị hoặc thiếu vật cản",
        pains: [
          "Robot kẹt hoặc đi xuyên vật vì collider sai",
          "Kích thước chưa theo mét nên đường đi không đáng tin",
          "Cần thử bố trí mới trước khi thay đổi tại địa điểm thực",
        ],
        handoff: "So sánh các tình huống thử robot",
      },
      {
        role: "Reviewer / Tech Lead",
        tag: "Người duyệt",
        highlight: "Không có một nơi",
        highlightNote: "để đối chiếu chất lượng tái tạo, hình học và kết quả mô phỏng",
        pains: [
          "Không rõ scene nào đã thực sự được kiểm tra",
          "Nguồn dữ liệu và lịch sử chỉnh sửa nằm rời rạc",
          "Khó truy lại đúng bản đã được duyệt",
        ],
        handoff: "Phát hành cho cả nhóm",
      },
    ],
    footnote:
      "Đây là nhu cầu nhóm đang kiểm chứng với các nhóm robotics. Mức tiết kiệm thời gian và công sức cần được đo trên cùng đầu vào và cùng tiêu chí nghiệm thu.",
  },

  SOLUTION: {
    index: "03 / Giải pháp",
    titleLead: "Tái tạo không gian.",
    titleEmphasis: "Chỉnh sửa và chuẩn bị mô phỏng.",
    lead:
      "Real2Sim kết nối tái tạo từ video, chỉnh sửa từng vật thể và kiểm tra hình học va chạm trong một workspace cho robotics. Người dùng có thể chuẩn bị các bố trí khác nhau trước khi đưa scene sang simulator.",
    mapTitle: "Mỗi chỗ vướng, một cách gỡ",
    map: [
      {
        problem: "Vật thể chưa có cấu trúc",
        answer: "Đề xuất và phân tách vật thể như bàn, kệ, thùng; người dùng kiểm tra và xác nhận.",
        status: "done" as Status,
      },
      {
        problem: "Thiếu va chạm cho từng vật",
        answer: "Tạo collider cho từng vật và hỗ trợ kiểm tra va chạm trong trình duyệt.",
        status: "done" as Status,
      },
      {
        problem: "Chưa chắc đúng kích thước",
        answer: "Xác nhận tỉ lệ bằng khoảng cách thực đã biết, đối chiếu với phép đo độc lập.",
        status: "done" as Status,
      },
      {
        problem: "Scene cần cập nhật khi đổi bố trí",
        answer: "Di chuyển, xoay vật đã xác nhận, thêm hoặc ẩn vật cản; kiểm tra lại collision sau chỉnh sửa.",
        status: "done" as Status,
      },
    ],
    extra: {
      title: "Rồi kiểm tra trước khi dùng",
      body:
        "Kiểm tra collision trong Studio, rồi chuẩn bị gói cho Isaac Sim. Bài thử robot và so sánh đường đi giữa các bố trí vẫn cần nghiệm thu trên scene thực tế.",
    },
    contribution: {
      title: "Đóng góp của Real2Sim",
      notTitle: "Nền tảng tái tạo",
      not: "Kết hợp các công cụ reconstruction có sẵn để tạo biểu diễn 3D từ dữ liệu quan sát.",
      isTitle: "Workflow cho robotics",
      is:
        "Kết nối bản tái tạo với thao tác từng vật, quản lý collider và chuẩn bị scene có thể kiểm tra. Mục tiêu là giảm công sức chuẩn bị và cập nhật môi trường thử nghiệm.",
    },
    columnsTitle: "Mỗi người nhận được gì",
    columns: [
      {
        for: "Cho kỹ sư mô phỏng",
        title: "Dựng scene trên trình duyệt",
        points: [
          "Tải video lên, hệ thống tự tách frame, ước lượng camera và dựng 3DGS",
          "Xác nhận tỉ lệ mét bằng một khoảng cách tham chiếu đã biết",
          "Kiểm tra, xác nhận vật thể rồi di chuyển, xoay hoặc thêm vật cản",
          "Lưu thay đổi theo revision để đối chiếu các phiên bản scene",
        ],
        outcome: "Tái tạo · Chỉnh sửa · Kiểm tra",
      },
      {
        for: "Cho kỹ sư tích hợp robot",
        title: "Chuẩn bị scene cho simulator",
        points: [
          "Quản lý collider riêng cho các vật thể được hỗ trợ",
          "Xem hình ảnh và lớp collision, kiểm tra va chạm bằng chế độ Walk",
          "Chuẩn bị và xuất gói OpenUSD theo phiên bản scene",
          "Nghiệm thu import, collision và bài thử robot trong Isaac Sim là bước tiếp theo",
        ],
        outcome: "Có nguồn dữ liệu · Có thể kiểm tra",
      },
      {
        for: "Cho Reviewer",
        title: "Duyệt dựa trên bằng chứng",
        points: [
          "Bảng đánh giá tự kiểm theo từng bước xử lý",
          "Duyệt hoặc từ chối kèm lý do; sửa sau khi duyệt sẽ tạo revision mới",
          "Bản phát hành được niêm phong bằng manifest và checksum",
          "Đối chiếu dữ liệu đầu vào, phiên bản và kết quả kiểm tra",
        ],
        outcome: "Truy vết được · Có bằng chứng để duyệt",
      },
    ],
    layers: [
      { code: "Visual", question: "Scene trông thế nào?", answer: "3D Gaussian Splatting, xem và điều hướng ngay trên trình duyệt.", tone: "geometry" },
      { code: "Geometry", question: "Bề mặt nằm ở đâu?", answer: "Mesh và point cloud để kiểm tra bề mặt, kích thước và hệ tọa độ.", tone: "ink" },
      { code: "Physics", question: "Simulator va chạm với gì?", answer: "Hình học va chạm của vật thể và môi trường, cần kiểm tra theo bài thử.", tone: "ochre" },
    ],
    layersNote: "Với vật thể được hỗ trợ, hình ảnh và collider dùng chung transform. Cần kiểm tra cả collision môi trường sau khi di chuyển vật.",
    checkpoints: ["Xác nhận tỉ lệ mét", "Xác nhận vật thể", "Reviewer duyệt"],
  },

  WORKFLOW: {
    index: "04 / Quy trình",
    titleLead: "Từ một video",
    titleEmphasis: "đến scene để chuẩn bị thử robot.",
    lead:
      "Quy trình kết nối thu nhận, tái tạo, chỉnh sửa và kiểm tra. Scene chỉnh sửa được chỉ sẵn sàng cho mô phỏng khi đạt yêu cầu về kích thước, collision và khả năng tương thích của bài thử.",
    steps: [
      {
        code: "01",
        title: "Nạp dữ liệu",
        actor: "Người",
        body: "Tải video MP4 quay không gian trong nhà bằng camera di chuyển, đủ góc nhìn và có quyền sử dụng dữ liệu.",
        output: "Job xử lý",
        status: "done",
      },
      {
        code: "02",
        title: "Tái tạo 3D",
        actor: "Máy",
        body: "Tách frame, COLMAP ước lượng vị trí camera, Brush dựng 3DGS, nén SOG để xem trên trình duyệt.",
        output: "Bản xem 3DGS",
        status: "done",
      },
      {
        code: "03",
        title: "Tỉ lệ mét",
        actor: "Người",
        body: "Dùng khoảng cách thực đã biết để xác nhận tỉ lệ, chọn phép đo kiểm độc lập và mặt sàn. Video RGB đơn mắt không tự bảo đảm đơn vị mét.",
        output: "Scene hệ mét",
        status: "done",
      },
      {
        code: "04",
        title: "Vật thể",
        actor: "Máy + Người",
        body: "Hệ thống đề xuất vật thể. Bạn kiểm tra, xác nhận, đổi tên, di chuyển, xoay hoặc thêm vật cản để tạo bố trí cần thử.",
        output: "Revision scene",
        status: "done",
      },
      {
        code: "05",
        title: "Gói mô phỏng",
        actor: "Máy",
        body: "Chuẩn bị geometry và collider, kiểm tra gói OpenUSD theo revision. Gói xuất cần được kiểm tra tiếp trong simulator.",
        output: "Gói ứng viên",
        status: "done",
      },
      {
        code: "06",
        title: "Kiểm tra Isaac Sim",
        actor: "Máy",
        body: "Mục tiêu nghiệm thu: import scene, kiểm tra collision và chạy cùng một robot trên hai bố trí. Kết quả end-to-end trên scene thực tế cần được xác nhận.",
        output: "Báo cáo validation",
        status: "building",
      },
      {
        code: "07",
        title: "Duyệt & phát hành",
        actor: "Người",
        body: "Reviewer đối chiếu phiên bản scene và bằng chứng kiểm tra trước khi duyệt. Chỉ công bố mức sẵn sàng theo phạm vi đã được xác minh.",
        output: "Bản phát hành",
        status: "building",
      },
    ] as WorkflowStep[],
  },

  PROGRESS: {
    index: "05 / Tiến độ",
    titleLead: "Nền tảng đã triển khai.",
    titleEmphasis: "Tiếp tục kiểm chứng thực tế.",
    lead:
      "Nhóm đã triển khai reconstruction, chỉnh sửa vật thể, collision trong trình duyệt và xuất USD. Chất lượng phụ thuộc dữ liệu đầu vào; độ tin cậy trên scene thực tế và bài thử robot trong Isaac Sim vẫn cần được nghiệm thu.",
    tiers: [
      {
        status: "done" as Status,
        title: "Luồng dựng scene",
        items: [
          "Pipeline video → 3DGS và cơ chế xác nhận tỉ lệ",
          "Phân tách, xác nhận, Move/Rotate vật thể và collider riêng",
          "Kiểm tra collision bằng Walk trong browser; đóng gói và xuất USD",
        ],
      },
      {
        status: "building" as Status,
        title: "Kiểm chứng mô phỏng",
        items: [
          "Nghiệm thu import, va chạm và bài thử robot end-to-end trong Isaac Sim",
          "Độ đầy đủ của vật thể và collision sau khi đổi bố trí",
          "Benchmark thời gian, công sức chỉnh sửa và chất lượng scene đạt yêu cầu",
        ],
      },
      {
        status: "later" as Status,
        title: "Mở rộng",
        items: [
          "Tạo nhiều biến thể bố trí và so sánh kịch bản thử robot",
          "Tự đề xuất tình huống kiểm thử dựa trên nhiệm vụ robot",
          "Spatial Imagination: hỗ trợ đánh giá robot trên nhiều tình huống giả định",
        ],
      },
    ],
    metricsTitle: "Nhóm cam kết đo",
    metrics: [
      { group: "Công sức chuẩn bị", items: "Thời gian đến scene dùng được · Thời gian thao tác thủ công" },
      { group: "Tỉ lệ & hình học", items: "Sai lệch kích thước · Mức đầy đủ của vật thể" },
      { group: "Va chạm & đường đi", items: "Vật cản thiếu hoặc giả · Collision sau khi chỉnh sửa" },
      { group: "Hệ thống", items: "Import Isaac Sim · Bài thử robot lặp lại được" },
    ],
    metricsNote: "Đo trên cùng đầu vào và tiêu chí nghiệm thu. Chưa công bố tỉ lệ tiết kiệm thời gian hoặc hiệu quả vận hành robot ngoài thực tế.",
    samplesTitle: "Scene mẫu đã xử lý sẵn",
    samplesLead: "Mở scene đã chuẩn bị để xem hình ảnh và cấu trúc. Mẫu dựng sẵn không thay thế bằng chứng chạy video → mô phỏng end-to-end.",
  },

  ROADMAP: {
    index: "06 / Dùng ở đâu",
    titleLead: "Một workspace Real2Sim.",
    titleEmphasis: "Cho các bài thử robot trong nhà.",
    lead:
      "Khởi đầu với phòng, văn phòng, hành lang hoặc kho nhỏ có vật thể tĩnh và một mặt sàn. Các use case dưới đây là hướng ứng dụng đang được kiểm chứng.",
    core: "Editable Real-to-Sim Workspace",
    adapters: ["Tái tạo & chỉnh sửa", "Chuẩn bị & kiểm tra collision"],
    tracks: [
      {
        state: "current" as TrackState,
        tag: "MVP · đang triển khai",
        domain: "Thử robot di động trong nhà",
        simulator: "NVIDIA Isaac Sim",
        body: "Chuẩn bị môi trường từ video khi chưa có CAD phù hợp. Bài thử robot trong Isaac Sim cần nghiệm thu trên scene thực tế.",
      },
      {
        state: "partial" as TrackState,
        tag: "Đã có công cụ chỉnh sửa",
        domain: "Khám phá thay đổi bố trí",
        simulator: "Studio · Vật thể & collision",
        body: "Dời bàn, xoay kệ hoặc thêm vật cản trong scene. Kiểm tra lại collision trước khi xuất và thử bố trí mới trong simulator.",
      },
      {
        state: "later" as TrackState,
        tag: "Tầm nhìn dài hạn",
        domain: "Diễn tập nhiều tình huống",
        simulator: "Spatial Imagination for Robots",
        body: "Hướng tới tạo và so sánh nhiều phiên bản của môi trường thực theo nhiệm vụ robot. Tự đề xuất kịch bản và tự học chưa phải khả năng hiện tại.",
      },
    ],
  },

  START: {
    titleLead: "Bắt đầu nhỏ.",
    titleEmphasis: "Thử một scene mẫu trước.",
    steps: [
      { title: "Thử scene mẫu", body: "Xem lại tiến trình đã ghi và mở scene đã xử lý sẵn. Không cần đăng nhập." },
      { title: "Đăng nhập và tải video", body: "Tạo scene từ video phù hợp, kiểm tra tỉ lệ và chỉnh sửa vật thể theo bố trí cần thử." },
      { title: "Tải gói mô phỏng", body: "Chuẩn bị gói OpenUSD theo revision; kiểm tra khả năng import và bài thử robot trong simulator." },
    ],
  },

  FOOTER: {
    tagline: "Từ video không gian thực đến scene 3D có thể chỉnh sửa, phục vụ chuẩn bị mô phỏng robot.",
    team: "Team P-087 · VinUni AI20K Build Phase, Cohort 4",
    github: "https://github.com/AI20K-Build-Phase-Cohort-4/P-087",
    license: "MIT License",
  },
};

export const CONTENT_EN = {
  STATUS_LABEL: {
    done: "Implemented",
    building: "In progress",
    later: "Future phase",
  } as Record<Status, string>,

  NAV: [
    { href: "#context", label: "Context" },
    { href: "#problem", label: "Problem" },
    { href: "#solution", label: "Solution" },
    { href: "#workflow", label: "Workflow" },
    { href: "#progress", label: "Progress" },
    { href: "#roadmap", label: "Use Cases" },
    { href: "#start", label: "Get Started" },
  ],

  HERO: {
    eyebrow: "Real2Sim Studio · Robotics Simulation Preparation",
    titleLead: "From real-world video",
    titleEmphasis: "to editable 3D scenes.",
    lead:
      "Reconstruct real spaces, edit individual objects, inspect collision geometry, and prepare scenes for robotics simulation through one connected workflow.",
    note:
      "Starting with indoor mobile robotics: rooms, offices, corridors, and small storage areas. Our vision: let robots rehearse the real world before they enter it.",
    benefits: [
      "Grounded in real observations",
      "Object and collider editing",
      "Inspect before simulation",
    ],
    pillars: ["Visual", "Geometry", "Physics"],
    sceneLabel: "example: warehouse aisle, top-down view",
  },

  HERO_CHAIN: [
    { label: "RGB Video", detail: "MP4, moving camera", tone: "ink" },
    { label: "3DGS", detail: "Visual preview", tone: "geometry" },
    { label: "Metric scale", detail: "Confirm a reference distance", tone: "geometry" },
    { label: "Objects + collider", detail: "Confirm, move, rotate", tone: "ochre" },
    { label: "OpenUSD package", detail: "Prepare for a simulator", tone: "sage" },
  ] as const,

  CONTEXT: {
    index: "01 / Context",
    titleLead: "Test robots in simulation",
    titleEmphasis: "before entering a new site.",
    lead:
      "At a new site, engineers need to evaluate clearances, obstacles, and layout changes. Tests involving 3D geometry or collisions require a virtual environment that represents the physical location.",
    steps: [
      { title: "Prepare a virtual environment", body: "Reconstruct a room, corridor, or small storage area, then inspect dimensions and obstacles." },
      { title: "Simulate test runs", body: "Bring the inspected scene into a simulator for a defined robot test." },
      { title: "Compare layouts", body: "Evaluate scenarios before and after moving an obstacle, before changing the physical site." },
    ],
    waysTitle: "Two ways to prepare a 3D environment",
    ways: [
      {
        name: "Manual CAD modeling",
        verdict: "Direct control over detail",
        body: "Build from CAD or existing assets when suitable data is available. Engineers still need to match the layout to the intended site.",
      },
      {
        name: "Video capture to 3D",
        verdict: "Start from real observations",
        body:
          "Use captured video when suitable CAD is unavailable, then inspect scale, objects, and collision geometry for the simulation test.",
      },
    ],
  },

  PROBLEM: {
    index: "02 / Problem",
    titleLead: "From a real space",
    titleEmphasis: "to a scene for robot testing.",
    lead:
      "Visual reconstruction is the first step. Engineers also need scale, object structure, collision geometry, and assets compatible with a simulator. Real2Sim focuses on the effort of preparing and updating those scenes.",
    analogy: {
      title: "From reconstruction to an inspectable scene",
      have: {
        label: "Raw 3D from video",
        like: "for visual inspection",
        body: "Represents what the camera observed. Scale, object structure, and collision still need inspection.",
      },
      need: {
        label: "What robots require",
        like: "for a defined test",
        body: "Individually managed objects with dimensions and collision geometry checked for the intended test.",
      },
    },
    issuesTitle: "Four unresolved hurdles",
    issues: [
      {
        title: "Unstructured objects",
        body: "A reconstruction may not separate tables, shelves, or obstacles for individual editing.",
        effect: "Segmentation and confirmation are needed before changing the layout.",
      },
      {
        title: "Missing object colliders",
        body: "Gaussians represent appearance; simulation needs suitable collision geometry.",
        effect: "Missing or incorrect colliders can let robots pass through objects or block empty space.",
      },
      {
        title: "Unverified metric dimensions",
        body: "Monocular RGB video does not guarantee metric scale. A reference distance and an independent check are needed.",
        effect: "Clearance and route evaluation can be wrong without scale verification.",
      },
      {
        title: "Updates after layout changes",
        body: "Moving a table, shelf, or obstacle changes the test environment.",
        effect: "Visuals, object placement, and collision must match the same scene revision.",
      },
    ],
    consequence:
      "Engineers need a connected reconstruction, editing, and inspection workflow to prepare robot test scenarios.",
    personasTitle: "Who carries this burden",
    personas: [
      {
        role: "Simulation Engineer",
        tag: "Scene Builder",
        highlight: "Prepare & update",
        highlightNote: "scenes must suit the physical site and the intended robot test",
        pains: [
          "Prepare geometry and verify physical dimensions",
          "Segmenting objects and generating collision meshes across disparate tools",
          "Update the scene when object placement changes",
        ],
        handoff: "Handoff scene to Robot Engineer",
      },
      {
        role: "Robot Integration Engineer",
        tag: "Robot Operator",
        highlight: "Looks right ≠ runs right",
        highlightNote: "visual beauty does not prevent scale errors or missing collision hulls",
        pains: [
          "Robots collide or phase through geometry due to invalid colliders",
          "Unverified dimensions make simulated trajectories untrustworthy",
          "Need to test new layouts before changing the physical site",
        ],
        handoff: "Compare robot test scenarios",
      },
      {
        role: "Reviewer / Tech Lead",
        tag: "Gatekeeper",
        highlight: "No single surface",
        highlightNote: "to cross-examine reconstruction visual fidelity, geometry, and sim results",
        pains: [
          "Unclear which scene variants were genuinely validated in simulation",
          "Data provenance and edit revisions remain scattered across folders",
          "Difficult to reproduce and audit the exact approved release",
        ],
        handoff: "Release to engineering team",
      },
    ],
    footnote:
      "We are validating these needs with robotics teams. Time and effort savings require measurement using the same input and acceptance criteria.",
  },

  SOLUTION: {
    index: "03 / Solution",
    titleLead: "Reconstruct real spaces.",
    titleEmphasis: "Edit and prepare for simulation.",
    lead:
      "Real2Sim connects video reconstruction, object editing, and collision inspection in a robotics workspace. Users can prepare different layouts before taking the scene into a simulator.",
    mapTitle: "A concrete resolution for each bottleneck",
    map: [
      {
        problem: "Unstructured objects",
        answer: "Propose and separate objects such as tables, shelves, and boxes for user review and confirmation.",
        status: "done" as Status,
      },
      {
        problem: "Missing object colliders",
        answer: "Generate per-object colliders and support collision inspection in the browser.",
        status: "done" as Status,
      },
      {
        problem: "Unverified metric dimensions",
        answer: "Confirm scale using a known physical distance and an independent measurement.",
        status: "done" as Status,
      },
      {
        problem: "Updates after layout changes",
        answer: "Move or rotate confirmed objects, add or hide obstacles, then inspect collision after editing.",
        status: "done" as Status,
      },
    ],
    extra: {
      title: "Simulate and verify before sign-off",
      body:
        "Inspect collision in Studio, then prepare a package for Isaac Sim. Robot testing and route comparison across layouts still require acceptance on real scenes.",
    },
    contribution: {
      title: "Real2Sim Value Proposition",
      notTitle: "Reconstruction foundation",
      not: "Combine existing reconstruction tools to build a 3D representation from captured observations.",
      isTitle: "A robotics workflow",
      is:
        "Connect reconstruction with object manipulation, collider management, and inspectable scene preparation. The goal is to reduce the effort of preparing and updating test environments.",
    },
    columnsTitle: "What each stakeholder receives",
    columns: [
      {
        for: "For Simulation Engineers",
        title: "Browser-native scene authoring",
        points: [
          "Upload video; system extracts frames, computes camera poses, and trains 3DGS",
          "Calibrate metric scale using a known ground-truth reference distance",
          "Review and confirm objects, then move, rotate, or add obstacles",
          "Save changes by revision to compare scene versions",
        ],
        outcome: "Reconstruct · Edit · Inspect",
      },
      {
        for: "For Robot Integration Engineers",
        title: "Prepare scenes for a simulator",
        points: [
          "Manage separate colliders for supported objects",
          "Inspect visual and collision layers; preview collisions in Walk mode",
          "Prepare and export OpenUSD packages by scene revision",
          "Isaac Sim import, collision, and robot test acceptance are the next step",
        ],
        outcome: "Traceable data · Inspectable scenes",
      },
      {
        for: "For Reviewers",
        title: "Evidence-backed sign-off",
        points: [
          "Automated checklist reports for each processing pipeline stage",
          "Approve or reject with reason log; edits post-approval create fresh revisions",
          "Released packages sealed with cryptographic manifest checksums",
          "Compare input data, scene versions, and inspection results",
        ],
        outcome: "Traceable · Evidence for review",
      },
    ],
    layers: [
      { code: "Visual", question: "What does it look like?", answer: "3D Gaussian Splatting, interactive in browser.", tone: "geometry" },
      { code: "Geometry", question: "Where are the surfaces?", answer: "Mesh and point clouds for inspecting surfaces, dimensions, and coordinate frames.", tone: "ink" },
      { code: "Physics", question: "What does the robot collide with?", answer: "Object and environment collision geometry to inspect for the intended test.", tone: "ochre" },
    ],
    layersNote: "For supported objects, visuals and colliders share a transform. Environment collision also needs inspection after moving an object.",
    checkpoints: ["Metric scale confirm", "Object candidate confirm", "Reviewer sign-off"],
  },

  WORKFLOW: {
    index: "04 / Workflow",
    titleLead: "From raw video",
    titleEmphasis: "to a scene for robot test preparation.",
    lead:
      "Capture, reconstruct, edit, and inspect in a connected workflow. An editable scene is simulation-ready only when it meets the scale, collision, and compatibility requirements of a defined test.",
    steps: [
      {
        code: "01",
        title: "Data Intake",
        actor: "Human",
        body: "Upload moving-camera MP4 video of an indoor space, with sufficient viewpoints and permission to use the data.",
        output: "Processing Job",
        status: "done",
      },
      {
        code: "02",
        title: "3D Reconstruction",
        actor: "Machine",
        body: "Frame extraction, COLMAP camera pose estimation, Brush 3DGS training, and SOG compression for instant browser preview.",
        output: "3DGS Preview",
        status: "done",
      },
      {
        code: "03",
        title: "Metric Scale",
        actor: "Human",
        body: "Confirm scale using a known physical distance, an independent check, and the ground plane. Monocular RGB video does not guarantee metric units.",
        output: "Metric Scene",
        status: "done",
      },
      {
        code: "04",
        title: "Object Candidates",
        actor: "Machine + Human",
        body: "Review proposed objects, confirm, rename, move, rotate, or add obstacles to create the intended test layout.",
        output: "Scene Revision",
        status: "done",
      },
      {
        code: "05",
        title: "Sim Package",
        actor: "Machine",
        body: "Prepare geometry and colliders, then check the OpenUSD package for the scene revision. Exported packages need further simulator validation.",
        output: "Candidate Package",
        status: "done",
      },
      {
        code: "06",
        title: "Isaac Sim Validation",
        actor: "Machine",
        body: "Acceptance target: import a scene, inspect collision, and run the same robot in two layouts. End-to-end results on real scenes still need confirmation.",
        output: "Validation Report",
        status: "building",
      },
      {
        code: "07",
        title: "Review & Release",
        actor: "Human",
        body: "Review the scene revision and inspection evidence before approval. Report readiness only within the verified scope.",
        output: "Audited Release",
        status: "building",
      },
    ] as WorkflowStep[],
  },

  PROGRESS: {
    index: "05 / Progress",
    titleLead: "The foundation is implemented.",
    titleEmphasis: "Real-scene validation continues.",
    lead:
      "Reconstruction, object editing, browser collision, and USD export have been implemented. Quality depends on input data; real-scene reliability and robot testing in Isaac Sim still require acceptance.",
    tiers: [
      {
        status: "done" as Status,
        title: "Scene authoring pipeline",
        items: [
          "Video → 3DGS pipeline and scale confirmation mechanisms",
          "Object segmentation, confirmation, Move/Rotate, and per-object colliders",
          "Browser collision preview in Walk mode; USD packaging and export",
        ],
      },
      {
        status: "building" as Status,
        title: "Simulation validation",
        items: [
          "Isaac Sim import, collision, and end-to-end robot test acceptance",
          "Object completeness and collision correctness after layout changes",
          "Benchmark time, editing effort, and scene quality against acceptance criteria",
        ],
      },
      {
        status: "later" as Status,
        title: "Future extensions",
        items: [
          "Create layout variants and compare robot test scenarios",
          "Suggest test scenarios based on robot tasks",
          "Spatial Imagination: evaluate robots across possible environment changes",
        ],
      },
    ],
    metricsTitle: "Committed evaluation metrics",
    metrics: [
      { group: "Preparation effort", items: "Time to a usable scene · Human editing time" },
      { group: "Scale & Geometry", items: "Dimension error · Object completeness" },
      { group: "Collision & Trajectory", items: "Missing or false obstacles · Collision after editing" },
      { group: "System", items: "Isaac Sim import · Repeatable robot tests" },
    ],
    metricsNote: "Measure with the same input and acceptance criteria. No quantified time savings or physical robot deployment outcomes are claimed yet.",
    samplesTitle: "Pre-processed sample scenes",
    samplesLead: "Explore prepared scenes to inspect visuals and structure. Pre-built samples do not establish a complete video-to-simulation result.",
  },

  ROADMAP: {
    index: "06 / Use Cases",
    titleLead: "One Real2Sim workspace.",
    titleEmphasis: "For indoor robotics tests.",
    lead:
      "Starting with rooms, offices, corridors, and small storage areas with static objects and one floor. These use cases are application directions under validation.",
    core: "Editable Real-to-Sim Workspace",
    adapters: ["Reconstruct & edit", "Prepare & inspect collision"],
    tracks: [
      {
        state: "current" as TrackState,
        tag: "MVP · in progress",
        domain: "Indoor Mobile Robot Testing",
        simulator: "NVIDIA Isaac Sim",
        body: "Prepare environments from video when suitable CAD is unavailable. Robot testing in Isaac Sim requires real-scene acceptance.",
      },
      {
        state: "partial" as TrackState,
        tag: "Editing tools implemented",
        domain: "Layout Change Exploration",
        simulator: "Studio · Objects & collision",
        body: "Move tables, rotate shelves, or add scene obstacles. Inspect collision before exporting and testing a new layout in a simulator.",
      },
      {
        state: "later" as TrackState,
        tag: "Long-term vision",
        domain: "Rehearse Possible Changes",
        simulator: "Spatial Imagination for Robots",
        body: "Work toward creating and comparing versions of real environments for robot tasks. Automatic scenario generation and robot learning are future capabilities.",
      },
    ],
  },

  START: {
    titleLead: "Start small.",
    titleEmphasis: "Try a sample scene first.",
    steps: [
      { title: "Try sample scenes", body: "Inspect recorded pipeline timeline and explore pre-built scenes. No account required." },
      { title: "Sign in & upload video", body: "Create a scene from supported video, inspect scale, and edit objects for the intended test layout." },
      { title: "Download sim package", body: "Prepare an OpenUSD package by revision, then verify import and robot testing in the simulator." },
    ],
  },

  FOOTER: {
    tagline: "Turn real-world video into editable 3D scenes for robotics simulation preparation.",
    team: "Team P-087 · VinUni AI20K Build Phase, Cohort 4",
    github: "https://github.com/AI20K-Build-Phase-Cohort-4/P-087",
    license: "MIT License",
  },
};

export const UI_LABELS = {
  vi: {
    tryDemo: "Thử scene mẫu",
    openStudio: "Truy cập Studio",
    loginStudio: "Đăng nhập Studio",
    openSample: "Mở scene mẫu",
    brandAria: "Real2Sim Studio, về đầu trang",
    navAria: "Các phần của trang",
    menuOpen: "Mở menu",
    menuClose: "Đóng menu",
    themeDark: "Chuyển sang giao diện tối",
    themeLight: "Chuyển sang giao diện sáng",
    selectPalette: "Chọn giao diện",
    paletteTitle: "Bảng màu",
    paletteClassic: "Cổ điển",
    paletteGruvbox: "Gruvbox",
    paletteClassicNote: "be + cam",
    paletteGruvboxNote: "vàng kem + cam đất (mặc định)",
    langToEn: "Chuyển sang tiếng Anh (EN)",
    langToVi: "Chuyển sang tiếng Việt (VI)",
    sourceOnGithub: "Mã nguồn trên GitHub",
    consequence: "Hậu quả: ",
    result: "Kết quả",
    oneObjectThreeLayers: "Một vật, ba lớp, một transform.",
    humanDecisions: "Những chỗ con người quyết định",
    diagramCaption: "Sơ đồ minh hoạ luồng xử lý, không phải ảnh chụp kết quả.",
    step: "Bước",
    explore: "Khám phá",
    layersGroup: "Các lớp",
  },
  en: {
    tryDemo: "Try sample scene",
    openStudio: "Open Studio",
    loginStudio: "Sign in to Studio",
    openSample: "Open sample scene",
    brandAria: "Real2Sim Studio, top of page",
    navAria: "Page navigation",
    menuOpen: "Open menu",
    menuClose: "Close menu",
    themeDark: "Switch to dark theme",
    themeLight: "Switch to light theme",
    selectPalette: "Select palette",
    paletteTitle: "Color palette",
    paletteClassic: "Classic",
    paletteGruvbox: "Gruvbox",
    paletteClassicNote: "beige + ember",
    paletteGruvboxNote: "cream + ochre (default)",
    langToEn: "Switch to English (EN)",
    langToVi: "Switch to Vietnamese (VI)",
    sourceOnGithub: "Source on GitHub",
    consequence: "Consequence: ",
    result: "Output",
    oneObjectThreeLayers: "One entity, three layers, one transform.",
    humanDecisions: "Human verification checkpoints",
    diagramCaption: "Pipeline schematic diagram, not rendered result.",
    step: "Step",
    explore: "Explore",
    layersGroup: "Layers",
  },
};

export function getContent(lang: Language = "vi") {
  return lang === "en" ? CONTENT_EN : CONTENT_VI;
}

export function getUiLabels(lang: Language = "vi") {
  return lang === "en" ? UI_LABELS.en : UI_LABELS.vi;
}

// Giữ các export mặc định (tiếng Việt) để tương thích ngược hoàn toàn
export const STATUS_LABEL = CONTENT_VI.STATUS_LABEL;
export const NAV = CONTENT_VI.NAV;
export const HERO = CONTENT_VI.HERO;
export const HERO_CHAIN = CONTENT_VI.HERO_CHAIN;
export const CONTEXT = CONTENT_VI.CONTEXT;
export const PROBLEM = CONTENT_VI.PROBLEM;
export const SOLUTION = CONTENT_VI.SOLUTION;
export const WORKFLOW = CONTENT_VI.WORKFLOW;
export const PROGRESS = CONTENT_VI.PROGRESS;
export const ROADMAP = CONTENT_VI.ROADMAP;
export const START = CONTENT_VI.START;
export const FOOTER = CONTENT_VI.FOOTER;
