#!/usr/bin/env bash
# =====================================================================
# Chatty-sp: FULL133 起動 PoC の実機確認用プレビューのバックエンド（Cloud Shell）
#
#   bash ~/chatty_preview_backend.sh            追加（トラフィック 0%・タグ f133pv）
#   bash ~/chatty_preview_backend.sh remove     タグ f133pv を外す（トラフィックは変えない）
#
# - 土台は「今 100% を受けている本番リビジョン」のイメージそのもの（digest 固定）。
#   変えるのは /app/app_customer_support.py の allowed_origins にプレビューの URL を 1 行足すことだけ
#   （依存の再インストール・コードの再ビルドはしない。docs/22 §5.1 の再ビルドの危険を避ける）
# - 新しいリビジョンは --no-traffic・タグ f133pv・最大 1 インスタンス。本番トラフィックは変えない
# - 本番トラフィックが「最新のリビジョンに追従」の場合は、--no-traffic で固定に変わってしまうので、何もせずに止まる
# - 環境変数の値は読まない・表示しない（名前と Secret 参照だけで確認する）
# =====================================================================
set -euo pipefail
PROJECT_ID="ai-avator-492205"
REGION="us-central1"
SERVICE="chatty-sp-base"
TAG="f133pv"
PREVIEW_ORIGIN="https://chatty-sp-git-preview-full133-mirais-projects-87257550.vercel.app"
EXPECTED_TAG_URL="https://${TAG}---chatty-sp-base-fmfxldo6kq-uc.a.run.app"
GC=(--project="${PROJECT_ID}" --region="${REGION}")
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
SVC_FMT='json(status.traffic,status.latestCreatedRevisionName,spec.template.spec.containers[0].env[].name,spec.template.spec.containers[0].env[].valueFrom)'

if [ "${1:-}" = "remove" ]; then
  gcloud run services describe "${SERVICE}" "${GC[@]}" --format='json(status.traffic)' > "${WORK}/b.json"
  if python3 -c "import json,sys; sys.exit(0 if any(t.get('tag')=='${TAG}' for t in json.load(open('${WORK}/b.json'))['status']['traffic']) else 1)"; then
    gcloud run services update-traffic "${SERVICE}" "${GC[@]}" --remove-tags="${TAG}" --quiet > /dev/null
  fi
  gcloud run services describe "${SERVICE}" "${GC[@]}" --format='json(status.traffic)' > "${WORK}/a.json"
  python3 - "${WORK}/b.json" "${WORK}/a.json" "${TAG}" <<'PYEOF'
import json, sys
b, a = (json.load(open(p))['status']['traffic'] for p in sys.argv[1:3])
live = lambda t: [(x.get('revisionName'), x.get('percent'), bool(x.get('latestRevision'))) for x in t if x.get('percent')]
ok = live(b) == live(a) and not any(x.get('tag') == sys.argv[3] for x in a)
print('    本番トラフィック:', live(a), '（変更なし）' if live(b) == live(a) else '（NG: 変わっています）')
print('完了: タグを外しました' if ok else 'NG')
sys.exit(0 if ok else 1)
PYEOF
  exit 0
fi

echo "[1/4] 事前確認（読み取りのみ）"
gcloud run services describe "${SERVICE}" "${GC[@]}" --format="${SVC_FMT}" > "${WORK}/svc_before.json"
python3 - "${WORK}/svc_before.json" "${WORK}" <<'PYEOF'
import json, sys
svc, work = json.load(open(sys.argv[1])), sys.argv[2]
st = svc['status']
live = [t for t in st['traffic'] if t.get('percent')]
if len(live) != 1 or live[0].get('percent') != 100:
    sys.exit('停止: 本番トラフィックが 1 つのリビジョンに 100% ではありません（何も変更しません）')
if live[0].get('latestRevision'):
    sys.exit('停止: 本番トラフィックが「最新のリビジョンに追従」です。--no-traffic の追加で固定に変わるため、何も変更しません')
rev = live[0]['revisionName']
if st.get('latestCreatedRevisionName') != rev:
    sys.exit(f'停止: サービスの設定（最新 {st.get("latestCreatedRevisionName")}）が本番リビジョン {rev} と別のものです（何も変更しません）')
open(f'{work}/prod_rev', 'w').write(rev)
print(f'    本番トラフィック: {rev} 100%（固定）')
PYEOF
PROD_REV="$(cat "${WORK}/prod_rev")"
gcloud run revisions describe "${PROD_REV}" "${GC[@]}" --format='json(spec.containers[0].image,spec.containers[0].env[].name,spec.containers[0].env[].valueFrom)' > "${WORK}/prod.json"
python3 - "${WORK}/svc_before.json" "${WORK}/prod.json" "${WORK}" <<'PYEOF'
import json, sys
svc, prod, work = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3]
names = lambda env: sorted((e['name'], json.dumps(e.get('valueFrom'), sort_keys=True)) for e in env or [])
t = names(svc['spec']['template']['spec']['containers'][0].get('env'))
p = names(prod['spec']['containers'][0].get('env'))
if t != p:
    sys.exit('停止: サービスの設定と本番リビジョンの環境変数の名前・Secret 参照が違います（何も変更しません）')
img = prod['spec']['containers'][0]['image']
if '@sha256:' not in img:
    sys.exit(f'停止: 本番リビジョンのイメージが digest で固定されていません: {img}')
open(f'{work}/prod_image', 'w').write(img)
print(f'    本番リビジョンのイメージ: {img.split("/")[-1]}')
print(f'    環境変数の名前・Secret 参照: サービスの設定と本番リビジョンで同じ（{len(p)} 個）')
PYEOF
PROD_IMAGE="$(cat "${WORK}/prod_image")"
REPO="${PROD_IMAGE%@*}"
NEW_IMAGE="${REPO}:preview-${TAG}-$(date +%Y%m%d%H%M)"

echo "[2/4] 本番リビジョンのイメージにプレビューの接続先を 1 行足してビルド（Cloud Build）"
mkdir -p "${WORK}/build"
cat > "${WORK}/build/add_preview_origin.py" <<'PYEOF'
import ast, sys
path, origin = sys.argv[1], sys.argv[2]
s = open(path, encoding='utf-8').read()
anchor = '    "https://chatty-sp.vercel.app",\n'
if s.count(anchor) != 1:
    sys.exit('allowed_origins に https://chatty-sp.vercel.app の行が 1 つではありません')
if origin in s:
    sys.exit('プレビューの接続先はすでに入っています')
s = s.replace(anchor, anchor + f'    "{origin}",  # FULL133 起動 PoC の実機確認用プレビュー（本番に merge しない）\n')
ast.parse(s)
open(path, 'w', encoding='utf-8').write(s)
print('allowed_origins にプレビューの接続先を追加しました')
PYEOF
cat > "${WORK}/build/Dockerfile" <<EOF
FROM ${PROD_IMAGE}
COPY add_preview_origin.py /tmp/add_preview_origin.py
RUN python3 /tmp/add_preview_origin.py /app/app_customer_support.py "${PREVIEW_ORIGIN}" && rm /tmp/add_preview_origin.py
EOF
gcloud builds submit "${WORK}/build" --project="${PROJECT_ID}" --region="${REGION}" --tag="${NEW_IMAGE}" --quiet > "${WORK}/build.log" 2>&1 \
  || { echo "停止: Cloud Build に失敗しました（Cloud Run は未変更）:" >&2; tail -n 15 "${WORK}/build.log" >&2; exit 1; }
DIGEST="$(gcloud artifacts docker images describe "${NEW_IMAGE}" --format='value(image_summary.digest)')"
[ -n "${DIGEST}" ] || { echo "停止: イメージの digest を取得できません（Cloud Run は未変更）" >&2; exit 1; }
echo "    ${NEW_IMAGE##*/} → ${DIGEST:0:19}..."

echo "[3/4] デプロイ直前の再確認と追加（--no-traffic --tag=${TAG} --max-instances=1）"
gcloud run services describe "${SERVICE}" "${GC[@]}" --format="${SVC_FMT}" > "${WORK}/svc_recheck.json"
python3 - "${WORK}/svc_before.json" "${WORK}/svc_recheck.json" <<'PYEOF'
import json, sys
a, b = (json.load(open(p))['status']['traffic'] for p in sys.argv[1:3])
if a != b:
    sys.exit('停止: 事前確認の後にトラフィックの設定が変わりました。追加しません')
PYEOF
NEW_REV="${SERVICE}-${TAG}-$(date +%m%d%H%M)"
gcloud run deploy "${SERVICE}" "${GC[@]}" --platform=managed --image="${REPO}@${DIGEST}" \
  --no-traffic --tag="${TAG}" --revision-suffix="${NEW_REV#${SERVICE}-}" --max-instances=1 --quiet > "${WORK}/deploy.log" 2>&1 \
  || { echo "停止: 追加に失敗しました（トラフィックは変更していません）:" >&2; tail -n 20 "${WORK}/deploy.log" >&2; exit 1; }

echo "[4/4] 事後確認"
gcloud run services describe "${SERVICE}" "${GC[@]}" --format="${SVC_FMT}" > "${WORK}/svc_after.json"
gcloud run revisions describe "${NEW_REV}" "${GC[@]}" --format='json(spec.containers[0].image,spec.containers[0].env[].name,spec.containers[0].env[].valueFrom)' > "${WORK}/new.json"
python3 - "${WORK}/svc_before.json" "${WORK}/svc_after.json" "${WORK}/prod.json" "${WORK}/new.json" "${TAG}" "${NEW_REV}" "${WORK}" <<'PYEOF'
import json, sys
before, after, prod, new = (json.load(open(p)) for p in sys.argv[1:5])
tag, new_rev, work = sys.argv[5:8]
ok = True
live = lambda t: [(x.get('revisionName'), x.get('percent'), bool(x.get('latestRevision'))) for x in t if x.get('percent')]
if live(before['status']['traffic']) != live(after['status']['traffic']):
    print('NG: 本番トラフィックが変わっています'); ok = False
others = lambda t: {(x.get('tag'), x.get('revisionName')) for x in t if x.get('tag') and x.get('tag') != tag}
if others(before['status']['traffic']) != others(after['status']['traffic']):
    print('NG: ほかのタグが変わっています'); ok = False
mine = [x for x in after['status']['traffic'] if x.get('tag') == tag]
if len(mine) != 1 or mine[0].get('revisionName') != new_rev or mine[0].get('percent'):
    print(f'NG: タグ {tag} が新しいリビジョン（0%）を指していません'); ok = False
names = lambda env: sorted((e['name'], json.dumps(e.get('valueFrom'), sort_keys=True)) for e in env or [])
if names(prod['spec']['containers'][0].get('env')) != names(new['spec']['containers'][0].get('env')):
    print('NG: 新しいリビジョンの環境変数の名前・Secret 参照が本番と違います'); ok = False
open(f'{work}/tag_url', 'w').write((mine[0].get('url') if mine else '') or '')
if ok:
    print(f'    本番トラフィック: {live(after["status"]["traffic"])}（変更なし）／タグ {tag} → {new_rev}（0%）／環境変数: 本番と同じ名前')
sys.exit(0 if ok else 1)
PYEOF
TAG_URL="$(cat "${WORK}/tag_url")"
PROD_URL="$(gcloud run services describe "${SERVICE}" "${GC[@]}" --format='value(status.url)')"
H="$(curl -s -o /dev/null -w '%{http_code}' "${TAG_URL}/health")"
ALLOW_TAG="$(curl -s -o /dev/null -D - -H "Origin: ${PREVIEW_ORIGIN}" "${TAG_URL}/health" | tr -d '\r' | awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2}')"
ALLOW_PROD="$(curl -s -o /dev/null -D - -H "Origin: ${PREVIEW_ORIGIN}" "${PROD_URL}/health" | tr -d '\r' | awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2}')"
echo "    ${TAG_URL}/health → ${H}（200 なら正常）"
echo "    プレビューの接続先の許可: タグ → ${ALLOW_TAG:-なし}（許可されていれば正常）／本番 → ${ALLOW_PROD:-なし}（なしなら本番は変わっていない）"
[ "${H}" = "200" ] && [ "${ALLOW_TAG}" = "${PREVIEW_ORIGIN}" ] && [ -z "${ALLOW_PROD}" ] || { echo "NG: 事後確認に失敗しました（トラフィックは変更していません）。外す場合: bash ~/chatty_preview_backend.sh remove" >&2; exit 1; }
if [ "${TAG_URL}" != "${EXPECTED_TAG_URL}" ]; then
  echo "注意: タグの URL が想定（${EXPECTED_TAG_URL}）と違います。この URL を Claude に伝えてください: ${TAG_URL}"
fi
echo "完了: ${TAG_URL}（${NEW_REV}）。外す場合: bash ~/chatty_preview_backend.sh remove"
