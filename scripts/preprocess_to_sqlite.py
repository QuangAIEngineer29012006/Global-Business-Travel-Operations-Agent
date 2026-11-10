"""Validate, index, and load mock travel operations fixtures into SQLite.

Usage: python scripts/preprocess_to_sqlite.py [--source data/mock-systems] [--output data/processed/travel_agent.sqlite]
Source fixtures are read-only; invalid records are reported and skipped.
"""
from __future__ import annotations
import argparse, csv, json, re, sqlite3, sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from policy_search import PolicySearchIndex


def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument('--source', type=Path, default=Path('data/mock-systems'))
    p.add_argument('--output', type=Path, default=Path('data/processed/travel_agent.sqlite'))
    return p.parse_args()


def load_csv(path, errors):
    try:
        with path.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
    except (OSError, csv.Error) as e:
        errors.append({'file':str(path),'record_id':None,'severity':'error','code':'FILE_READ_ERROR','message':str(e)})
        return []


def load_json(path, errors):
    try:
        with path.open(encoding='utf-8-sig') as f: data=json.load(f)
        if not isinstance(data,list): raise ValueError('Expected top-level JSON array')
        return data
    except (OSError, json.JSONDecodeError, ValueError) as e:
        errors.append({'file':str(path),'record_id':None,'severity':'error','code':'JSON_READ_ERROR','message':str(e)})
        return []


def problem(errors, file, rid, code, message, severity='error'):
    errors.append({'file':str(file),'record_id':rid,'severity':severity,'code':code,'message':message})


def required(rec, fields): return [k for k in fields if rec.get(k) in (None,'')]
def valid_date(value):
    try: date.fromisoformat(value); return True
    except (TypeError, ValueError): return False

def insert_many(conn, table, cols, rows):
    if not rows: return
    sql=f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
    conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS traveler_profiles(traveler_id TEXT PRIMARY KEY, department TEXT NOT NULL, preferences TEXT, home_region TEXT);
CREATE TABLE IF NOT EXISTS travel_requests(trip_id TEXT PRIMARY KEY, traveler_id TEXT NOT NULL REFERENCES traveler_profiles, destination TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, purpose TEXT NOT NULL, travel_status TEXT NOT NULL, required_fields TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS itineraries(itinerary_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL UNIQUE REFERENCES travel_requests, disruption_status TEXT NOT NULL, last_updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS itinerary_segments(segment_id TEXT PRIMARY KEY, itinerary_id TEXT NOT NULL REFERENCES itineraries ON DELETE CASCADE, segment_type TEXT NOT NULL, origin TEXT, destination TEXT, city TEXT, depart_at TEXT, arrive_at TEXT, check_in TEXT, check_out TEXT, status TEXT NOT NULL, disruption_note TEXT);
CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY, trip_id TEXT REFERENCES travel_requests, report_id TEXT, request_type TEXT NOT NULL, status TEXT NOT NULL, action_summary TEXT NOT NULL, created_at TEXT NOT NULL, CHECK ((trip_id IS NOT NULL) OR (report_id IS NOT NULL)));
CREATE TABLE IF NOT EXISTS expense_reports(report_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES travel_requests, traveler_id TEXT NOT NULL REFERENCES traveler_profiles, status TEXT NOT NULL, currency TEXT NOT NULL, receipts_status TEXT NOT NULL, submitted_at TEXT);
CREATE TABLE IF NOT EXISTS expense_line_items(item_id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES expense_reports ON DELETE CASCADE, category TEXT NOT NULL, amount REAL NOT NULL CHECK(amount>=0), currency TEXT NOT NULL, item_date TEXT NOT NULL, description TEXT NOT NULL, receipt_present INTEGER NOT NULL CHECK(receipt_present IN (0,1)));
CREATE TABLE IF NOT EXISTS policy_documents(doc_id TEXT PRIMARY KEY, source TEXT NOT NULL, version TEXT NOT NULL, effective_from TEXT, effective_to TEXT, category TEXT NOT NULL, file_path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policy_chunks(chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES policy_documents, source TEXT NOT NULL, section TEXT NOT NULL, page TEXT, version TEXT NOT NULL, category TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS draft_artifacts(draft_id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL, status TEXT NOT NULL, delivery_status TEXT NOT NULL, source_ids_json TEXT NOT NULL, content_json TEXT NOT NULL, created_at TEXT, idempotency_key TEXT UNIQUE);
CREATE INDEX IF NOT EXISTS idx_trip_traveler ON travel_requests(traveler_id);
CREATE INDEX IF NOT EXISTS idx_expense_trip ON expense_reports(trip_id);
CREATE INDEX IF NOT EXISTS idx_chunks_category ON policy_chunks(category);
'''


def main():
    args=parse_args(); src=args.source.resolve(); out=args.output.resolve(); out.parent.mkdir(parents=True,exist_ok=True); out.parent.joinpath('validation_report.json')
    errors=[]
    travelers=load_json(src/'traveler-profiles/traveler_profiles.json',errors)
    trips=load_csv(src/'travel-requests/travel_requests.csv',errors)
    itineraries=load_json(src/'itineraries/itineraries.json',errors)
    approvals=load_csv(src/'approvals/approvals.csv',errors)
    expenses=load_json(src/'expenses/expense_reports.json',errors)
    chunk_meta=load_csv(src/'policy-knowledge-base/chunk_metadata.csv',errors)
    valid_people=[]; ids=set()
    for r in travelers:
        rid=r.get('traveler_id'); miss=required(r,['traveler_id','department'])
        if miss or rid in ids: problem(errors,src/'traveler-profiles/traveler_profiles.json',rid,'INVALID_OR_DUPLICATE',f'missing={miss} or duplicate id'); continue
        ids.add(rid); valid_people.append({'traveler_id':rid,'department':r['department'],'preferences':r.get('preferences',''),'home_region':r.get('home_region','')})
    people_ids={x['traveler_id'] for x in valid_people}; valid_trips=[]; trip_ids=set()
    for r in trips:
        rid=r.get('trip_id'); miss=required(r,['trip_id','traveler_id','destination','start_date','end_date','purpose','travel_status','required_fields','created_at'])
        if miss or rid in trip_ids or r.get('traveler_id') not in people_ids or not valid_date(r.get('start_date')) or not valid_date(r.get('end_date')) or (valid_date(r.get('start_date')) and valid_date(r.get('end_date')) and r['end_date']<r['start_date']): problem(errors,src/'travel-requests/travel_requests.csv',rid,'INVALID_TRIP','missing/duplicate fields, invalid dates, or unknown traveler'); continue
        trip_ids.add(rid); valid_trips.append(r)
    valid_itins=[]; itin_ids=set(); segment_rows=[]; itin_trip=set()
    for it in itineraries:
        rid=it.get('itinerary_id'); trip=it.get('trip_id')
        if not rid or rid in itin_ids or trip not in trip_ids or trip in itin_trip or not it.get('last_updated'):
            problem(errors,src/'itineraries/itineraries.json',rid,'INVALID_ITINERARY','duplicate/missing id, unknown/duplicate trip, or missing updated time'); continue
        itin_ids.add(rid); itin_trip.add(trip); valid_itins.append({'itinerary_id':rid,'trip_id':trip,'disruption_status':it.get('disruption_status','unknown'),'last_updated':it['last_updated']})
        for s in it.get('segments',[]):
            sid=s.get('segment_id')
            if not sid or any(x['segment_id']==sid for x in segment_rows) or not s.get('type') or not s.get('status'):
                problem(errors,src/'itineraries/itineraries.json',sid,'INVALID_SEGMENT','missing/duplicate segment id, type, or status'); continue
            segment_rows.append({'segment_id':sid,'itinerary_id':rid,'segment_type':s['type'],'origin':s.get('origin'),'destination':s.get('destination'),'city':s.get('city'),'depart_at':s.get('depart_at'),'arrive_at':s.get('arrive_at'),'check_in':s.get('check_in'),'check_out':s.get('check_out'),'status':s['status'],'disruption_note':s.get('disruption_note')})

    valid_exp=[]; exp_ids=set(); line_rows=[]
    for r in expenses:
        rid=r.get('report_id'); miss=required(r,['report_id','trip_id','traveler_id','status','currency','receipts_status'])
        if miss or rid in exp_ids or r.get('trip_id') not in trip_ids or r.get('traveler_id') not in people_ids:
            problem(errors,src/'expenses/expense_reports.json',rid,'INVALID_EXPENSE','missing/duplicate fields or unknown trip/traveler'); continue
        exp_ids.add(rid); valid_exp.append({'report_id':rid,'trip_id':r['trip_id'],'traveler_id':r['traveler_id'],'status':r['status'],'currency':r['currency'],'receipts_status':r['receipts_status'],'submitted_at':r.get('submitted_at') or None})
        for item in r.get('line_items',[]):
            iid=item.get('item_id'); amount=item.get('amount')
            try: amount=float(amount)
            except (TypeError,ValueError): amount=-1
            if not iid or any(x['item_id']==iid for x in line_rows) or amount<0 or not valid_date(item.get('date')) or not item.get('category') or not item.get('currency'):
                problem(errors,src/'expenses/expense_reports.json',iid,'INVALID_EXPENSE_LINE','invalid/duplicate item id, amount, date, category or currency'); continue
            line_rows.append({'item_id':iid,'report_id':rid,'category':item['category'],'amount':amount,'currency':item['currency'],'item_date':item['date'],'description':item.get('description',''),'receipt_present':int(bool(item.get('receipt_present')))})
    valid_approvals=[]; approval_ids=set()
    for r in approvals:
        rid=r.get('approval_id'); trip=r.get('trip_id') or None; report=r.get('report_id') or None
        if not rid or rid in approval_ids or (trip not in trip_ids and trip is not None) or (report not in exp_ids and report is not None) or not (trip or report) or r.get('status') not in {'pending','approved','rejected'}:
            problem(errors,src/'approvals/approvals.csv',rid,'INVALID_APPROVAL','invalid/duplicate id, reference, or status'); continue
        approval_ids.add(rid); valid_approvals.append({'approval_id':rid,'trip_id':trip,'report_id':report,'request_type':r.get('request_type'),'status':r['status'],'action_summary':r.get('action_summary',''),'created_at':r.get('created_at','')})
    docs=[]; chunks=[]; meta_by={r.get('chunk_id'):r for r in chunk_meta}; seen_chunks=set()
    for path in sorted((src/'policy-knowledge-base/documents').glob('*.md')):
        try: raw=path.read_text(encoding='utf-8-sig')
        except OSError as e: problem(errors,path,None,'FILE_READ_ERROR',str(e)); continue
        fm=re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$',raw,re.S)
        if not fm: problem(errors,path,None,'INVALID_FRONTMATTER','missing YAML front matter'); continue
        fields=dict(re.findall(r'^([a-z_]+):\s*["\']?(.+?)["\']?\s*$',fm.group(1),re.M)); body=fm.group(2)
        doc_id=fields.get('doc_id'); required_doc=['doc_id','source','version','category']
        if any(not fields.get(k) for k in required_doc): problem(errors,path,doc_id,'INVALID_POLICY_DOC','required metadata absent'); continue
        docs.append({'doc_id':doc_id,'source':fields['source'],'version':fields['version'],'effective_from':fields.get('effective_from'),'effective_to':fields.get('effective_to') or None,'category':fields['category'],'file_path':path.relative_to(src).as_posix()})
        for match in re.finditer(r'^## Chunk (CHUNK-[\w-]+) — (.+?)\n(.*?)(?=^## Chunk |\Z)',body,re.M|re.S):
            cid,title,text=match.group(1),match.group(2),match.group(3).strip()
            m=meta_by.get(cid)
            if cid in seen_chunks or not m or not text: problem(errors,path,cid,'INVALID_POLICY_CHUNK','duplicate id, missing metadata index, or empty text'); continue
            if m.get('doc_id')!=doc_id or m.get('version')!=fields['version'] or m.get('category')!=fields['category']:
                problem(errors,path,cid,'POLICY_METADATA_MISMATCH','document and chunk metadata do not agree'); continue
            seen_chunks.add(cid); chunks.append({'chunk_id':cid,'doc_id':doc_id,'source':fields['source'],'section':title,'page':m.get('page') or None,'version':fields['version'],'category':fields['category'],'text':text})
    for cid,m in meta_by.items():
        if cid not in seen_chunks: problem(errors,src/'policy-knowledge-base/chunk_metadata.csv',cid,'ORPHAN_POLICY_METADATA','metadata row has no parsed chunk')
    draft_path=src/'draft-workspace/drafts.json'; drafts=[]
    try:
        d=json.loads(draft_path.read_text(encoding='utf-8-sig')); drafts=d.get('drafts',[])
        if not isinstance(drafts,list): raise ValueError('drafts must be an array')
    except (OSError,json.JSONDecodeError,ValueError) as e: problem(errors,draft_path,None,'INVALID_DRAFT_STORE',str(e))
    policy_index = PolicySearchIndex(chunks)
    # Foreign-key checked transaction. Rebuild output atomically from current fixtures.
    temp=out.with_suffix('.tmp.sqlite')
    if temp.exists(): temp.unlink()
    conn=sqlite3.connect(temp); conn.execute('PRAGMA foreign_keys=ON'); conn.executescript(SCHEMA)
    try:
        with conn:
            insert_many(conn,'traveler_profiles',['traveler_id','department','preferences','home_region'],valid_people)
            insert_many(conn,'travel_requests',['trip_id','traveler_id','destination','start_date','end_date','purpose','travel_status','required_fields','created_at'],valid_trips)
            insert_many(conn,'itineraries',['itinerary_id','trip_id','disruption_status','last_updated'],valid_itins)
            insert_many(conn,'itinerary_segments',['segment_id','itinerary_id','segment_type','origin','destination','city','depart_at','arrive_at','check_in','check_out','status','disruption_note'],segment_rows)
            insert_many(conn,'expense_reports',['report_id','trip_id','traveler_id','status','currency','receipts_status','submitted_at'],valid_exp)
            insert_many(conn,'expense_line_items',['item_id','report_id','category','amount','currency','item_date','description','receipt_present'],line_rows)
            insert_many(conn,'approvals',['approval_id','trip_id','report_id','request_type','status','action_summary','created_at'],valid_approvals)
            insert_many(conn,'policy_documents',['doc_id','source','version','effective_from','effective_to','category','file_path'],docs)
            insert_many(conn,'policy_chunks',['chunk_id','doc_id','source','section','page','version','category','text'],chunks)
            policy_index.persist_to(conn)
            for d in drafts:
                if not isinstance(d,dict) or not d.get('draft_id'):
                    problem(errors,draft_path,None,'INVALID_DRAFT','draft record missing draft_id'); continue
                conn.execute('INSERT OR IGNORE INTO draft_artifacts VALUES(?,?,?,?,?,?,?,?)',(d['draft_id'],d.get('artifact_type','unknown'),d.get('status','draft_created'),d.get('delivery_status','not_sent'),json.dumps(d.get('source_ids',[])),json.dumps(d.get('content',{})),d.get('created_at'),d.get('idempotency_key')))
    except sqlite3.IntegrityError as e:
        conn.close(); temp.unlink(missing_ok=True); raise RuntimeError(f'SQLite integrity failure; database not published: {e}') from e
    fk=list(conn.execute('PRAGMA foreign_key_check')); counts={t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['traveler_profiles','travel_requests','itineraries','itinerary_segments','approvals','expense_reports','expense_line_items','policy_documents','policy_chunks','draft_artifacts']}; conn.close()
    if fk: temp.unlink(missing_ok=True); raise RuntimeError(f'Foreign-key violations: {fk}')
    temp.replace(out)
    report={'source':str(src),'database':str(out),'counts':counts,'error_count':sum(e['severity']=='error' for e in errors),'warning_count':sum(e['severity']=='warning' for e in errors),'issues':errors}
    out.parent.joinpath('validation_report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['database','counts','error_count','warning_count']},indent=2))
    return 1 if report['error_count'] else 0

if __name__=='__main__': sys.exit(main())
