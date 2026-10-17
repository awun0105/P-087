#!/usr/bin/env bash
# Odometry LiDAR (KISS-ICP) trong venv riêng, cài đúng bản khoá có hash.
recipe_lidar_odometry() { echo "lidar_odometry $(pin KISS_ICP_VERSION) $(sha_of "$REPO/requirements-lidar-odometry.lock.txt")"; }

verify_lidar_odometry() {
  [ -x "$LIDAR/bin/python" ] && [ "$("$LIDAR/bin/python" -c 'import importlib.metadata as m; print(m.version("kiss-icp"))' 2>/dev/null)" = "$(pin KISS_ICP_VERSION)" ]
}

install_lidar_odometry() {
  command -v python3 >/dev/null || die "không thấy python3"
  python3 -m venv "$LIDAR"
  "$LIDAR/bin/python" -m pip install --quiet --require-hashes -r "$REPO/requirements-lidar-odometry.lock.txt"
}
