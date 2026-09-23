# ValidationReport fixture

`validation_report.json` bind vào synthetic `candidate/candidate_package.json`
bằng package checksum thật. `failed_validation_report.json` cho EX-PRODUCT
failure UI (FAIL check + ERROR path). Mỗi `report_checksum` là canonical content
hash loại trừ chính field đó; evidence refs dùng exact byte SHA-256. Đây là
fixture contract/integration proof, không phải bằng chứng Isaac validation thật.
