# SceneIR fixture

`scene.json` có environment/floor, rack, pallet và collider references với
checksum resolvable để `EX-SIM` và `EX-PRODUCT` phát triển độc lập với
`EX-SCENE`. PLY/collider payload rất nhỏ, chỉ chứng minh contract shape và
handoff; chưa chứng minh scene decomposition hay physics trên Isaac.
`edited_scene.json` là rev-002: pallet giữ stable ID nhưng đổi transform; review
status nằm ngoài SceneIR. Hai `scene_ir_checksum` là canonical content hashes
khác nhau; checker verify optional visual ref ở revision edit.
