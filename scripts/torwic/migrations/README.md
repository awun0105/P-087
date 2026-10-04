# Migration dữ liệu TorWIC một lần

Script chuyển layout dữ liệu REC-01 cũ (`data/torwic_slam_rec01/`) sang layout
`data/torwic_slam/{normalized,derived,evaluation_only}/` (xem REC-01). Đã chạy
xong trên máy owner; giữ lại để tái lập khi có checkout dữ liệu cũ.

Chạy từ root repo vì đường dẫn trong script là tương đối:

```bash
python scripts/torwic/migrations/rec01_merge.py
bash scripts/torwic/migrations/rec01_merge.sh
```
