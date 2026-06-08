#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-delete-smoke-20260608-$(date +%H%M%S)}"
WORK="${WORK:-/root/${RUN_ID}}"
A380_CONFIG="${A380_CONFIG:-/root/a380-mc-config-delete-smoke.json}"
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

mkdir -p "${WORK}/mc" "${WORK}/files" "${WORK}/evidence"
cp "${A380_CONFIG}" "${WORK}/mc/config.json"
chmod 700 "${WORK}/mc"
chmod 600 "${WORK}/mc/config.json"

python3 - "${WORK}/mc/config.json" <<PY
import json
import sys

path = sys.argv[1]
with open(path) as f:
    data = json.load(f)

aliases = data.setdefault("aliases", {})
source = aliases.get("hot_minio") or aliases.get("local")
cold = aliases.get("cold_minio")
if not source or not cold:
    raise SystemExit("missing local/hot_minio or cold_minio aliases")

source = dict(source)
source["url"] = "${SOURCE_ENDPOINT}"
aliases["${SOURCE_ALIAS}"] = source

cold = dict(cold)
cold["url"] = "${COLD_ENDPOINT}"
aliases["${COLD_ALIAS}"] = cold

with open(path, "w") as f:
    json.dump(data, f, indent="\t")
PY

mc() {
  docker run --rm --network host -v "${WORK}/mc:/root/.mc" -v "${WORK}:${WORK}" "${MCIMG}" "$@"
}

storage_class() {
  mc stat --json "$1" | python3 -c '
import json, sys
d=json.load(sys.stdin)
m=d.get("metadata") or {}
print(d.get("storageClass") or d.get("StorageClass") or m.get("X-Amz-Storage-Class") or m.get("X-Amz-Storage-Class".lower()) or "STANDARD")
'
}

http_code() {
  curl -sS -L -r 0-0 -o /dev/null -w "%{http_code}" --max-time 15 "$1" || true
}

get_config_value() {
  python3 - "${WORK}/mc/config.json" "$1" "$2" <<'PY'
import json
import sys

path, alias, field = sys.argv[1:4]
with open(path) as f:
    data = json.load(f)
print((data.get("aliases") or {}).get(alias, {}).get(field, ""))
PY
}

echo "RUN_ID=${RUN_ID}"
echo "WORK=${WORK}"
echo "SOURCE_BUCKET=${SOURCE_BUCKET}"
echo "VERIFY_KEY=${VERIFY_KEY}"
echo "DELETE_KEY=${DELETE_KEY}"
echo "COLD_BUCKET=${COLD_BUCKET}"
echo "COLD_PREFIX=${COLD_PREFIX}"
echo "TIER_NAME=${TIER_NAME}"

mc --version
mc stat "${SOURCE_ALIAS}/${SOURCE_BUCKET}" >/dev/null
mc admin info "${COLD_ALIAS}" >/dev/null
echo "CONNECTIVITY=OK"

dd if=/dev/urandom of="${WORK}/files/verify.bin" bs=1M count=8 status=none
dd if=/dev/urandom of="${WORK}/files/delete.bin" bs=1M count=8 status=none
sha256sum "${WORK}/files/verify.bin" "${WORK}/files/delete.bin" | tee "${WORK}/evidence/source-sha256.txt"

mc cp "${WORK}/files/verify.bin" "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}" >/dev/null
mc cp "${WORK}/files/delete.bin" "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}" >/dev/null
echo "SOURCE_PUT=OK"

VERIFY_SOURCE_URL="${SOURCE_ENDPOINT}/${SOURCE_BUCKET}/${VERIFY_KEY}"
DELETE_SOURCE_URL="${SOURCE_ENDPOINT}/${SOURCE_BUCKET}/${DELETE_KEY}"

echo "VERIFY_SOURCE_PRE_CODE=$(http_code "${VERIFY_SOURCE_URL}")"
echo "DELETE_SOURCE_PRE_CODE=$(http_code "${DELETE_SOURCE_URL}")"

mc mb -p "${COLD_ALIAS}/${COLD_BUCKET}" >/dev/null
mc anonymous set download "${COLD_ALIAS}/${COLD_BUCKET}" >/dev/null

COLD_ACCESS_KEY="$(get_config_value "${COLD_ALIAS}" "accessKey")"
COLD_SECRET_KEY="$(get_config_value "${COLD_ALIAS}" "secretKey")"
if [[ -z "${COLD_ACCESS_KEY}" || -z "${COLD_SECRET_KEY}" ]]; then
  echo "missing cold tier credentials" >&2
  exit 1
fi

mc ilm tier add minio "${SOURCE_ALIAS}" "${TIER_NAME}" \
  --endpoint "${COLD_ENDPOINT}" \
  --access-key "${COLD_ACCESS_KEY}" \
  --secret-key "${COLD_SECRET_KEY}" \
  --bucket "${COLD_BUCKET}" \
  --prefix "${COLD_PREFIX}" >/dev/null

mc ilm rule add "${SOURCE_ALIAS}/${SOURCE_BUCKET}" \
  --prefix "${SOURCE_PREFIX}/" \
  --transition-days 0 \
  --transition-tier "${TIER_NAME}" >/dev/null

echo "TIER_AND_RULE=OK"

deadline=$((SECONDS + 1800))
transitioned=0
while (( SECONDS < deadline )); do
  verify_sc="$(storage_class "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}")"
  delete_sc="$(storage_class "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}")"
  echo "WAIT elapsed=${SECONDS}s verify=${verify_sc} delete=${delete_sc}"
  if [[ "${verify_sc}" == "${TIER_NAME}" && "${delete_sc}" == "${TIER_NAME}" ]]; then
    transitioned=1
    break
  fi
  sleep 30
done

if [[ "${transitioned}" != "1" ]]; then
  echo "TRANSITION_TIMEOUT=1" >&2
  exit 2
fi

echo "TRANSITION=OK"

mc ilm rule export "${SOURCE_ALIAS}/${SOURCE_BUCKET}" > "${WORK}/evidence/lifecycle-before-cleanup.xml"
python3 - "${WORK}/evidence/lifecycle-before-cleanup.xml" "${SOURCE_PREFIX}/" "${TIER_NAME}" > "${WORK}/evidence/rule-ids-to-remove.txt" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET

path, prefix, tier = sys.argv[1:4]
raw = open(path).read().strip()

rules = []
if raw.startswith("{"):
    rules = json.loads(raw).get("Rules", [])
else:
    root = ET.fromstring(raw)
    for rule in root.findall(".//Rule"):
        rules.append({
            "ID": rule.findtext("ID"),
            "Filter": {"Prefix": rule.findtext("Filter/Prefix")},
            "Transition": {"StorageClass": rule.findtext("Transition/StorageClass")},
        })

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

VERIFY_COLD_URL="${COLD_ENDPOINT}/${COLD_BUCKET}/${verify_cold_key}"
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
cold_deleted=0
source_deleted=0
while (( SECONDS < deadline )); do
  source_code="$(http_code "${DELETE_SOURCE_URL}")"
  cold_code="$(http_code "${DELETE_COLD_URL}")"
  echo "DELETE_WAIT elapsed=${SECONDS}s source=${source_code} cold=${cold_code}"
  if [[ "${source_code}" == "404" ]]; then
    source_deleted=1
  fi
  if [[ "${cold_code}" == "404" ]]; then
    cold_deleted=1
  fi
  if [[ "${source_deleted}" == "1" && "${cold_deleted}" == "1" ]]; then
    break
  fi
  sleep 10
done

echo "DELETE_SOURCE_FINAL_CODE=$(http_code "${DELETE_SOURCE_URL}")"
echo "DELETE_COLD_FINAL_CODE=$(http_code "${DELETE_COLD_URL}")"
echo "VERIFY_SOURCE_FINAL_CODE=$(http_code "${VERIFY_SOURCE_URL}")"
echo "VERIFY_COLD_FINAL_CODE=$(http_code "${VERIFY_COLD_URL}")"
echo "MAPPING_TSV=${WORK}/evidence/mapping.tsv"
echo "LIFECYCLE_XML=${WORK}/evidence/lifecycle-before-cleanup.xml"
echo "RESULT_WORK=${WORK}"

if [[ "${source_deleted}" != "1" || "${cold_deleted}" != "1" ]]; then
  echo "DELETE_SMOKE=FAIL"
  exit 4
fi

echo "DELETE_SMOKE=PASS"
