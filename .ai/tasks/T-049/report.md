# T-049 report
- `jobs/database.py`: `is_transient_database_error` (sqlite locked/busy, psycopg Operational/InterfaceError, ConnectionError, TimeoutError). Không đổi pool kết nối của phiên khác.
- `jobs/heartbeat.py`: `HeartbeatTolerance(ttl)` — chịu lỗi thoáng qua tới 2/3 TTL kể từ lần thành công.
- Áp vào: heartbeat tách vật (`objectify_queue._start_heartbeat`), heartbeat kiểm định (`_ValidationHeartbeat._run`, TTL = `queue.lease_ttl`), vòng poll `_run_tool` (TTL = `LEASE_TTL`).
- `retryability`: thêm `OperationalError`, `InterfaceError` vào lỗi tạm thời.
- Test mới: test_heartbeat_tolerance (6), 2 test heartbeat tách vật, 2 test heartbeat kiểm định, test_runner_db_blip (2).
