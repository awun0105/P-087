# Candidate fixture

`candidate_package.json` chứa manifest/entrypoint USD/geometry/collider refs
đều resolve và verify SHA-256. `candidate_checksum` là canonical hash của toàn
package contract loại trừ self field; không phải hash riêng của USD. USD payload
chỉ là synthetic test content, không phải Isaac/OpenUSD runtime acceptance.
