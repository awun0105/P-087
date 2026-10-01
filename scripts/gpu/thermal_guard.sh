#!/usr/bin/env bash
# Bảo vệ nhiệt cho máy local khi chạy pipeline GPU (laptop dễ tự tắt vì quá nhiệt).
#
# Theo dõi nhiệt CPU (x86_pkg_temp) và GPU (nvidia-smi). Khi vượt ngưỡng nóng thì ĐÓNG BĂNG unit
# systemd của stack (cgroup freezer: tiến trình đứng yên, không mất việc) và tạm dừng container COLMAP;
# khi nguội xuống dưới ngưỡng mát thì thả ra. Không kill gì cả nên job tiếp tục đúng chỗ đang dở.
#
#   scripts/gpu/thermal_guard.sh [unit]          # mặc định: r2s-stack
#
# Ngưỡng chỉnh qua biến môi trường: HOT_CPU, HOT_GPU, COOL_CPU, COOL_GPU (°C), POLL (giây).
set -euo pipefail

UNIT="${1:-r2s-stack}"
HOT_CPU="${HOT_CPU:-88}"; HOT_GPU="${HOT_GPU:-82}"
COOL_CPU="${COOL_CPU:-72}"; COOL_GPU="${COOL_GPU:-68}"
POLL="${POLL:-3}"

cpu_zone=""
for zone in /sys/class/thermal/thermal_zone*; do
  [ "$(cat "$zone/type")" = "x86_pkg_temp" ] && cpu_zone="$zone/temp"
done
[ -n "$cpu_zone" ] || { echo "[!] Không thấy cảm biến x86_pkg_temp." >&2; exit 1; }

cpu_temp() { echo $(( $(cat "$cpu_zone") / 1000 )); }
gpu_temp() { nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0; }
colmap_containers() { docker ps -q --filter "ancestor=colmap/colmap" 2>/dev/null || true; }

set_frozen() {  # set_frozen freeze|thaw
  systemctl --user "$1" "$UNIT" 2>/dev/null || true
  local action=pause; [ "$1" = thaw ] && action=unpause
  for id in $(colmap_containers); do docker "$action" "$id" >/dev/null 2>&1 || true; done
}
trap 'set_frozen thaw' EXIT

frozen=0
while true; do
  cpu=$(cpu_temp); gpu=$(gpu_temp); gpu=${gpu:-0}
  if [ "$frozen" = 0 ] && { [ "$cpu" -ge "$HOT_CPU" ] || [ "$gpu" -ge "$HOT_GPU" ]; }; then
    set_frozen freeze; frozen=1
    echo "$(date +%T) nóng (CPU ${cpu}°C, GPU ${gpu}°C) → đóng băng $UNIT"
  elif [ "$frozen" = 1 ] && [ "$cpu" -le "$COOL_CPU" ] && [ "$gpu" -le "$COOL_GPU" ]; then
    set_frozen thaw; frozen=0
    echo "$(date +%T) đã nguội (CPU ${cpu}°C, GPU ${gpu}°C) → chạy tiếp $UNIT"
  fi
  sleep "$POLL"
done
