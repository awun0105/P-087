# Mock job fixture

`input_manifest.json` và `job_manifest.json` tuân shared manifest contracts, phục vụ orchestration development mà không giả lập worker business logic.
File input khai báo `data_class: product_input`; stage output khai báo
`data_class: derived`. Product manifest không được nhận raw GT/evaluation-only
chỉ vì URI trông như ordinary input.

`scene_revision_states.json` là chuỗi snapshot workflow mẫu để EX-PRODUCT dựng
job/review UI: DRAFT → CANDIDATE_READY → READY_FOR_REVIEW → APPROVED → edit tạo
rev-002 DRAFT và không kế thừa validation/approval. Mỗi entry deserialize được
thành `SceneRevisionRecord`; đây là fixture hiển thị/test, không phải audit log,
human approval thật hoặc real release.
`processing_config.json` có byte checksum thật trong Job/Candidate. Published
input manifest copy dưới `artifact_store/` có byte hash riêng, khác canonical
`input_manifest_checksum`. `approval_record.json` là synthetic review identity
để kiểm lineage, không chứng minh reviewer authorization.
