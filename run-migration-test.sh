#!/usr/bin/env bash
set -euo pipefail

MC="${MC:-/home/minio_migration_package_20260313_141732/mc}"
WORK="${WORK:-/tmp/minio-migration-test}"
REPORT="$WORK/reports"
OLD1_ENDPOINT="${OLD1_ENDPOINT:-http://172.16.100.132:10100}"
OLD2_ENDPOINT="${OLD2_ENDPOINT:-http://172.16.100.56:9100}"
SW_ENDPOINT="${SW_ENDPOINT:-http://127.0.0.1:8333}"

: "${OLD_MINIO_USER:?OLD_MINIO_USER is required}"
: "${OLD_MINIO_PASSWORD:?OLD_MINIO_PASSWORD is required}"
: "${SW_ACCESS_KEY:?SW_ACCESS_KEY is required}"
: "${SW_SECRET_KEY:?SW_SECRET_KEY is required}"

mkdir -p "$REPORT/manifests" "$REPORT/conflicts" "$REPORT/logs" "$REPORT/checksum"

"$MC" alias set old1 "$OLD1_ENDPOINT" "$OLD_MINIO_USER" "$OLD_MINIO_PASSWORD" --api S3v4 >/dev/null
"$MC" alias set old2 "$OLD2_ENDPOINT" "$OLD_MINIO_USER" "$OLD_MINIO_PASSWORD" --api S3v4 >/dev/null
"$MC" alias set sw "$SW_ENDPOINT" "$SW_ACCESS_KEY" "$SW_SECRET_KEY" --api S3v4 >/dev/null

echo "__SOURCE_MANIFESTS__"
for SRC in old1 old2; do
  for BUCKET in legacy-a legacy-b legacy-conflict; do
    "$MC" ls --recursive --json "$SRC/$BUCKET" \
      | jq -r 'select(.key != null) | [.key, .size] | @tsv' \
      | LC_ALL=C sort > "$REPORT/manifests/$SRC.$BUCKET.manifest"
    count=$(wc -l < "$REPORT/manifests/$SRC.$BUCKET.manifest" | tr -d " ")
    bytes=$(awk -F '\t' '{sum += $2} END {print sum + 0}' "$REPORT/manifests/$SRC.$BUCKET.manifest")
    echo "$SRC/$BUCKET objects=$count bytes=$bytes"
  done
done

scan_conflicts() {
  local in_file="$1"
  local out_file="$2"

  cut -f1 "$in_file" | LC_ALL=C sort > "$out_file.keys.sorted"
  awk '
    NR > 1 && index($0, prev "/") == 1 {
      print "CONFLICT\t" prev "\t" $0
    }
    { prev=$0 }
  ' "$out_file.keys.sorted" > "$out_file"
}

echo "__CONFLICT_SCAN__"
for SRC in old1 old2; do
  for BUCKET in legacy-a legacy-b legacy-conflict; do
    scan_conflicts "$REPORT/manifests/$SRC.$BUCKET.manifest" "$REPORT/conflicts/$SRC.$BUCKET.key_conflicts.txt"
    conflicts=$(wc -l < "$REPORT/conflicts/$SRC.$BUCKET.key_conflicts.txt" | tr -d " ")
    echo "$SRC/$BUCKET conflicts=$conflicts"
  done
done
printf "a/b\t1\na/b/c\t1\n" > "$REPORT/manifests/synthetic.conflict.manifest"
scan_conflicts "$REPORT/manifests/synthetic.conflict.manifest" "$REPORT/conflicts/synthetic.key_conflicts.txt"
echo "synthetic conflicts=$(wc -l < "$REPORT/conflicts/synthetic.key_conflicts.txt" | tr -d " ")"
cat "$REPORT/conflicts/synthetic.key_conflicts.txt"

echo "__MIRROR__"
for PAIR in \
  "old1 legacy-a old1-legacy-a" \
  "old1 legacy-b old1-legacy-b" \
  "old2 legacy-a old2-legacy-a" \
  "old2 legacy-b old2-legacy-b"
do
  set -- $PAIR
  SRC="$1"
  SRC_BUCKET="$2"
  DST_BUCKET="$3"

  "$MC" rb --force "sw/$DST_BUCKET" >/dev/null 2>&1 || true
  "$MC" mb "sw/$DST_BUCKET" >/dev/null
  "$MC" mirror --overwrite --retry --summary "$SRC/$SRC_BUCKET" "sw/$DST_BUCKET" \
    2>&1 | tee "$REPORT/logs/mirror.$SRC.$SRC_BUCKET.log"
done

echo "__TARGET_MANIFESTS_AND_DIFFS__"
for DST_BUCKET in old1-legacy-a old1-legacy-b old2-legacy-a old2-legacy-b; do
  "$MC" ls --recursive --json "sw/$DST_BUCKET" \
    | jq -r 'select(.key != null) | [.key, .size] | @tsv' \
    | LC_ALL=C sort > "$REPORT/manifests/sw.$DST_BUCKET.manifest"
done

diff -u "$REPORT/manifests/old1.legacy-a.manifest" "$REPORT/manifests/sw.old1-legacy-a.manifest" > "$REPORT/manifests/diff.old1.legacy-a.txt" || true
diff -u "$REPORT/manifests/old1.legacy-b.manifest" "$REPORT/manifests/sw.old1-legacy-b.manifest" > "$REPORT/manifests/diff.old1.legacy-b.txt" || true
diff -u "$REPORT/manifests/old2.legacy-a.manifest" "$REPORT/manifests/sw.old2-legacy-a.manifest" > "$REPORT/manifests/diff.old2.legacy-a.txt" || true
diff -u "$REPORT/manifests/old2.legacy-b.manifest" "$REPORT/manifests/sw.old2-legacy-b.manifest" > "$REPORT/manifests/diff.old2.legacy-b.txt" || true

for DIFF in "$REPORT"/manifests/diff.*.txt; do
  if [ -s "$DIFF" ]; then
    echo "DIFF_NONEMPTY $DIFF"
  else
    echo "DIFF_EMPTY $DIFF"
  fi
done

checksum_one_pair() {
  local src_alias="$1"
  local src_bucket="$2"
  local dst_bucket="$3"
  local result_file="$4"
  local sample_file="$REPORT/checksum/$src_alias.$src_bucket.sample.keys"

  cut -f1 "$REPORT/manifests/$src_alias.$src_bucket.manifest" > "$sample_file"
  : > "$result_file"
  mkdir -p "$WORK/check/old" "$WORK/check/new"

  while IFS= read -r key; do
    old_file="$WORK/check/old/object"
    new_file="$WORK/check/new/object"
    "$MC" cp "$src_alias/$src_bucket/$key" "$old_file" >/dev/null
    "$MC" cp "sw/$dst_bucket/$key" "$new_file" >/dev/null
    old_sha=$(sha256sum "$old_file" | awk '{print $1}')
    new_sha=$(sha256sum "$new_file" | awk '{print $1}')
    if [ "$old_sha" = "$new_sha" ]; then
      echo -e "PASS\t$key\t$old_sha" >> "$result_file"
    else
      echo -e "FAIL\t$key\told=$old_sha\tnew=$new_sha" >> "$result_file"
    fi
  done < "$sample_file"
}

echo "__CHECKSUM__"
checksum_one_pair old1 legacy-a old1-legacy-a "$REPORT/checksum/old1.legacy-a.sha256.tsv"
checksum_one_pair old1 legacy-b old1-legacy-b "$REPORT/checksum/old1.legacy-b.sha256.tsv"
checksum_one_pair old2 legacy-a old2-legacy-a "$REPORT/checksum/old2.legacy-a.sha256.tsv"
checksum_one_pair old2 legacy-b old2-legacy-b "$REPORT/checksum/old2.legacy-b.sha256.tsv"

if grep -R '^FAIL' "$REPORT/checksum"/*.sha256.tsv; then
  echo "CHECKSUM_FAILED"
  exit 3
else
  echo "CHECKSUM_ALL_PASS"
fi

echo "__REPORT_FILES__"
find "$REPORT" -type f | sort
