# Evidence T-019

Các log là output thực của ngày 16/10/2026; baseline, focused và recheck là những lượt riêng.

- `backend.txt`: full baseline, 3502 passed / 28 skipped / 1 failed; failure guard được sửa sau khi lượt này bắt đầu.
- `frontend-initial.txt`, `frontend.txt`: trước và sau sửa palette; full cuối 839 passed.
- `geometry-initial.txt`, `geometry-recheck.txt`, `draft-guard.txt`, `queue.txt`, `package.txt`: regression và recheck cụ thể.
- `preview-300k.txt`: budget fail được giữ nguyên. `preview-benchmark.txt`, `preview-profile.txt`: hai lượt benchmark 2M.
- `review-probes.txt`, `inpaint-valid-probe.txt`: probe xác nhận hành vi lỗi; PASS ở đây nghĩa là tái hiện được bug.
- `static-checks.txt`, `graphify.txt`, `palette.txt`: output kiểm tra bổ sung.

Hai file `*.py.txt` giữ script chẩn đoán để tái hiện, không được collect như test nghiệm thu của repo. Script probe assert
hành vi lỗi đã quan sát; sau khi sửa bug, phải thay bằng regression test kiểm hành vi mong muốn.

Chạy script benchmark từ repo root sau khi copy `preview-benchmark.py.txt` ra một file `.py` trong `/tmp`:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH="$PWD" .venv/bin/python /tmp/preview-benchmark.py
```

Tương tự, copy `review-probes.py.txt` ra `/tmp/test_review_probes.py`, rồi chạy:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m pytest /tmp/test_review_probes.py -q -s
```

Probe dùng fixture/helper của checkout hiện tại; kết quả có thể đổi sau khi fixture/helper thay đổi. Benchmark stub floor
fitting và dùng 7-field Gaussian rows; không chứng minh latency hoặc chất lượng scene thật.
