#!/usr/bin/env bash
# RAG-01V1 — temporary VM validation of referenced pgvector retrieval with the REAL OpenRouter embeddings API.
# Owner-run, ONE SSH session. stdin = <OpenRouter key line> + <git bundle>; the key travels only inside the
# encrypted SSH stream (never in any command's arguments), is written to a 600-mode file, and is deleted at cleanup:
#   { sed -n 's/^OPENROUTER_API_KEY=//p' ../../.env | tr -d '\r\n'; echo; cat raw/rag.bundle; } \
#     | ssh -p 9922 user@<VM> "EXPECTED_SHA=<commit>; BUNDLE_SHA256=<sha>; $(cat vm-validate.sh)" > raw/run.raw.log 2>&1
# Starts ONLY db + backend (n8n is not needed for RAG). Other secrets are generated on the VM. Nothing secret is
# printed. No chat/completions call. Loopback exposure only. The committed corpus is never modified; the
# 120 € -> 150 € demo uses a temporary copy. Full cleanup at the end.
set -u
: "${EXPECTED_SHA:?set EXPECTED_SHA}"; : "${BUNDLE_SHA256:?set BUNDLE_SHA256}"
export WORK="$HOME/nexo-rag01v1"
REPO="$WORK/repo"; LOG="$WORK/run.log"
FAILED=0
sec()  { printf '\n===== %s =====\n' "$1"; }
run()  { printf '$ %s\n' "$*"; "$@" 2>&1 || { rc=$?; printf '(exit %s)\n' "$rc"; return $rc; }; }
check(){ if eval "$2"; then echo "CHECK PASS: $1"; else echo "CHECK FAIL: $1"; FAILED=1; fi; }
psql_db(){ docker compose exec -T db sh -c 'psql -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }
drv(){ python3 "$WORK/driver.py" "$1" || FAILED=1; }
health(){ docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$1")"; }

sec "0. PRE-CHECKS"
[ -e "$WORK" ] && { echo "ABORT: $WORK exists"; exit 1; }
ss -tlnH | grep -qE ':(8000|5678|5432) ' && { echo "ABORT: port 8000/5678/5432 in use"; exit 1; }
docker compose ls -a --format json 2>/dev/null | grep -q '"Name":"nexo"' && { echo "ABORT: project nexo exists"; exit 1; }
for v in nexo_db_data nexo_n8n_data; do docker volume inspect "$v" >/dev/null 2>&1 && { echo "ABORT: volume $v exists"; exit 1; }; done
echo "pre-checks passed"; run docker system df; run ss -tlnH

sec "1. RECEIVE OPENROUTER KEY (stdin, never printed) + BUNDLE"
IFS= read -r ORK
mkdir -p "$WORK"; chmod 700 "$WORK"
( umask 077; printf '%s' "$ORK" > "$WORK/ork" )
case "$ORK" in sk-or-*) KEYOK=1 ;; *) KEYOK=0 ;; esac
unset ORK
[ "$KEYOK" = 1 ] || { echo "ABORT: first stdin line is not an OpenRouter key"; rm -rf -- "$WORK"; exit 1; }
echo "key received on stdin: format ok, stored in a 600-mode file (value not shown)"
docker images -q --no-trunc | sort -u > "$WORK/images.before"
exec > >(tee "$LOG") 2>&1
cat > "$WORK/rag.bundle"
check "bundle sha256 matches the local bundle" '[ "$(sha256sum "$WORK/rag.bundle" | cut -d" " -f1)" = "$BUNDLE_SHA256" ]'

sec "2. CHECKOUT EXACT COMMIT"
run git clone -q "$WORK/rag.bundle" "$REPO"
git -C "$REPO" -c advice.detachedHead=false checkout -q --detach "$EXPECTED_SHA"
check "checked-out commit is $EXPECTED_SHA" '[ "$(git -C "$REPO" rev-parse HEAD)" = "$EXPECTED_SHA" ]'
check "working tree clean (no edits)" '[ -z "$(git -C "$REPO" status --porcelain)" ]'
cd "$REPO" || exit 1

sec "3. VM-LOCAL .env (generated secrets + OpenRouter key from the 600-mode file; never printed)"
( umask 077
  tok(){ python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
  printf 'POSTGRES_DB=nexo\nPOSTGRES_USER=nexo\nPOSTGRES_PASSWORD=%s\nAUTH_TOKEN_CUSTOMER_A=%s\nAUTH_TOKEN_CUSTOMER_B=%s\nN8N_ENCRYPTION_KEY=%s\nLEAD_WRITER_TOKEN_SHA256=%s\nOPENROUTER_API_KEY=%s\n' \
    "$(tok)" "$(tok)" "$(tok)" "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
    "$(python3 -c 'import secrets,hashlib; print(hashlib.sha256(secrets.token_bytes(32)).hexdigest())')" "$(cat "$WORK/ork")" > .env
)
run stat -c '%A %n' .env "$WORK/ork"
echo ".env names: $(cut -d= -f1 .env | tr '\n' ' ')"
echo "NOTE: N8N_ENCRYPTION_KEY / LEAD_WRITER_TOKEN_SHA256 are random placeholders required by compose interpolation; n8n is NOT started."

sec "4. CONFIG + BUILD + START (db + backend only)"
check "docker compose config valid (output not printed: it would contain secrets)" 'docker compose config --quiet'
run docker compose --progress plain build backend 2>&1 | tail -3
run docker compose up -d --wait --wait-timeout 300 db backend
run docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
for s in db backend; do check "$s healthy" '[ "$(health '"$s"')" = healthy ]'; done
check "n8n NOT running (not needed for RAG)" '[ -z "$(docker compose ps -q n8n)" ]'
echo "--- backend startup:"; docker compose logs --no-color backend 2>&1 | grep -E 'migrations applied|provisioned|applied' | sed -E 's/^[^|]*\| //'

sec "5. MIGRATIONS 0001-0007 + CHECKSUMS + PGVECTOR"
echo "SELECT version || ' ' || checksum FROM schema_migrations ORDER BY version;" | psql_db > "$WORK/db_mig.txt"
for f in src/backend/app/migrations/*.sql; do echo "$(basename "$f" .sql) $(sha256sum "$f" | cut -d' ' -f1)"; done > "$WORK/file_mig.txt"
cat "$WORK/db_mig.txt"
check "schema_migrations == files 0001..0007 (identical checksums)" 'diff -q "$WORK/db_mig.txt" "$WORK/file_mig.txt" >/dev/null && [ "$(wc -l < "$WORK/db_mig.txt")" = 7 ] && grep -q "^0007_knowledge " "$WORK/db_mig.txt"'
echo "SELECT 'server ' || current_setting('server_version') || ' | vector ' || extversion FROM pg_extension WHERE extname = 'vector';" | psql_db
check "pgvector extension 0.8.7 installed" '[ "$(echo "SELECT extversion FROM pg_extension WHERE extname = '"'vector'"';" | psql_db)" = 0.8.7 ]'
echo "SELECT 'knowledge_chunks.embedding: ' || format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = 'knowledge_chunks'::regclass AND attname = 'embedding';" | psql_db

sec "6. NETWORK / EXPOSURE"
run ss -tlnH
check "backend only 127.0.0.1:8000" '[ "$(docker port "$(docker compose ps -q backend)")" = "8000/tcp -> 127.0.0.1:8000" ]'
check "db no published port" '[ -z "$(docker port "$(docker compose ps -q db)")" ]'
check "no :5432 host listener" '! ss -tlnH | grep -q ":5432 "'
check "no :5678 host listener (n8n not started)" '! ss -tlnH | grep -q ":5678 "'
check "public listeners only :9922" '[ -z "$(ss -tlnH | awk "{print \$4}" | grep -vE "^(127\.|\[::1\]|0\.0\.0\.0:9922$|\[::\]:9922$)")" ]'

sec "7. KNOWLEDGE MOUNT (canonical corpus, read-only)"
docker inspect -f '{{range .Mounts}}{{.Source}} -> {{.Destination}} rw={{.RW}}{{println}}{{end}}' "$(docker compose ps -q backend)" | sed "s#$REPO#<checkout>#" | grep .
check "mount ./knowledge -> /srv/knowledge is read-only" '[ "$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"/srv/knowledge\"}}{{.RW}}{{end}}{{end}}" "$(docker compose ps -q backend)")" = false ]'
check "write inside /srv/knowledge is refused" '! docker compose exec -T backend sh -c "touch /srv/knowledge/x" 2>/dev/null'
echo "--- files inside the container (ls -A /srv/knowledge):"; docker compose exec -T backend ls -A /srv/knowledge
check "exactly the 4 canonical files, nothing else (incl. hidden)" '[ "$(docker compose exec -T backend ls -A /srv/knowledge | tr "\n" " ")" = "01_services.md 02_support_policy.md 03_commercial_policy.md 04_security_policy.md " ]'
for f in 01_services.md 02_support_policy.md 03_commercial_policy.md 04_security_policy.md; do
  C="$(docker compose exec -T backend sha256sum "/srv/knowledge/$f" | cut -d' ' -f1)"
  G="$(git cat-file blob "$EXPECTED_SHA:knowledge/$f" | sha256sum | cut -d' ' -f1)"
  echo "$f container=$C commit=$G"
  check "$f in container == blob in $EXPECTED_SHA" '[ "$C" = "$G" ]'
done

sec "8. DRIVER (host python3 stdlib; secrets read from files, never printed)"
cat > "$WORK/driver.py" <<'PY'
"""RAG-01V1 checks against the REAL stack: backend 127.0.0.1:8000, REAL pgvector, REAL OpenRouter embeddings."""
import hashlib, json, os, re, shutil, subprocess, sys, urllib.error, urllib.request

WORK = os.environ["WORK"]; REPO = os.path.join(WORK, "repo")
BASE = "http://127.0.0.1:8000"
MODEL = "openai/text-embedding-3-small"
ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l)
TOK = {"A": ENV["AUTH_TOKEN_CUSTOMER_A"], "B": ENV["AUTH_TOKEN_CUSTOMER_B"]}
ORK = open(os.path.join(WORK, "ork")).read().strip()
SECRETS = [TOK["A"], TOK["B"], ENV["POSTGRES_PASSWORD"], ORK]
STATE_FILE = os.path.join(WORK, "state.json")
FAILED = []
SUPPORTED = [  # (label, query, expected chunk, strict top-1) from evidence/10-rag/calibration.json
    ("A schedule", "¿Cuál es el horario de atención del soporte?", "support-policy#horario-de-atencion", True),
    ("B services", "¿Qué servicios ofrecéis?", "services#catalogo-de-servicios", True),
    ("C commercial", "¿Cuánto cuesta el diagnóstico inicial?", "commercial-policy#tarifas", True),
    ("critical incident", "¿Cuándo se considera crítica una incidencia?", "support-policy#clasificacion-de-incidencias", False),
    ("agent limits", "¿El agente puede reiniciar un servidor?", "support-policy#limites-del-agente-y-escalado", False),
    ("new deployment", "¿Cuándo estará lista una nueva implantación?", "services#nuevas-implantaciones-y-plazos", False),
    ("AI pricing", "¿Cuánto cuesta una implantación de IA?", "commercial-policy#implantaciones-de-ia-y-descuentos", False),
    ("paraphrase: managed support price", "precio mensual del soporte gestionado", "commercial-policy#tarifas", False),
    ("paraphrase: delete my data", "quiero que borréis mis datos", "security-policy#acciones-y-borrados", False),
    ("password (calibration: expected at rank 2)", "¿Puedo darle mi contraseña al agente?", "security-policy#datos-sensibles-y-privacidad", False),
]
INSUFFICIENT = [
    ("absent in domain (REQUIRED)", "¿Tenéis oficina en Barcelona?"),
    ("absent in domain", "¿Cuál es vuestro número de teléfono?"),
    ("absent in domain", "¿Desarrolláis aplicaciones móviles?"),
    ("unrelated", "receta de paella valenciana"),
    ("unrelated", "precio del bitcoin hoy"),
    ("unrelated", "¿Cuál es la capital de Australia?"),
]
QUERIES = [q for _, q, _, _ in SUPPORTED] + [q for _, q in INSUFFICIENT] + ["¿Cuánto cuesta el diagnóstico inicial? (demo)"]


def state():
    return json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}


def save(**kw):
    s = state(); s.update(kw); json.dump(s, open(STATE_FILE, "w"))


def check(name, ok, detail=""):
    print(("CHECK PASS: " if ok else "CHECK FAIL: ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILED.append(name)


def http(method, path, token=None, body=None, headers=None, raw_body=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if token is not None:
        h["Authorization"] = "Bearer " + token
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, method=method, headers=h, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    text = raw.decode("utf-8", "replace")
    assert not any(s in text for s in SECRETS), "secret in response body"
    try:
        return status, json.loads(text)
    except ValueError:
        return status, None


def search(query, who="A", top_k=3, conv=None):
    return http("POST", "/rag/search", TOK[who], {"query": query, "top_k": top_k},
                {"X-Conversation-ID": conv or "rag01v1-conv"})


def sh(cmd, inp=None):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), input=inp, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def sql(q):
    return sh(["docker", "compose", "exec", "-T", "db", "sh", "-c",
               'psql -X -q -t -A -F "|" -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], q)[1].strip()


def ingest(directory=None):
    cmd = ["docker", "compose", "exec", "-T", "backend", "python", "-m", "app.rag_ingest"] + (["--dir", directory] if directory else [])
    rc, out, err = sh(cmd)
    both = out + err
    print(f"  $ python -m app.rag_ingest{' --dir ' + directory if directory else ''}  (exit {rc})")
    for line in both.strip().splitlines():
        print("    " + line)
    check("ingest output: no key, no embeddings/long float lists, single short line",
          ORK not in both and not re.search(r"(-?\d\.\d+,\s*){10}", both) and len(both) < 400 and len(both.strip().splitlines()) == 1)
    rep = json.loads(out.strip().split("rag_ingest ", 1)[1]) if rc == 0 and out.startswith("rag_ingest ") else {}
    return rc, rep


def index_snapshot():
    docs = sql("SELECT source_id, id, reference, content_sha256, embedding_model, updated_at FROM knowledge_documents ORDER BY source_id;")
    chunks = sql("SELECT chunk_key, id, document_id, content_sha256, embedding_model, md5(embedding::text), updated_at "
                 "FROM knowledge_chunks ORDER BY chunk_key;")
    return docs, chunks


def index_facts():
    return sql("SELECT (SELECT count(*) FROM knowledge_documents) || '|' || (SELECT count(*) FROM knowledge_chunks) || '|' ||"
               " (SELECT count(DISTINCT chunk_key) FROM knowledge_chunks) || '|' || (SELECT count(DISTINCT embedding_model) FROM knowledge_chunks) || '|' ||"
               " (SELECT min(embedding_model) FROM knowledge_chunks) || '|' || (SELECT string_agg(DISTINCT vector_dims(embedding)::text, ',') FROM knowledge_chunks) || '|' ||"
               " (SELECT count(DISTINCT embedding_model) FROM knowledge_documents);").split("|")


def show_match(m):
    print(f"    {m['reference']} | source_id={m['source_id']} | chunk_id={m['chunk_id']} | version={m['document_version']}"
          f" | chunk_sha={m['chunk_sha256']} | score={m['score']}")


# ----------------------------------------------------------------------------------------------
def health():
    for path in ("/health", "/health/ready"):
        s, js = http("GET", path)
        print(f"  GET {path}: {s} {json.dumps(js)}")
        check(f"{path} 200", s == 200)


def ingest1():
    print(f"  index before: {sql('SELECT count(*) || ' + chr(39) + ' documents, ' + chr(39) + ' || (SELECT count(*) FROM knowledge_chunks) || ' + chr(39) + ' chunks' + chr(39) + ' FROM knowledge_documents;')}")
    rc, rep = ingest()
    check("first ingestion exit 0 with REAL OpenRouter", rc == 0)
    check("report: model openai/text-embedding-3-small, 4 new documents, 10 chunks, 10 embedded, nothing deleted",
          rep.get("model") == MODEL and rep.get("documents") == 4 and rep.get("new") == 4 and rep.get("chunks") == 10
          and rep.get("embedded") == 10 and rep.get("deleted_chunks") == 0 and rep.get("deleted_documents") == 0, json.dumps(rep))
    f = index_facts()
    print(f"  index facts: documents={f[0]} chunks={f[1]} distinct_chunk_keys={f[2]} chunk_models={f[3]} model={f[4]} dims={f[5]} doc_models={f[6]}")
    check("4 documents, 10 chunks, no duplicate chunk keys", f[0] == "4" and f[1] == "10" and f[2] == "10")
    check("every embedding has 1536 dimensions", f[5] == "1536")
    check("single model openai/text-embedding-3-small (chunks + documents)", f[3] == "1" and f[4] == MODEL and f[6] == "1")
    print("  indexed rows (no vectors printed): chunk_key | ordinal | section | chunk sha256(12) | document reference | doc sha256(12)")
    for r in sql("SELECT c.chunk_key, c.ordinal, c.section, left(c.content_sha256,12), d.reference, left(d.content_sha256,12)"
                 " FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id ORDER BY d.reference, c.ordinal;").splitlines():
        print("    " + r)
    save(snap1=index_snapshot())


def ingest2():
    rc, rep = ingest()
    check("re-ingest exit 0", rc == 0)
    check("re-ingest: 0 embedded, 4 unchanged, 0 new/updated/deleted, 10 chunks",
          rep.get("embedded") == 0 and rep.get("unchanged") == 4 and rep.get("new") == 0 and rep.get("updated") == 0
          and rep.get("deleted_chunks") == 0 and rep.get("deleted_documents") == 0 and rep.get("chunks") == 10, json.dumps(rep))
    snap = index_snapshot()
    check("re-ingest: documents + chunks byte-identical (ids, hashes, models, vector md5, updated_at)",
          list(snap) == state()["snap1"])
    f = index_facts()
    check("still 4 documents / 10 chunks / 10 distinct keys", f[0] == "4" and f[1] == "10" and f[2] == "10")


def retrieval():
    rows = []
    for label, q, expected, strict in SUPPORTED:
        s, js = search(q)
        ok = s == 200 and js and js.get("evidence") == "found"
        ids = [m["chunk_id"] for m in (js or {}).get("matches", [])]
        top = ids[0] if ids else None
        print(f"  [{label}] query={q!r} -> HTTP {s} evidence={(js or {}).get('evidence')} best_score={(js or {}).get('best_score')}"
              f" min_score={(js or {}).get('min_score')} model={(js or {}).get('model')} accepted={ids}")
        for m in (js or {}).get("matches", []):
            show_match(m)
        if strict:
            check(f"{label}: evidence=found, top-1 = {expected}, score >= threshold", ok and top == expected and js["matches"][0]["score"] >= js["min_score"])
            files = {"support-policy": "02_support_policy.md", "services": "01_services.md", "commercial-policy": "03_commercial_policy.md"}
            m0 = js["matches"][0] if ok and js["matches"] else {}
            check(f"{label}: reference = '<real file> § <section>'", m0.get("reference") == f"{files[expected.split('#')[0]]} § {m0.get('section')}",
                  m0.get("reference", ""))
        else:
            check(f"{label}: evidence=found and expected chunk accepted", ok and expected in ids, f"top-1 {top}")
        check(f"{label}: no generated answer field", js is not None and "answer" not in js)
        rows.append({"label": label, "query": q, "expected": expected, "top1": top, "accepted": ids,
                     "best_score": (js or {}).get("best_score"), "matches": (js or {}).get("matches", [])})
    save(retrieval=rows)


def insufficient():
    for label, q in INSUFFICIENT:
        s, js = search(q)
        print(f"  [{label}] query={q!r} -> HTTP {s} evidence={(js or {}).get('evidence')} matches={(js or {}).get('matches')}"
              f" best_score={(js or {}).get('best_score')} min_score={(js or {}).get('min_score')}")
        check(f"{label} {q!r}: evidence=insufficient, matches=[], no answer, best_score < min_score",
              s == 200 and js["evidence"] == "insufficient" and js["matches"] == [] and "answer" not in js
              and js["best_score"] < js["min_score"])


def file_sha_in_container(path):
    rc, out, _ = sh(["docker", "compose", "exec", "-T", "backend", "sha256sum", path])
    return out.split()[0] if rc == 0 else None


def parsed_chunk_sha(path, key):
    code = ("import sys; from pathlib import Path; from app import rag; d = rag.parse_document(Path(sys.argv[1]));"
            " print(d.reference + '|' + d.content_sha256 + '|' + next(c.content_sha256 for c in d.chunks if c.chunk_key == sys.argv[2]))")
    return sh(["docker", "compose", "exec", "-T", "backend", "python", "-c", code, path, key])[1].strip().split("|")


def references():
    hits = [(r["label"], m) for r in state()["retrieval"][:3] for m in r["matches"]]
    for label, m in hits:
        row = sql(f"SELECT c.id, c.content_sha256, c.embedding_model, d.id, d.source_id, d.reference, d.path, d.content_sha256,"
                  f" encode(sha256(convert_to(c.content, 'UTF8')), 'hex'), c.content = $t${m['text']}$t$"
                  f" FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id WHERE c.chunk_key = '{m['chunk_id']}';").split("|")
        f = "/srv/knowledge/" + row[5]
        fsha = file_sha_in_container(f)
        gsha = hashlib.sha256(subprocess.run(["git", "-C", REPO, "cat-file", "blob", f"HEAD:knowledge/{row[5]}"], capture_output=True).stdout).hexdigest()
        pref, pdoc, pchunk = parsed_chunk_sha(f, m["chunk_id"])
        print(f"  [{label}] API {m['reference']} chunk_id={m['chunk_id']} version={m['document_version']} chunk_sha={m['chunk_sha256']}")
        print(f"     -> chunk row id={row[0]} sha={row[1][:12]} model={row[2]} | sha256(DB content)={row[8][:12]} | API text == DB content: {row[9]}")
        print(f"     -> document row id={row[3]} source_id={row[4]} reference={row[5]} path={row[6]} sha={row[7][:12]}")
        print(f"     -> mounted file {f}: sha256={fsha[:12] if fsha else None} | commit blob sha256={gsha[:12]}"
              f" | re-parsed in container: reference={pref} doc_sha={pdoc[:12]} chunk_sha={pchunk[:12]}")
        filename = m["reference"].split(" § ")[0]
        check(f"[{label}] {m['chunk_id']}: API filename == document row reference == path == real mounted file name",
              filename == row[5] == row[6] == pref and fsha is not None)
        check(f"[{label}] {m['chunk_id']}: version == doc row sha == sha256(mounted file) == sha256(commit blob)",
              m["document_version"] == row[7][:12] and row[7] == fsha == gsha == pdoc)
        check(f"[{label}] {m['chunk_id']}: chunk_sha == row sha == sha256(DB content) == re-parsed file chunk sha; API text == DB content",
              m["chunk_sha256"] == row[1][:12] and row[1] == row[8] == pchunk and row[9] == "t")


def to_container_demo(src):
    rc = subprocess.run(f"tar -C {os.path.dirname(src)} -cf - {os.path.basename(src)} | docker compose exec -T backend sh -c "
                        f"'rm -rf /tmp/kdemo && tar -C /tmp -xf - && ls /tmp/kdemo | tr \"\\n\" \" \"'", shell=True, capture_output=True, text=True)
    print(f"  copied to container /tmp/kdemo: {rc.stdout.strip()}")


def demo():
    canon = os.path.join(REPO, "knowledge")
    tmp = os.path.join(WORK, "kdemo")
    shutil.copytree(canon, tmp)
    tar = os.path.join(tmp, "03_commercial_policy.md")
    text = open(tar, encoding="utf-8").read()
    print(f"  1. temporary copy {tmp}: occurrences of '120 €' in 03_commercial_policy.md = {text.count('120 €')}")
    check("1. temporary copy contains the canonical 120 € exactly once", text.count("120 €") == 1)
    to_container_demo(tmp)
    rc, rep = ingest("/tmp/kdemo")
    check("2. ingest temporary copy (identical content): 0 embedded, 4 unchanged", rc == 0 and rep.get("embedded") == 0 and rep.get("unchanged") == 4, json.dumps(rep))
    ids_before = dict(l.split("|") for l in sql("SELECT chunk_key, id FROM knowledge_chunks;").splitlines())
    s, js = search("¿Cuánto cuesta el diagnóstico inicial?")
    top = js["matches"][0] if js and js["matches"] else {}
    print(f"  3. retrieval before: {top.get('reference')} chunk={top.get('chunk_id')} score={top.get('score')} text excerpt={top.get('text', '')[-95:]!r}")
    check("3. tariff chunk retrieved and contains 120 €", top.get("chunk_id") == "commercial-policy#tarifas" and "120 €" in top.get("text", ""))
    new = text.replace("Diagnóstico inicial: 120 € más IVA.", "Diagnóstico inicial: 150 € más IVA.")
    open(tar, "w", encoding="utf-8", newline="\n").write(new)
    diff = sh(["diff", os.path.join(canon, "03_commercial_policy.md"), tar])[1]
    print("  4. edit applied ONLY to the temporary copy; diff canonical -> temporary:")
    for line in diff.splitlines():
        print("     " + line)
    check("4. exactly one line changed (120 € -> 150 €) in the temporary copy", sum(l.startswith(("<", ">")) for l in diff.splitlines()) == 2)
    check("4. committed canonical file untouched", subprocess.run(["git", "-C", REPO, "status", "--porcelain"], capture_output=True, text=True).stdout == "")
    to_container_demo(tmp)
    rc, rep = ingest("/tmp/kdemo")
    check("5. re-ingest after edit: 1 document updated, exactly 1 chunk re-embedded, 3 unchanged, 10 chunks, nothing deleted",
          rc == 0 and rep.get("updated") == 1 and rep.get("embedded") == 1 and rep.get("unchanged") == 3 and rep.get("chunks") == 10
          and rep.get("deleted_chunks") == 0, json.dumps(rep))
    c120 = sql("SELECT count(*) FROM knowledge_chunks WHERE content LIKE '%120 €%';")
    tar_row = sql("SELECT id, content LIKE '%150 €%', left(content_sha256,12) FROM knowledge_chunks WHERE chunk_key = 'commercial-policy#tarifas';").split("|")
    ids_after = dict(l.split("|") for l in sql("SELECT chunk_key, id FROM knowledge_chunks;").splitlines())
    f = index_facts()
    print(f"  6. rows containing '120 €': {c120} | tarifas row id {tar_row[0]} (before {ids_before['commercial-policy#tarifas']}) contains 150 €: {tar_row[1]} sha {tar_row[2]}"
          f" | chunks={f[1]} distinct keys={f[2]}")
    check("6. no indexed chunk still contains 120 €", c120 == "0")
    check("6. tariff chunk now contains 150 € (same row, updated in place)", tar_row[1] == "t" and tar_row[0] == ids_before["commercial-policy#tarifas"])
    check("6. unchanged chunks not duplicated (same 10 keys, same row ids)", ids_after == ids_before and f[1] == "10" and f[2] == "10")
    s, js = search("¿Cuánto cuesta el diagnóstico inicial?")
    top = js["matches"][0] if js and js["matches"] else {}
    tmp_sha = hashlib.sha256(new.encode()).hexdigest()
    print(f"  6. retrieval after: {top.get('reference')} chunk={top.get('chunk_id')} version={top.get('document_version')} score={top.get('score')}"
          f" text excerpt={top.get('text', '')[-95:]!r}")
    check("6. post-update retrieval returns the 150 € chunk (no 120 €)", top.get("chunk_id") == "commercial-policy#tarifas"
          and "150 €" in top.get("text", "") and "120 €" not in top.get("text", ""))
    check("6. reference still the same real file name; version == sha256(edited temporary file)",
          top.get("reference") == "03_commercial_policy.md § Tarifas" and top.get("document_version") == tmp_sha[:12])
    rc, rep = ingest()
    check("7. RESTORE from canonical /srv/knowledge: 1 updated, 1 embedded", rc == 0 and rep.get("updated") == 1 and rep.get("embedded") == 1, json.dumps(rep))
    c120 = sql("SELECT count(*) FROM knowledge_chunks WHERE content LIKE '%120 €%';")
    c150 = sql("SELECT count(*) FROM knowledge_chunks WHERE content LIKE '%150 €%';")
    shas = dict(l.split("|") for l in sql("SELECT reference, content_sha256 FROM knowledge_documents;").splitlines())
    canon_ok = all(shas.get(n) == hashlib.sha256(open(os.path.join(canon, n), "rb").read()).hexdigest() for n in os.listdir(canon))
    print(f"  7. after restore: rows with 120 € = {c120}, rows with 150 € = {c150}, every document version == committed file: {canon_ok}")
    check("7. index restored to the committed corpus (120 € back, no 150 €, all versions == committed files)", c120 == "1" and c150 == "0" and canon_ok)
    sh(["docker", "compose", "exec", "-T", "backend", "rm", "-rf", "/tmp/kdemo"]); shutil.rmtree(tmp)
    check("temporary corpus removed (host + container)", not os.path.exists(tmp) and sh(["docker", "compose", "exec", "-T", "backend", "test", "-e", "/tmp/kdemo"])[0] != 0)


def consistency():
    rc, out, _ = sh(["docker", "compose", "exec", "-T", "backend", "python", "-c",
                     "from app.config import load_settings; from app import rag; s = load_settings();"
                     " print(s.rag_embedding_model + '|' + str(rag.EMBEDDING_DIMENSION) + '|' + str(s.rag_min_score))"])
    configured, dim, thr = out.strip().split("|")
    f = index_facts()
    s, js = search("¿Cuál es el horario de atención del soporte?")
    print(f"  configured model={configured} dimension={dim} min_score={thr} | indexed: chunk models={f[3]} ({f[4]}), doc models={f[6]},"
          f" dims={f[5]} | API model={js.get('model')}")
    check("configured model == indexed model == API model == openai/text-embedding-3-small", configured == f[4] == js.get("model") == MODEL)
    check("dimension 1536 (code + every stored vector)", dim == "1536" and f[5] == "1536")
    check("single embedding_model in chunks and documents; no mixed rows", f[3] == "1" and f[6] == "1"
          and sql(f"SELECT count(*) FROM knowledge_chunks WHERE embedding_model <> '{MODEL}';") == "0")


def auth():
    q = "¿Cuál es el horario de atención del soporte?"
    sa, a = search(q, "A"); sb, b = search(q, "B")
    ia, ib = [m["chunk_id"] for m in a["matches"]], [m["chunk_id"] for m in b["matches"]]
    diffs = [abs(x["score"] - y["score"]) for x, y in zip(a["matches"], b["matches"])]
    print(f"  CUSTOMER_A: {sa} {ia} | CUSTOMER_B: {sb} {ib} | max score difference {max(diffs) if diffs else None}")
    check("CUSTOMER_A 200 found", sa == 200 and a["evidence"] == "found")
    check("CUSTOMER_B gets the same shared-corpus result (same chunks/references; scores within 0.02: embedding jitter)",
          sb == 200 and ia == ib and [m["reference"] for m in a["matches"]] == [m["reference"] for m in b["matches"]] and max(diffs) < 0.02)
    cases = [
        ("missing token", None, {"query": q}, {}, 401),
        ("invalid token", "x" * 43, {"query": q}, {}, 401),
        ("injected customer_id field", TOK["A"], {"query": q, "customer_id": "CUSTOMER_B"}, {}, 422),
        ("malformed X-Conversation-ID", TOK["A"], {"query": q}, {"X-Conversation-ID": "bad id!"}, 400),
        ("top_k 0", TOK["A"], {"query": q, "top_k": 0}, {}, 422),
        ("top_k 6", TOK["A"], {"query": q, "top_k": 6}, {}, 422),
        ("top_k not an integer", TOK["A"], {"query": q, "top_k": "abc"}, {}, 422),
        ("empty query", TOK["A"], {"query": ""}, {}, 422),
        ("whitespace-only query", TOK["A"], {"query": "    "}, {}, 422),
        ("query 501 chars", TOK["A"], {"query": "a" * 501}, {}, 422),
        ("missing query", TOK["A"], {"top_k": 3}, {}, 422),
    ]
    for label, tok, body, hdr, expected in cases:
        s, js = http("POST", "/rag/search", tok, body, hdr)
        print(f"  {label}: HTTP {s} code={(js or {}).get('code')}")
        check(f"{label} -> {expected}", s == expected)
    s, js = http("POST", "/rag/search", TOK["A"], {"query": "a" * 500, "top_k": 1})
    check("query of exactly 500 chars accepted (boundary)", s == 200, str(s))


def logs():
    backend = sh(["docker", "compose", "logs", "--no-color", "backend"])[1]
    events = [json.loads(l[l.index('{"ts"'):]) for l in backend.splitlines() if '{"ts"' in l]
    rag = [e for e in events if e.get("action") == "rag_search"]
    print(f"  rag_search audit events: {len(rag)}; examples (found, insufficient, rejected):")
    found = next((e for e in rag if e.get("result") == "found"), None)
    insuf = next((e for e in rag if e.get("result") == "insufficient"), None)
    rej = next((e for e in rag if e.get("status") in (400, 401, 422) or e.get("status_code") in (400, 401, 422)), None)
    for e in (found, insuf, rej):
        if e:
            print("   " + json.dumps(e, ensure_ascii=False))
    need = ("request_id", "conversation_id", "customer_id", "query_length", "query_fp", "model", "accepted", "chunk_ids",
            "source_ids", "best_score", "result")
    check("found event has request_id, conversation_id, customer, query length/fingerprint, model, accepted, chunk/source ids, best_score, result",
          found is not None and all(k in found for k in need), str([k for k in need if found and k not in found]))
    check("events carry status + timing", found is not None and any(k in found for k in ("status", "status_code"))
          and any("ms" in k or "duration" in k for k in found))
    check("query fingerprint == sha256(query)[:12]", found is not None and found["query_fp"] in
          {hashlib.sha256(q.encode()).hexdigest()[:12] for q in QUERIES})
    check("conversation id propagated", found is not None and found["conversation_id"] == "rag01v1-conv")
    contents = [c for c in sql("SELECT content FROM knowledge_chunks;").split("\n") if len(c) > 40]
    run_log = open(os.path.join(WORK, "run.log"), encoding="utf-8", errors="replace").read()
    for name, blob in (("backend logs", backend), ("harness run log", run_log)):
        check(f"{name}: no OpenRouter key, customer tokens, DB password", not any(s in blob for s in SECRETS))
        check(f"{name}: no Authorization header / Bearer value", not re.search(r"Bearer\s+\S{8,}", blob) and not re.search(r"(?i)[\"']?authorization[\"']?\s*[:=]", blob))
        check(f"{name}: no raw embeddings (>=10 comma-separated floats)", not re.search(r"(-?\d\.\d{5,},\s*){10}", blob))
    check("backend logs: no raw query text", not any(q in backend for q in QUERIES))
    check("backend logs: no chunk content", not any(c in backend for c in contents))


if __name__ == "__main__":
    {"health": health, "ingest1": ingest1, "ingest2": ingest2, "retrieval": retrieval, "insufficient": insufficient,
     "references": references, "demo": demo, "consistency": consistency, "auth": auth, "logs": logs}[sys.argv[1]]()
    print(f"PHASE {sys.argv[1]}: {'PASS' if not FAILED else 'FAILURES: ' + '; '.join(FAILED)}")
    sys.exit(1 if FAILED else 0)
PY
echo "driver ready"

sec "9. HEALTH"
drv health

sec "10. REAL INGESTION (REAL OpenRouter embeddings -> REAL pgvector)"
drv ingest1

sec "11. RE-INGEST IDEMPOTENCY"
drv ingest2

sec "12. SUPPORTED RETRIEVAL (CUSTOMER_A, loopback)"
drv retrieval

sec "13. NO-EVIDENCE MATRIX"
drv insufficient

sec "14. REFERENCE INTEGRITY (API -> chunk row -> document row -> mounted file -> commit blob)"
drv references

sec "15. 120 € -> 150 € UPDATE DEMO (TEMPORARY copy only; then restore canonical)"
drv demo

sec "16. MODEL CONSISTENCY (REAL index)"
drv consistency

sec "17. ATOMIC FAILURE SMOKE: TEST failure providers, scratch database on the REAL VM PostgreSQL/pgvector"
echo "LABEL: TEST-ONLY providers (deterministic hashing; NOT OpenRouter). Scratch DB nexo_rag_smoke; the real index is not touched."
SNAP_REAL="$(echo "SELECT md5(string_agg(chunk_key || content_sha256 || embedding_model || md5(embedding::text), ',' ORDER BY chunk_key)) FROM knowledge_chunks;" | psql_db)"
echo "CREATE DATABASE nexo_rag_smoke;" | psql_db
cat > "$WORK/smoke.py" <<'PY'
"""TEST-ONLY atomic-failure smoke inside the real backend container, on a SCRATCH database. No OpenRouter call."""
import dataclasses, hashlib, math, re, sys
from pathlib import Path
import psycopg
from app import rag
from app.config import load_settings
from app.db import connect
from app.migrate import apply_migrations

FAILED = []
def check(name, ok):
    print(("CHECK PASS: " if ok else "CHECK FAIL: ") + name); ok or FAILED.append(name)

class TestHashProvider:  # TEST-ONLY
    def __init__(self, model, fail_on_call=None):
        self.model, self.dimension, self.calls, self.fail_on_call = model, rag.EMBEDDING_DIMENSION, 0, fail_on_call
    def embed(self, texts):
        self.calls += 1
        if self.fail_on_call and self.calls >= self.fail_on_call:
            raise rag.ProviderError("TEST failure provider: simulated failure")
        out = []
        for t in texts:
            v = [0.0] * self.dimension
            for tok in re.findall(r"\w{3,}", t.lower()):
                v[int(hashlib.sha256(tok.encode()).hexdigest(), 16) % self.dimension] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

def snap(c):
    return (c.execute("SELECT id, source_id, reference, content_sha256, embedding_model, updated_at FROM knowledge_documents ORDER BY 2").fetchall(),
            c.execute("SELECT id, chunk_key, content_sha256, embedding_model, md5(embedding::text), updated_at FROM knowledge_chunks ORDER BY 2").fetchall())

s = dataclasses.replace(load_settings(), postgres_db="nexo_rag_smoke")
corpus = Path("/srv/knowledge")
V1, V2 = "test-only/hashing-v1", "test-only/hashing-v2"
with connect(s, autocommit=True) as c:
    apply_migrations(c)
    r = rag.ingest(c, TestHashProvider(V1), corpus)
    print(f"  setup: scratch index built with TEST provider {V1}: {r.as_dict()}")
    before = snap(c)
    p = TestHashProvider(V2, fail_on_call=2)
    try:
        rag.ingest(c, p, corpus); print("  UNEXPECTED: no error")
    except rag.ProviderError as e:
        print(f"  provider failure: V1 -> V2, call 1 OK, call {p.calls} raised ProviderError ({e.code})")
    check("provider failure before publication: index identical (docs, chunks, hashes, models, vectors, timestamps)", snap(c) == before)
    c.execute("CREATE FUNCTION smoke_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.chunk_key = "
              "'support-policy#limites-del-agente-y-escalado' THEN RAISE EXCEPTION 'simulated DB failure late in publication'; END IF; RETURN NEW; END; $$")
    c.execute("CREATE TRIGGER smoke_fail BEFORE INSERT OR UPDATE ON knowledge_chunks FOR EACH ROW EXECUTE FUNCTION smoke_fail()")
    try:
        rag.ingest(c, TestHashProvider(V2), corpus); print("  UNEXPECTED: no error")
    except psycopg.Error as e:
        print(f"  DB failure during publication: {type(e).__name__} (all 10 embeddings had succeeded)")
    check("DB failure during publication: whole corpus rolled back (identical, still V1 only)", snap(c) == before)
    c.execute("DROP TRIGGER smoke_fail ON knowledge_chunks"); c.execute("DROP FUNCTION smoke_fail()")
    p = TestHashProvider(V2)
    try:
        rag.search_knowledge(c, p, "horario", 3, 0.2); print("  UNEXPECTED: no error")
    except rag.IndexMismatchError as e:
        print(f"  configured {V2} vs indexed {V1}: IndexMismatchError ({e.code}); provider calls: {p.calls}")
    check("model mismatch refused before embedding the query", p.calls == 0)
    c.execute("UPDATE knowledge_chunks SET embedding_model = %s WHERE chunk_key = 'services#catalogo-de-servicios'", (V2,))
    p = TestHashProvider(V1)
    try:
        rag.search_knowledge(c, p, "horario", 3, 0.2); print("  UNEXPECTED: no error")
    except rag.IndexMismatchError as e:
        print(f"  mixed-model index: IndexMismatchError ({e.code}); provider calls: {p.calls}")
    check("mixed-model index refused", p.calls == 0)
print("SMOKE: " + ("PASS" if not FAILED else "FAILURES: " + "; ".join(FAILED)))
sys.exit(1 if FAILED else 0)
PY
docker compose exec -T backend python - < "$WORK/smoke.py" || FAILED=1
echo "DROP DATABASE nexo_rag_smoke;" | psql_db
check "scratch database dropped" '[ "$(echo "SELECT count(*) FROM pg_database WHERE datname = '"'nexo_rag_smoke'"';" | psql_db)" = 0 ]'
check "REAL index untouched by the smoke" '[ "$(echo "SELECT md5(string_agg(chunk_key || content_sha256 || embedding_model || md5(embedding::text), '"','"' ORDER BY chunk_key)) FROM knowledge_chunks;" | psql_db)" = "$SNAP_REAL" ]'

sec "18. AUTH / INPUT SAFETY"
drv auth

sec "19. TRACEABILITY + SECRET HYGIENE"
drv logs
docker compose logs --no-color > "$WORK/compose.log" 2>&1
for var in POSTGRES_PASSWORD AUTH_TOKEN_CUSTOMER_A AUTH_TOKEN_CUSTOMER_B OPENROUTER_API_KEY; do
  V="$(sed -n "s/^$var=//p" .env)"
  echo "$var: run log $(grep -cF -- "$V" "$LOG"), container logs $(grep -cF -- "$V" "$WORK/compose.log")"
  check "$var value not in logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$WORK/compose.log")" = 0 ]'
  unset V
done
check "OpenRouter traffic only to the configured base URL (code: OPENROUTER_BASE_URL default)" 'docker compose exec -T backend python -c "from app.config import load_settings; import sys; sys.exit(0 if load_settings().openrouter_base_url == \"https://openrouter.ai/api/v1\" else 1)"'

sec "20. RESULT"
[ "$FAILED" = 0 ] && echo "RAG-01V1 VM VALIDATION: ALL CHECKS PASS" || echo "RAG-01V1 VM VALIDATION: FAILURES (see CHECK FAIL)"
echo "SELECT 'documents=' || (SELECT count(*) FROM knowledge_documents) || ' chunks=' || (SELECT count(*) FROM knowledge_chunks);" | psql_db

sec "21. CLEANUP"
run docker compose down -v
docker images -q --no-trunc | sort -u > "$WORK/images.after"
NEW_IMAGES="$(comm -13 "$WORK/images.before" "$WORK/images.after" | tr '\n' ' ')"
[ -n "$NEW_IMAGES" ] && run docker image rm -f $NEW_IMAGES | tail -3
run docker builder prune -f | tail -1
cd "$HOME"; case "$WORK" in "$HOME"/nexo-rag01v1) rm -rf -- "$WORK" ;; esac

sec "22. FINAL STATE"
run docker ps -a; run docker images; run docker volume ls; run docker network ls; run docker system df; run ss -tlnH
echo "nexo containers: $(docker ps -aq --filter label=com.docker.compose.project=nexo | wc -l)"
echo "nexo volumes: $(docker volume ls -q --filter label=com.docker.compose.project=nexo | wc -l)"
ss -tlnH | grep -qE ':(8000|5432|5678) ' && echo "LISTENER STILL PRESENT" || echo "no :8000/:5432/:5678 listener"
test ! -e "$HOME/nexo-rag01v1" && echo "temporary directory removed (checkout, .env, OpenRouter key file, bundle, driver, state, demo copy)"
