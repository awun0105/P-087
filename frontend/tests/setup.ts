import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library chỉ tự cleanup khi `globals: true`; ở đây tắt globals nên
// phải gọi tay, nếu không DOM của test trước rò sang test sau.
afterEach(cleanup);
