#!/usr/bin/env bash
set -euo pipefail

WORK="${WORK:?set WORK to the existing delete-smoke work directory}"
RUN_ID="$(basename "${WORK}")"
MCIMG="${MCIMG:-quay.io/minio/mc:RELEASE.2023-12-23T08-47-21Z}"

SOURCE_ALIAS="a380src"
COLD_ALIAS="cold4070"
SOURCE_ENDPOINT="http://172.16.100.132:9000"
COLD_ENDPOINT="http://172.16.100.217:9000"
SOURCE_BUCKET="sucaiwang"
SOURCE_PREFIX="sucaiwang/codex-delete-smoke/20260608/${RUN_ID}"
VERIFY_KEY="${SOURCE_PREFIX}/verify.bin"
DELETE_KEY="${SOURCE_PREFIX}/delete.bin"
COLD_BUCKET="tier-a380-delete-smoke-20260608"
COLD_PREFIX="a380-9000/sucaiwang/delete-smoke-20260608/${RUN_ID}/"
TIER_NAME="COLD_4070_DELETE_SMOKE_20260608_${RUN_ID##*-}"

mc() {
  docker run --rm --network host -v "${WORK}/mc:/root/.mc" -v "${WORK}:${WORK}" "${MCIMG}" "$@"
}

http_code() {
  curl -sS -L -r 0-0 -o /dev/null -w "%{http_code}" --max-time 15 "$1" || true
}

echo "RESUME_RUN_ID=${RUN_ID}"
echo "WORK=${WORK}"
echo "VERIFY_KEY=${VERIFY_KEY}"
echo "DELETE_KEY=${DELETE_KEY}"
echo "TIER_NAME=${TIER_NAME}"

mc ilm rule export "${SOURCE_ALIAS}/${SOURCE_BUCKET}" > "${WORK}/evidence/lifecycle-before-cleanup.json"
python3 - "${WORK}/evidence/lifecycle-before-cleanup.json" "${SOURCE_PREFIX}/" "${TIER_NAME}" > "${WORK}/evidence/rule-ids-to-remove.txt" <<'PY'
import json
import sys

path, prefix, tier = sys.argv[1:4]
raw = open(path).read().strip()
rules = json.loads(raw).get("Rules", [])
for rule in rules:
    rid = rule.get("ID")
    rprefix = (rule.get("Filter") or {}).get("Prefix")
    storage_class = (rule.get("Transition") or {}).get("StorageClass")
    if rid and rprefix == prefix and storage_class == tier:
        print(rid)
PY

while IFS= read -r rule_id; do
  [[ -z "${rule_id}" ]] && continue
  mc ilm rule rm "${SOURCE_ALIAS}/${SOURCE_BUCKET}" --id "${rule_id}" >/dev/null
  echo "RULE_REMOVED=${rule_id}"
done < "${WORK}/evidence/rule-ids-to-remove.txt"

mc ls --recursive --json "${COLD_ALIAS}/${COLD_BUCKET}/${COLD_PREFIX}" > "${WORK}/evidence/cold-after-transition.jsonl"
python3 - "${WORK}/evidence/cold-after-transition.jsonl" > "${WORK}/evidence/cold-candidates.tsv" <<'PY'
import json
import sys

for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    row = json.loads(line)
    if row.get("type") == "file":
        print(f"{row.get('key')}\t{row.get('size')}")
PY

verify_sha="$(sha256sum "${WORK}/files/verify.bin" | awk '{print $1}')"
delete_sha="$(sha256sum "${WORK}/files/delete.bin" | awk '{print $1}')"
: > "${WORK}/evidence/mapping.tsv"
while IFS=$'\t' read -r cold_key cold_size; do
  [[ -z "${cold_key}" ]] && continue
  full_cold_key="${COLD_PREFIX}${cold_key}"
  cold_sha="$(mc cat "${COLD_ALIAS}/${COLD_BUCKET}/${full_cold_key}" | sha256sum | awk '{print $1}')"
  if [[ "${cold_sha}" == "${verify_sha}" ]]; then
    printf 'verify\t%s\t%s\t%s\t%s\n' "${VERIFY_KEY}" "${verify_sha}" "${full_cold_key}" "${cold_size}" >> "${WORK}/evidence/mapping.tsv"
  elif [[ "${cold_sha}" == "${delete_sha}" ]]; then
    printf 'delete\t%s\t%s\t%s\t%s\n' "${DELETE_KEY}" "${delete_sha}" "${full_cold_key}" "${cold_size}" >> "${WORK}/evidence/mapping.tsv"
  fi
done < "${WORK}/evidence/cold-candidates.tsv"

verify_cold_key="$(awk -F '\t' '$1=="verify"{print $4}' "${WORK}/evidence/mapping.tsv")"
delete_cold_key="$(awk -F '\t' '$1=="delete"{print $4}' "${WORK}/evidence/mapping.tsv")"
if [[ -z "${verify_cold_key}" || -z "${delete_cold_key}" ]]; then
  echo "MAPPING_FAILED=1" >&2
  cat "${WORK}/evidence/mapping.tsv" >&2
  exit 3
fi

VERIFY_SOURCE_URL="${SOURCE_ENDPOINT}/${SOURCE_BUCKET}/${VERIFY_KEY}"
VERIFY_COLD_URL="${COLD_ENDPOINT}/${COLD_BUCKET}/${verify_cold_key}"
DELETE_SOURCE_URL="${SOURCE_ENDPOINT}/${SOURCE_BUCKET}/${DELETE_KEY}"
DELETE_COLD_URL="${COLD_ENDPOINT}/${COLD_BUCKET}/${delete_cold_key}"

echo "VERIFY_SOURCE_URL=${VERIFY_SOURCE_URL}"
echo "VERIFY_COLD_URL=${VERIFY_COLD_URL}"
echo "DELETE_SOURCE_URL=${DELETE_SOURCE_URL}"
echo "DELETE_COLD_URL=${DELETE_COLD_URL}"
echo "VERIFY_SOURCE_TRANSITIONED_CODE=$(http_code "${VERIFY_SOURCE_URL}")"
echo "VERIFY_COLD_TRANSITIONED_CODE=$(http_code "${VERIFY_COLD_URL}")"
echo "DELETE_SOURCE_TRANSITIONED_CODE=$(http_code "${DELETE_SOURCE_URL}")"
echo "DELETE_COLD_TRANSITIONED_CODE=$(http_code "${DELETE_COLD_URL}")"

mc rm "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}" >/dev/null
echo "SOURCE_DELETE_ISSUED=OK"

deadline=$((SECONDS + 300))
source_deleted=0
cold_deleted=0
while (( SECONDS < deadline )); do
  source_code="$(http_code "${DELETE_SOURCE_URL}")"
  cold_code="$(http_code "${DELETE_COLD_URL}")"
  echo "DELETE_WAIT elapsed=${SECONDS}s source=${source_code} cold=${cold_code}"
  [[ "${source_code}" == "404" ]] && source_deleted=1
  [[ "${cold_code}" == "404" ]] && cold_deleted=1
  [[ "${source_deleted}" == "1" && "${cold_deleted}" == "1" ]] && break
  sleep 10
done

echo "DELETE_SOURCE_FINAL_CODE=$(http_code "${DELETE_SOURCE_URL}")"
echo "DELETE_COLD_FINAL_CODE=$(http_code "${DELETE_COLD_URL}")"
echo "VERIFY_SOURCE_FINAL_CODE=$(http_code "${VERIFY_SOURCE_URL}")"
echo "VERIFY_COLD_FINAL_CODE=$(http_code "${VERIFY_COLD_URL}")"
echo "MAPPING_TSV=${WORK}/evidence/mapping.tsv"
echo "RESULT_WORK=${WORK}"

if [[ "${source_deleted}" != "1" || "${cold_deleted}" != "1" ]]; then
  echo "DELETE_SMOKE=FAIL"
  exit 4
fi

echo "DELETE_SMOKE=PASS"
