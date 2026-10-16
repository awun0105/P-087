#!/usr/bin/env bash
# Dựng hoặc nhận ra toàn bộ runtime GPU ở một thư mục gốc, bằng một công thức cho mọi máy (laptop, pod, image).
#
#   scripts/gpu/install.sh <gốc> [--only a,b] [--skip a,b] [--colmap=docker|binary] [--colmap-from-file <tar.zst>]
#                          [--objectgs-wheels <dir>]
#                          [--skip-gpu-check] [--system-node] [--apt] [--check-system] [--no-doctor]
#
# Thành phần: colmap, brush, splat, lidar_odometry, scene, objectgs. Với mỗi thành phần: đã có và đúng phiên bản thì
# nhận ra và không cài lại; chưa có thì cài rồi kiểm lại. Cuối cùng ghi <gốc>/runtime.env (chỉ đường dẫn runtime,
# không secret) và chạy doctor. Phiên bản ghim: configs/runtime/pins.env.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO
ALL=(colmap brush splat lidar_odometry scene objectgs)

ONLY=""
SKIP=""
COLMAP_MODE="docker"
OBJECTGS_WHEELS=""
COLMAP_FROM_FILE=""
SKIP_GPU_CHECK=0
SYSTEM_NODE=0
USE_APT=0
CHECK_ONLY=0
NO_DOCTOR=0
GOC=""
while [ $# -gt 0 ]; do
  case "$1" in
    --only) ONLY="${2:?--only cần danh sách}"; shift 2 ;;
    --skip) SKIP="${2:?--skip cần danh sách}"; shift 2 ;;
    --colmap=*) COLMAP_MODE="${1#--colmap=}"; shift ;;
    --objectgs-wheels) OBJECTGS_WHEELS="${2:?--objectgs-wheels cần thư mục}"; shift 2 ;;
    --colmap-from-file) COLMAP_FROM_FILE="${2:?--colmap-from-file cần đường dẫn gói}"; shift 2 ;;
    --skip-gpu-check) SKIP_GPU_CHECK=1; shift ;;
    --system-node) SYSTEM_NODE=1; shift ;;
    --apt) USE_APT=1; shift ;;
    --check-system) CHECK_ONLY=1; shift ;;
    --no-doctor) NO_DOCTOR=1; shift ;;
    -*) echo "tham số lạ: $1" >&2; exit 2 ;;
    *) [ -z "$GOC" ] || { echo "chỉ nhận một thư mục gốc" >&2; exit 2; }; GOC="$1"; shift ;;
  esac
done

source "$REPO/scripts/gpu/install.d/_lib.sh"
for component in "${ALL[@]}"; do source "$REPO/scripts/gpu/install.d/$component.sh"; done
[[ "$COLMAP_MODE" = docker || "$COLMAP_MODE" = binary ]] || die "--colmap phải là docker hoặc binary"

check_system() {  # in gói apt còn thiếu; với --apt và quyền root thì cài
  local missing=() package
  while IFS= read -r package; do
    case "$package" in ''|'#'*) continue ;; esac
    dpkg -s "$package" >/dev/null 2>&1 || missing+=("$package")
  done < "$REPO/configs/runtime/apt-packages.txt"
  if [ "${#missing[@]}" -eq 0 ]; then echo "[hệ thống] đủ gói apt"; return 0; fi
  echo "[hệ thống] thiếu ${#missing[@]} gói apt: ${missing[*]}"
  if [ "$USE_APT" = 1 ]; then
    [ "$(id -u)" = 0 ] || die "--apt cần quyền root (chạy bằng sudo)"
    apt-get install -y --no-install-recommends "${missing[@]}"
  else
    return 1
  fi
}

if [ "$CHECK_ONLY" = 1 ]; then check_system; exit $?; fi
[ -n "$GOC" ] || die "dùng: install.sh <gốc> [tuỳ chọn]; xem đầu file"
mkdir -p "$GOC"
GOC="$(cd "$GOC" && pwd)"
layout
TMP_DIR="$GOC/.install-tmp"
mkdir -p "$TMP_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

check_system || echo "[hệ thống] cài thiếu gói bằng: sudo $0 $GOC --check-system --apt" >&2

selected=()
for component in "${ALL[@]}"; do
  if [ -n "$ONLY" ] && ! [[ ",$ONLY," == *",$component,"* ]]; then continue; fi
  if [ -n "$SKIP" ] && [[ ",$SKIP," == *",$component,"* ]]; then continue; fi
  selected+=("$component")
done

ready=()
for component in "${selected[@]}"; do
  recipe="$(recipe_"$component")"
  if verify_"$component" && stamp_ok "$component" "$recipe"; then
    echo "[bỏ qua] $component: đã cài đúng công thức"
  elif verify_"$component"; then
    echo "[nhận ra] $component: đã có sẵn đúng phiên bản, không cài lại"
    write_stamp "$component" "$recipe"
  else
    echo "[cài] $component"
    install_"$component"
    verify_"$component" || die "cài $component xong nhưng kiểm không đạt"
    write_stamp "$component" "$recipe"
  fi
  ready+=("$component")
done

if [ "${#ready[@]}" -gt 0 ]; then
  write_runtime_env "$GOC/runtime.env" "${ready[@]}"
  echo "[ghi] $GOC/runtime.env (${#ready[@]} thành phần)"
fi
if [ "$NO_DOCTOR" = 0 ]; then
  bash "$REPO/scripts/gpu/doctor.sh" "$GOC"
fi
