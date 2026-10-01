#!/usr/bin/env bash
# Kiểm trong 1–2 phút xem máy (Kaggle, vast.ai…) có dùng được Vulkan trên GPU NVIDIA không — điều kiện để Brush
# train 3DGS. Không cần mã nguồn repo: dán nguyên file này vào một ô `%%bash` hoặc chạy `bash probe_vulkan.sh`.
#
# Kết quả cuối: "VULKAN_GPU=yes" (Brush chạy được trên GPU) hoặc "VULKAN_GPU=no" kèm lý do.
set -uo pipefail

echo "== GPU =="; nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader || echo "không có nvidia-smi"
echo "== NVIDIA_DRIVER_CAPABILITIES=${NVIDIA_DRIVER_CAPABILITIES:-<chưa đặt>} =="

echo "== thư viện đồ hoạ của driver (Vulkan cần libGLX_nvidia + libnvidia-glcore) =="
libs="$(ldconfig -p | grep -E 'libGLX_nvidia|libEGL_nvidia|libnvidia-glcore|libnvidia-glvkspirv' || true)"
[ -n "$libs" ] && echo "$libs" || echo "KHÔNG có thư viện đồ hoạ NVIDIA trong container"

export DEBIAN_FRONTEND=noninteractive
command -v vulkaninfo >/dev/null || { apt-get update -qq && apt-get install -y -qq libvulkan1 vulkan-tools >/dev/null; }

icd=""
for candidate in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
  [ -f "$candidate" ] && icd="$candidate"
done
if [ -z "$icd" ]; then
  icd=/tmp/nvidia_icd.json
  echo '{"file_format_version": "1.0.0", "ICD": {"library_path": "libGLX_nvidia.so.0", "api_version": "1.3.0"}}' > "$icd"
  echo "== không có file ICD sẵn; dùng file tự ghi $icd =="
else
  echo "== ICD có sẵn: $icd =="
fi

echo "== thiết bị Vulkan =="
devices="$(VK_ICD_FILENAMES="$icd" vulkaninfo --summary 2>/dev/null | grep -E 'deviceName|deviceType' || true)"
echo "${devices:-<không liệt kê được thiết bị nào>}"

if echo "$devices" | grep -q "DISCRETE_GPU"; then
  echo "VULKAN_GPU=yes  (đặt VK_ICD_FILENAMES=$icd cho Brush)"
elif [ -z "$libs" ]; then
  echo "VULKAN_GPU=no   (container không được cấp thư viện đồ hoạ của driver NVIDIA; chỉ có CUDA)"
else
  echo "VULKAN_GPU=no   (có thư viện nhưng Vulkan không thấy GPU; xem lỗi: VK_ICD_FILENAMES=$icd vulkaninfo)"
fi
