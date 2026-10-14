/**
 * Stream input assembly uploads thẳng sang FastAPI.
 *
 * Rewrite `/api/v1/*` của Next buffer body tối đa 10MB rồi cắt (Next 16), nên file
 * lớn (Gaussian PLY, point cloud PCD, ZIP) hỏng giữa chừng với mã lỗi 500.
 * Route handler này được ưu tiên trước rewrite, chuyển tiếp `request.body` dạng stream
 * (không giữ cả file trong RAM) và trả nguyên response từ backend.
 */

const BACKEND_ORIGIN = process.env.REAL2SIM_API_URL ?? "http://127.0.0.1:8000";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Header chuyển tiếp sang FastAPI, bao gồm cookie phiên đăng nhập và Content-Type.
 */
function forwardHeaders(request: Request, contentType?: string): Headers {
  const headers = new Headers();
  for (const name of ["cookie", "authorization", "x-forwarded-for", "user-agent"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (contentType) headers.set("Content-Type", contentType);
  return headers;
}

function passthrough(response: Response): Response {
  return new Response(response.body, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
  });
}

export async function POST(request: Request): Promise<Response> {
  const search = new URL(request.url).search;
  try {
    const response = await fetch(`${BACKEND_ORIGIN}/api/v1/input-assemblies/uploads${search}`, {
      method: "POST",
      body: request.body,
      headers: forwardHeaders(request, request.headers.get("Content-Type") ?? "application/octet-stream"),
      // Node fetch cần `duplex: "half"` khi body là stream.
      duplex: "half",
      signal: request.signal,
    } as RequestInit & { duplex: "half" });
    return passthrough(response);
  } catch {
    return Response.json({ detail: "Không chuyển được input upload tới backend" }, { status: 502 });
  }
}
