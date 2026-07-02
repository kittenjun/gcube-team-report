# -*- coding: utf-8 -*-
"""
GCUBE 팀 작업현황 리포트 생성기 (GitHub Actions / 로컬 공용).

데이터 출처: Azure DevOps REST API (개인용 액세스 토큰 PAT 사용).
- 환경변수:
    AZDO_PAT      (필수)  Azure DevOps 개인 액세스 토큰. Work Items 읽기 권한.
    AZDO_ORG      (선택, 기본 data-alliance-com)
    AZDO_PROJECT  (선택, 기본 GCUBE)
    AZDO_MEMBERS  (선택) 쉼표구분 displayName. 기본: 조광현,권상준,장호진,임채윤,구지연
- 출력: index.html (현재 디렉터리)
- 조회 범위: 실행 시각 기준 최근 30일(rolling) 이후 System.ChangedDate, State!=Removed, 대상 팀원.
- 팀원별 업무 내역 요약: 최근 14일 이내 변경된 항목만 기준으로 작성.

로컬 테스트: AZDO_PAT 없이 `TEST=1 python generate_report.py` 로 실행하면
data.json(미리 만들어 둔 동일 구조)을 읽어 index.html 생성만 검증한다.
"""
import os, json, base64, re, statistics
import urllib.request
from datetime import datetime, timezone, timedelta

ORG     = os.environ.get("AZDO_ORG", "data-alliance-com")
PROJECT = os.environ.get("AZDO_PROJECT", "GCUBE")
MEMBERS = [m.strip() for m in os.environ.get(
    "AZDO_MEMBERS", "조광현,권상준,장호진,임채윤,구지연").split(",") if m.strip()]

WINDOW_DAYS  = 30   # 전체 리포트 조회 범위
SUMMARY_DAYS = 14   # 팀원별 업무 내역 요약 기준 범위

BASE = "https://dev.azure.com/{}/{}/_apis/wit/".format(ORG, PROJECT)

PROJECT_DESC = {
 "한자연·NHN 연동": "한국자동차연구원·NHN 클라우드 연동 및 OpenClaw 배포·세미나 관련 작업",
 "플랫폼(User Site·Admin)": "GCUBE 사용자 사이트·관리자 사이트 프론트엔드 및 기능 개발/최적화",
 "EDU": "교육용(EDU) 워크로드 배포·관리 기능 개발 및 QA 피드백 대응",
 "PC방": "PC방 전용 클라이언트·웹 콘솔·런타임 운영 및 패치 대응",
 "CLI·확장": "GCUBE CLI 및 확장 도구 구현",
 "템플릿·콘텐츠": "워크로드 템플릿·사용자 게시 콘텐츠 관리 기능",
 "정산·포인트": "빌링·잔액 계산·차단 판정 등 정산/포인트 기능",
 "인프라·Agent": "Window/PC Agent, 컨테이너·이미지 풀링 등 인프라 운영·디버깅",
 "기타": "분류되지 않은 사전 조사·기획 등 기타 작업",
}

# ---------------- HTTP ----------------
def _headers():
    pat = os.environ["AZDO_PAT"]
    auth = base64.b64encode((":" + pat).encode()).decode()
    return {"Authorization": "Basic " + auth,
            "Content-Type": "application/json", "Accept": "application/json"}

def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def _get(url):
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

# ---------------- helpers ----------------
def parse_dt(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    s = re.sub(r"\.(\d{6})\d+", r".\1", s)  # trim sub-microsecond
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None

def strip_html(h):
    if not h:
        return ""
    t = re.sub(r"<[^>]+>", " ", h)
    for a, b in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")]:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()

def classify(t):
    t = t or ""
    if re.search(r"한자연|NHN|Open\s?Claw|OpenClaw", t, re.I): return "한자연·NHN 연동"
    if re.search(r"PC\s?방", t): return "PC방"
    if re.search(r"EDU", t): return "EDU"
    if re.search(r"Billing|정산|포인트|잔액|차단", t, re.I): return "정산·포인트"
    if re.search(r"CLI|확장|Extension", t, re.I): return "CLI·확장"
    if re.search(r"템플릿|콘텐츠|게시", t): return "템플릿·콘텐츠"
    if re.search(r"Agent|Container|컨테이너|image_pull|WoL|워크로드 상태", t, re.I): return "인프라·Agent"
    if re.search(r"User Site|Admin|사용자|FE:|FE |Next\.js|Lighthouse", t): return "플랫폼(User Site·Admin)"
    return "기타"

def reason(state, wtype, dwell, carry):
    if state == "Done": return "정상"
    c = carry or 0; dw = dwell or 0
    if c >= 3: return "반복 이월"
    if state == "New" and dw >= 30: return "장기 미착수"
    if wtype in ("Epic", "Feature"): return "대형 과제(분할 필요)"
    if state == "New" and dw >= 14: return "착수 지연"
    if state == "In Progress" and dw >= 14: return "진행 정체(블로커 가능)"
    if state == "In Review" and dw >= 7: return "리뷰 대기"
    return "정상"

# ---------------- data collection ----------------
def collect():
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS)

    wiql = _post(BASE + "wiql?api-version=7.0",
                 {"query": "SELECT [System.Id] FROM WorkItems WHERE "
                           "[System.TeamProject]='%s' ORDER BY [System.ChangedDate] DESC" % PROJECT})
    ids = [w["id"] for w in wiql.get("workItems", [])]

    fields = ["System.Id", "System.WorkItemType", "System.State", "System.AssignedTo",
              "System.CreatedDate", "System.ChangedDate", "System.Title",
              "Microsoft.VSTS.Common.Priority", "Microsoft.VSTS.Common.ClosedDate",
              "System.IterationPath"]
    items = []
    for i in range(0, len(ids), 200):
        batch = _post(BASE + "workitemsbatch?api-version=7.0",
                      {"ids": ids[i:i+200], "fields": fields})
        items += batch.get("value", [])

    def member_of(f):
        a = f.get("System.AssignedTo") or {}
        nm = a.get("displayName", "") or ""
        for t in MEMBERS:
            if t in nm:
                return t
        return None

    filt = []
    for w in items:
        f = w.get("fields", {})
        if f.get("System.State") == "Removed":
            continue
        if member_of(f) is None:
            continue
        ch = parse_dt(f.get("System.ChangedDate"))
        if ch is None or ch < window_start:
            continue
        filt.append(w)

    # descriptions
    desc = {}
    fids = [w["id"] for w in filt]
    for i in range(0, len(fids), 200):
        batch = _post(BASE + "workitemsbatch?api-version=7.0",
                      {"ids": fids[i:i+200],
                       "fields": ["System.Id", "System.Description", "Microsoft.VSTS.TCM.ReproSteps"]})
        for w in batch.get("value", []):
            f = w.get("fields", {})
            desc[w["id"]] = strip_html(f.get("System.Description") or
                                       f.get("Microsoft.VSTS.TCM.ReproSteps") or "")

    # updates for open items -> dwell + sprint carry
    upd = {}
    for w in filt:
        st = w["fields"].get("System.State")
        if st == "Done":
            continue
        try:
            j = _get(BASE + "workItems/%s/updates?api-version=7.0" % w["id"])
        except Exception:
            j = {"value": []}
        last = None
        iters = set()
        for u in j.get("value", []):
            ff = u.get("fields", {})
            sc = ff.get("System.State")
            if sc and sc.get("newValue") == st:
                dt = None
                cd = ff.get("System.ChangedDate")
                if cd and cd.get("newValue"):
                    d = parse_dt(cd["newValue"])
                    if d and d.year < 9000:
                        dt = d
                if dt is None and u.get("revisedDate"):
                    d = parse_dt(u["revisedDate"])
                    if d and d.year < 9000:
                        dt = d
                if dt:
                    last = dt
            ip = ff.get("System.IterationPath")
            if ip:
                if ip.get("newValue"): iters.add(ip["newValue"])
                if ip.get("oldValue"): iters.add(ip["oldValue"])
        if not iters and w["fields"].get("System.IterationPath"):
            iters.add(w["fields"]["System.IterationPath"])
        base = last or parse_dt(w["fields"].get("System.ChangedDate")) or now
        upd[w["id"]] = {"dwell": (now - base).days, "carry": len(iters)}

    # enrich -> compact object
    assignees, projects, reasons, types, states = [], [], [], [], []
    def idx(arr, v):
        if v not in arr:
            arr.append(v)
        return arr.index(v)
    dp = lambda s: (s[:10] if s else None)

    rows = []
    for w in filt:
        f = w["fields"]
        who = member_of(f)
        st = f.get("System.State"); ty = f.get("System.WorkItemType")
        u = upd.get(w["id"])
        dwell = u["dwell"] if u else None
        carry = u["carry"] if u else None
        cyc = None
        if st == "Done" and f.get("Microsoft.VSTS.Common.ClosedDate"):
            c = parse_dt(f["Microsoft.VSTS.Common.ClosedDate"])
            cr = parse_dt(f.get("System.CreatedDate"))
            if c and cr:
                cyc = round((c - cr).total_seconds() / 86400)
        rows.append([
            w["id"], idx(types, ty), idx(states, st), idx(assignees, who),
            dp(f.get("System.CreatedDate")), dp(f.get("Microsoft.VSTS.Common.ClosedDate")),
            f.get("System.Title"), (desc.get(w["id"], "") or "")[:45],
            idx(projects, classify(f.get("System.Title"))),
            dwell, carry, idx(reasons, reason(st, ty, dwell, carry)), cyc,
            dp(f.get("System.ChangedDate")),
        ])
    return {"a": assignees, "p": projects, "r": reasons, "t": types, "s": states,
            "cols": ["id", "type", "state", "assignee", "created", "closed", "title",
                     "desc", "project", "dwell", "carry", "reason", "cycle", "changed"],
            "rows": rows}

# ---------------- HTML ----------------
TEMPLATE = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GCUBE 팀 작업현황 리포트</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js"></script>
<style>
:root{color-scheme:light;
 --bg:#f5f7fa;--card:#ffffff;--ink:#1f2733;--muted:#6b7787;--line:#e6eaf0;
 --brand:#2563eb;--brand2:#7c3aed;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;--info:#0891b2;
 --chipbg:#eef2ff;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI","Malgun Gothic",AppleSDGothicNeo,sans-serif;font-size:14px;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:20px 18px 60px}
header.top{background:linear-gradient(120deg,#1e3a8a,#6d28d9);color:#fff;border-radius:14px;padding:22px 24px;margin-bottom:18px}
header.top h1{margin:0 0 6px;font-size:22px}
header.top .meta{font-size:12.5px;opacity:.92}
header.top .meta b{font-weight:600}
.note{display:inline-block;margin-top:8px;background:rgba(255,255,255,.16);padding:3px 10px;border-radius:20px;font-size:11.5px}
h2.sec{font-size:16px;margin:26px 0 12px;padding-left:10px;border-left:4px solid var(--brand)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:700}
.kpi .l{font-size:12px;color:var(--muted);margin-top:2px}
.kpi.warn .v{color:var(--warn)} .kpi.ok .v{color:var(--ok)} .kpi.bad .v{color:var(--bad)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.pcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.pcard h3{margin:0 0 4px;font-size:14.5px}
.pcard .pd{font-size:11.8px;color:var(--muted);min-height:32px;margin-bottom:8px}
.pcard .stats{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.pcard .who{font-size:11.5px;color:var(--muted)}
.pill{font-size:11px;padding:2px 8px;border-radius:20px;background:var(--chipbg);color:var(--brand);font-weight:600}
.pill.ok{background:#dcfce7;color:#15803d}.pill.inp{background:#fef3c7;color:#b45309}.pill.new{background:#e0f2fe;color:#0369a1}
.pill.rev{background:#ede9fe;color:#6d28d9}.pill.bad{background:#fee2e2;color:#b91c1c}
.mcards{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:780px){.mcards{grid-template-columns:1fr}}
.mcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.mcard .mh{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
.mcard .mh b{font-size:15px}
.mcard .mh .cyc{font-size:11px;color:var(--muted);font-weight:400}
.mcard .badges{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.mcard .txt{font-size:12.7px;color:var(--ink);margin:0}
.summ-note{font-size:11.5px;color:var(--muted);margin:0 0 10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:780px){.grid2{grid-template-columns:1fr}}
.chartbox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.chartbox h4{margin:0 0 10px;font-size:13px;color:var(--muted);font-weight:600}
.cwrap{position:relative;height:260px}
.insights{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 18px;margin-bottom:12px}
.insights li{margin:8px 0;font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:9px 11px;text-align:left;border-bottom:1px solid var(--line);font-size:12.5px;vertical-align:top}
th{background:#f0f3f8;color:var(--muted);font-weight:600;position:sticky;top:0}
tbody tr{cursor:pointer}
tbody tr:hover{background:#f3f6fc}
tbody tr.donerow{background:#fbfdfb}
tbody tr.donerow:hover{background:#f1f8f1}
.tbl-scroll{max-height:560px;overflow:auto;border-radius:12px;border:1px solid var(--line)}
.tbl-scroll table{border:none}
.tabtitle{display:flex;align-items:center;gap:8px;margin:16px 0 8px;font-size:14px;font-weight:600}
.tabtitle .cnt{color:var(--muted);font-weight:400;font-size:12px}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.dot.ok{background:var(--ok)}.dot.op{background:var(--warn)}
.tg{font-size:10.5px;padding:1px 7px;border-radius:6px;font-weight:600;white-space:nowrap}
.s-Done{background:#dcfce7;color:#15803d}.s-New{background:#e0f2fe;color:#0369a1}
.s-InProgress{background:#fef3c7;color:#b45309}.s-InReview{background:#ede9fe;color:#6d28d9}.s-Ready{background:#f1f5f9;color:#475569}
.rn{font-size:10.5px;padding:1px 7px;border-radius:6px;background:#fee2e2;color:#b91c1c;font-weight:600;white-space:nowrap}
.rn.ok{background:#f1f5f9;color:#64748b}
.donetag{font-size:10.5px;padding:1px 7px;border-radius:6px;background:#dcfce7;color:#15803d;font-weight:600;white-space:nowrap}
.desc{color:var(--muted);font-size:11.3px;margin-top:3px}
.proj-tag{font-size:10.5px;color:var(--brand2);font-weight:600}
.legend{font-size:11px;color:var(--muted);margin:4px 0 0}
.footer{margin-top:30px;font-size:11px;color:var(--muted);text-align:center}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
 <h1>GCUBE 팀 작업현황 리포트</h1>
 <div class="meta">
  <b>생성일</b> <span id="genDate"></span> &nbsp;·&nbsp;
  <b>조회 범위</b> <span id="rangeLabel"></span> (최근 30일 롤링) &nbsp;·&nbsp;
  <b>대상</b> <span id="memLabel"></span>
 </div>
 <div class="note">※ State="Removed"(삭제) 항목 제외 &nbsp;|&nbsp; 팀원별 업무 요약은 최근 14일 기준 &nbsp;|&nbsp; 데이터: Azure DevOps · GCUBE · 자동 생성</div>
</header>

<h2 class="sec">① 핵심 지표 (KPI)</h2>
<div class="kpis" id="kpis"></div>

<h2 class="sec">② 프로젝트별 현황</h2>
<div class="cards" id="cards"></div>

<h2 class="sec">③ 팀원별 업무 내역 요약 <span style="font-size:12px;color:var(--muted);font-weight:400">(최근 14일)</span></h2>
<p class="summ-note" id="summNote"></p>
<div class="mcards" id="memSummary"></div>

<h2 class="sec">④ 정체·병목 분석</h2>
<ul class="insights" id="insights"></ul>
<div class="tbl-scroll">
 <table><thead><tr>
  <th>ID</th><th>제목</th><th>프로젝트</th><th>담당</th><th>상태</th><th>추정 원인</th><th>상태 체류일</th><th>스프린트 이월</th>
 </tr></thead><tbody id="stagBody"></tbody></table>
</div>

<h2 class="sec">⑤ 처리 현황 차트</h2>
<div class="grid2">
 <div class="chartbox"><h4>프로젝트별 완료 vs 열림</h4><div class="cwrap"><canvas id="cProj"></canvas></div></div>
 <div class="chartbox"><h4>주간 완료 추세 (완료일 기준)</h4><div class="cwrap"><canvas id="cWeek"></canvas></div></div>
 <div class="chartbox"><h4>팀원별 처리량</h4><div class="cwrap"><canvas id="cMember"></canvas></div></div>
 <div class="chartbox"><h4>팀원별 사이클타임 중앙값 (일)</h4><div class="cwrap"><canvas id="cCycle"></canvas></div></div>
</div>

<h2 class="sec">⑥ 팀원 비교</h2>
<div class="tbl-scroll">
 <table><thead><tr>
  <th>팀원</th><th>완료</th><th>진행중</th><th>신규</th><th>열림(전체)</th><th>사이클타임 중앙값</th><th>정체(주의)</th>
 </tr></thead><tbody id="memBody"></tbody></table>
</div>

<h2 class="sec">⑦ 항목 상세</h2>
<p class="legend">행을 클릭하면 Azure DevOps 작업 항목으로 이동합니다. 완료 항목과 열림(진행·신규) 항목을 분리해 표시합니다.</p>
<div class="tabtitle"><span class="dot ok"></span>완료 항목 <span class="cnt" id="doneCount"></span></div>
<div class="tbl-scroll">
 <table><thead><tr>
  <th>ID</th><th>제목 / 설명</th><th>프로젝트</th><th>유형</th><th>담당</th><th>완료일</th><th>구분</th>
 </tr></thead><tbody id="doneBody"></tbody></table>
</div>
<div class="tabtitle"><span class="dot op"></span>열림(진행·신규) 항목 <span class="cnt" id="openCount"></span></div>
<div class="tbl-scroll">
 <table><thead><tr>
  <th>ID</th><th>제목 / 설명</th><th>프로젝트</th><th>유형</th><th>담당</th><th>상태</th><th>상태/원인</th>
 </tr></thead><tbody id="openBody"></tbody></table>
</div>

<div class="footer">자동 생성 리포트 · GCUBE 팀 · Azure DevOps 데이터 기반</div>
</div>

<script>
const D = __DATA__;
const PDESC = __PDESC__;
const GENDATE = "__GENDATE__";
const RANGELABEL = "__RANGELABEL__";
const MEMLABEL = "__MEMLABEL__";
const EDIT_BASE = "__EDITBASE__";
const CUT14 = "__CUT14__";
const A=D.a,P=D.p,R=D.r,T=D.t,S=D.s,ROWS=D.rows;
const C={id:0,type:1,state:2,assignee:3,created:4,closed:5,title:6,desc:7,project:8,dwell:9,carry:10,reason:11,cycle:12,changed:13};
const iDone=S.indexOf('Done'),iInp=S.indexOf('In Progress'),iNew=S.indexOf('New'),iRev=S.indexOf('In Review');
const iNormal=R.indexOf('정상');
const EDIT=EDIT_BASE;
function esc(s){return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function median(a){if(!a.length)return null;const b=[...a].sort((x,y)=>x-y);const m=b.length>>1;return b.length%2?b[m]:Math.round((b[m-1]+b[m])/2*10)/10;}
function clip(s,n){s=s||'';return s.length>n?s.slice(0,n-1)+'…':s;}

document.getElementById('genDate').textContent=GENDATE;
document.getElementById('rangeLabel').textContent=RANGELABEL;
document.getElementById('memLabel').textContent=MEMLABEL;

const total=ROWS.length;
const done=ROWS.filter(r=>r[C.state]===iDone);
const open=ROWS.filter(r=>r[C.state]!==iDone);
const inp=ROWS.filter(r=>r[C.state]===iInp);
const nw=ROWS.filter(r=>r[C.state]===iNew);
const stag=open.filter(r=>r[C.reason]!==iNormal);
const cyc=done.map(r=>r[C.cycle]).filter(v=>v!=null);
const medCyc=median(cyc);
const compRate=total?Math.round(done.length/total*100):0;
const kpis=[
 {v:total,l:'전체 활동 항목',c:''},
 {v:done.length+' ('+compRate+'%)',l:'완료',c:'ok'},
 {v:open.length,l:'열림(미완료)',c:''},
 {v:inp.length,l:'진행 중',c:''},
 {v:nw.length,l:'신규',c:''},
 {v:stag.length,l:'정체 주의',c:'warn'},
 {v:(medCyc==null?'-':medCyc+'일'),l:'사이클타임 중앙값',c:''},
];
document.getElementById('kpis').innerHTML=kpis.map(k=>
 `<div class="kpi ${k.c}"><div class="v">${k.v}</div><div class="l">${k.l}</div></div>`).join('');

const projAgg={};
P.forEach(p=>projAgg[p]={done:0,inp:0,nw:0,open:0,total:0,who:new Set()});
ROWS.forEach(r=>{const p=P[r[C.project]];const a=projAgg[p];a.total++;a.who.add(A[r[C.assignee]]);
 if(r[C.state]===iDone)a.done++;else{a.open++;if(r[C.state]===iInp)a.inp++;if(r[C.state]===iNew)a.nw++;}});
const projOrder=Object.keys(projAgg).sort((x,y)=>projAgg[y].total-projAgg[x].total);
document.getElementById('cards').innerHTML=projOrder.map(p=>{const a=projAgg[p];return `
 <div class="pcard">
  <h3>${esc(p)} <span class="pill">${a.total}건</span></h3>
  <div class="pd">${esc(PDESC[p]||'')}</div>
  <div class="stats">
   <span class="pill ok">완료 ${a.done}</span>
   <span class="pill inp">진행 ${a.inp}</span>
   <span class="pill new">신규 ${a.nw}</span>
  </div>
  <div class="who">담당: ${[...a.who].map(esc).join(', ')}</div>
 </div>`;}).join('');

/* ③ 팀원별 업무 내역 요약 — 최근 14일(CUT14) 기준 */
const recent14=ROWS.filter(r=>r[C.changed]&&r[C.changed]>=CUT14);
document.getElementById('summNote').textContent=
 `최근 14일(${CUT14} 이후) 변경된 ${recent14.length}건을 기준으로 팀원별 활동을 요약했습니다.`;
function narrative(m){
 const rr=recent14.filter(r=>A[r[C.assignee]]===m);
 if(!rr.length) return {badges:{done:0,inp:0,nw:0,rev:0,stag:0},cyc:null,text:'최근 14일간 변경된 담당 항목이 없습니다.'};
 const d=rr.filter(r=>r[C.state]===iDone);
 const ip=rr.filter(r=>r[C.state]===iInp);
 const nn=rr.filter(r=>r[C.state]===iNew);
 const rv=rr.filter(r=>r[C.state]===iRev);
 const wn=rr.filter(r=>r[C.state]!==iDone&&r[C.reason]!==iNormal);
 const pc={};rr.forEach(r=>{const p=P[r[C.project]];pc[p]=(pc[p]||0)+1;});
 const tops=Object.keys(pc).sort((x,y)=>pc[y]-pc[x]).slice(0,2);
 const parts=[];
 parts.push(`최근 14일간 ${rr.length}건을 다뤘으며 주로 <b>${esc(tops.join(', '))}</b> 영역에 집중했습니다.`);
 if(d.length){parts.push(`완료 ${d.length}건(예: ${esc(d.slice(0,3).map(r=>clip(r[C.title],24)).join(', '))}).`);}
 else{parts.push('이 기간 완료 처리된 항목은 없습니다.');}
 const pb=[];
 if(ip.length)pb.push(`진행 중 ${ip.length}건(${esc(clip(ip[0][C.title],22))} 등)`);
 if(rv.length)pb.push(`리뷰 대기 ${rv.length}건`);
 if(nn.length)pb.push(`신규 ${nn.length}건`);
 if(pb.length)parts.push('현재 '+pb.join(', ')+'.');
 if(wn.length){const w=wn.slice().sort((a,b)=>(b[C.dwell]||0)-(a[C.dwell]||0))[0];
  parts.push(`정체 주의 ${wn.length}건 — 대표적으로 '${esc(clip(w[C.title],28))}'이(가) <b>${esc(R[w[C.reason]])}</b>(상태 체류 ${w[C.dwell]==null?'-':w[C.dwell]+'일'}).`);}
 const md=median(d.map(r=>r[C.cycle]).filter(v=>v!=null));
 return {badges:{done:d.length,inp:ip.length,nw:nn.length,rev:rv.length,stag:wn.length},cyc:md,text:parts.join(' ')};
}
const summOrder=A.filter(m=>m);
document.getElementById('memSummary').innerHTML=summOrder.map(m=>{const n=narrative(m);const b=n.badges;return `
 <div class="mcard">
  <div class="mh"><b>${esc(m)}</b><span class="cyc">사이클타임 중앙값 ${n.cyc==null?'–':n.cyc+'일'}</span></div>
  <div class="badges">
   <span class="pill ok">완료 ${b.done}</span>
   <span class="pill inp">진행 ${b.inp}</span>
   <span class="pill new">신규 ${b.nw}</span>
   <span class="pill rev">리뷰 ${b.rev}</span>
   <span class="pill bad">정체 ${b.stag}</span>
  </div>
  <p class="txt">${n.text}</p>
 </div>`;}).join('');

/* ④ 정체·병목 */
const ins=[];
ins.push(`전체 <b>${total}</b>건 중 완료 <b>${done.length}</b>건(${compRate}%), 열림 <b>${open.length}</b>건. 이 중 <b>${stag.length}</b>건이 정체(주의) 상태입니다.`);
const longNew=stag.filter(r=>r[C.state]===iNew&&r[C.dwell]>=30).sort((a,b)=>b[C.dwell]-a[C.dwell]);
if(longNew.length)ins.push(`<b>장기 미착수</b>: '${esc(longNew[0][C.title])}'(#${longNew[0][C.id]})가 신규 상태로 약 <b>${longNew[0][C.dwell]}일</b> 정체 — 최우선 점검 필요.`);
const carry=stag.filter(r=>r[C.carry]>=3).sort((a,b)=>b[C.carry]-a[C.carry]);
if(carry.length)ins.push(`<b>반복 이월</b> ${carry.length}건: '${esc(carry[0][C.title])}'(#${carry[0][C.id]})은 서로 다른 스프린트 <b>${carry[0][C.carry]}개</b>를 거침 — 범위 축소/재계획 권장.`);
const blocker=stag.filter(r=>R[r[C.reason]]==='진행 정체(블로커 가능)').sort((a,b)=>b[C.dwell]-a[C.dwell]);
if(blocker.length)ins.push(`<b>진행 정체(블로커 가능)</b> ${blocker.length}건: '${esc(blocker[0][C.title])}'(#${blocker[0][C.id]})가 In Progress로 <b>${blocker[0][C.dwell]}일</b> 체류 — 블로커 확인 필요.`);
const big=stag.filter(r=>R[r[C.reason]]==='대형 과제(분할 필요)');
if(big.length)ins.push(`<b>대형 과제</b> ${big.length}건(Epic/Feature)은 분할이 필요할 수 있습니다.`);
const rev=stag.filter(r=>R[r[C.reason]]==='리뷰 대기');
if(rev.length)ins.push(`<b>리뷰 대기</b> ${rev.length}건이 In Review에서 대기 중 — 리뷰어 배정 점검.`);
document.getElementById('insights').innerHTML=ins.map(t=>`<li>${t}</li>`).join('');

const stagSorted=[...stag].sort((a,b)=>(b[C.dwell]||0)-(a[C.dwell]||0));
document.getElementById('stagBody').innerHTML=stagSorted.map(r=>rowTr(r,`
  <td>#${r[C.id]}</td><td>${esc(r[C.title])}</td><td class="proj-tag">${esc(P[r[C.project]])}</td>
  <td>${esc(A[r[C.assignee]])}</td><td>${stateTag(r[C.state])}</td>
  <td><span class="rn">${esc(R[r[C.reason]])}</span></td>
  <td>${r[C.dwell]==null?'-':r[C.dwell]+'일'}</td><td>${r[C.carry]==null?'-':r[C.carry]}</td>`)).join('');

/* ⑥ 팀원 비교 (30일 전체 기준) */
const memAgg={};
A.forEach(a=>memAgg[a]={done:0,inp:0,nw:0,open:0,stag:0,cyc:[]});
ROWS.forEach(r=>{const m=A[r[C.assignee]];const x=memAgg[m];
 if(r[C.state]===iDone){x.done++;if(r[C.cycle]!=null)x.cyc.push(r[C.cycle]);}
 else{x.open++;if(r[C.state]===iInp)x.inp++;if(r[C.state]===iNew)x.nw++;if(r[C.reason]!==iNormal)x.stag++;}});
const memOrder=Object.keys(memAgg).sort((x,y)=>(memAgg[y].done+memAgg[y].open)-(memAgg[x].done+memAgg[x].open));
document.getElementById('memBody').innerHTML=memOrder.map(m=>{const x=memAgg[m];const mc=median(x.cyc);return `
 <tr><td><b>${esc(m)}</b></td><td>${x.done}</td><td>${x.inp}</td><td>${x.nw}</td><td>${x.open}</td>
 <td>${mc==null?'-':mc+'일'}</td><td>${x.stag?('<span class="rn">'+x.stag+'</span>'):'0'}</td></tr>`;}).join('');

/* ⑦ 항목 상세 — 완료 / 열림 분리 */
const doneSorted=[...done].sort((a,b)=>(b[C.closed]||'').localeCompare(a[C.closed]||''));
document.getElementById('doneCount').textContent='('+done.length+'건)';
document.getElementById('doneBody').innerHTML=doneSorted.map(r=>rowTr(r,`
  <td>#${r[C.id]}</td>
  <td>${esc(r[C.title])}${r[C.desc]?('<div class="desc">'+esc(r[C.desc])+'</div>'):''}</td>
  <td class="proj-tag">${esc(P[r[C.project]])}</td>
  <td>${esc(T[r[C.type]])}</td><td>${esc(A[r[C.assignee]])}</td>
  <td>${r[C.closed]?esc(r[C.closed]):'-'}</td><td><span class="donetag">완료</span></td>`,'donerow')).join('');
const stateRank={};stateRank[iInp]=0;stateRank[iRev]=1;stateRank[iNew]=2;
const openSorted=[...open].sort((a,b)=>{
 const ra=(a[C.reason]!==iNormal?0:1),rb=(b[C.reason]!==iNormal?0:1);
 if(ra!==rb)return ra-rb;
 return (b[C.dwell]||0)-(a[C.dwell]||0);});
document.getElementById('openCount').textContent='('+open.length+'건)';
document.getElementById('openBody').innerHTML=openSorted.map(r=>{
 const rz=R[r[C.reason]];
 const tail=(r[C.reason]!==iNormal)?`<span class="rn">${esc(rz)}</span>`:`<span class="rn ok">정상</span>`;
 return rowTr(r,`
  <td>#${r[C.id]}</td>
  <td>${esc(r[C.title])}${r[C.desc]?('<div class="desc">'+esc(r[C.desc])+'</div>'):''}</td>
  <td class="proj-tag">${esc(P[r[C.project]])}</td>
  <td>${esc(T[r[C.type]])}</td><td>${esc(A[r[C.assignee]])}</td>
  <td>${stateTag(r[C.state])}</td><td>${tail}</td>`);}).join('');

function stateTag(si){const n=S[si];const cls='s-'+n.replace(/\s/g,'');return `<span class="tg ${cls}">${esc(n)}</span>`;}
function rowTr(r,inner,cls){return `<tr class="${cls||''}" onclick="window.open('${EDIT}${r[C.id]}','_blank')">${inner}</tr>`;}

const PALETTE=['#2563eb','#7c3aed','#16a34a','#d97706','#dc2626','#0891b2','#db2777','#65a30d','#64748b'];
Chart.defaults.font.family='"Segoe UI","Malgun Gothic",sans-serif';
Chart.defaults.font.size=11;
new Chart(document.getElementById('cProj'),{type:'bar',data:{labels:projOrder,
 datasets:[{label:'완료',data:projOrder.map(p=>projAgg[p].done),backgroundColor:'#16a34a'},
  {label:'열림',data:projOrder.map(p=>projAgg[p].open),backgroundColor:'#d97706'}]},
 options:{responsive:true,maintainAspectRatio:false,scales:{x:{stacked:true,ticks:{maxRotation:40,minRotation:0}},y:{stacked:true,beginAtZero:true}},plugins:{legend:{position:'bottom'}}}});
function weekKey(ds){const d=new Date(ds+'T00:00:00Z');const day=(d.getUTCDay()+6)%7;d.setUTCDate(d.getUTCDate()-day);return d.toISOString().slice(0,10);}
const wk={};done.forEach(r=>{if(r[C.closed]){const k=weekKey(r[C.closed]);wk[k]=(wk[k]||0)+1;}});
const wkeys=Object.keys(wk).sort();
new Chart(document.getElementById('cWeek'),{type:'line',data:{labels:wkeys.map(k=>k.slice(5)),
 datasets:[{label:'주간 완료',data:wkeys.map(k=>wk[k]),borderColor:'#2563eb',backgroundColor:'rgba(37,99,235,.15)',fill:true,tension:.3,pointRadius:3}]},
 options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true,ticks:{precision:0}}},plugins:{legend:{display:false}}}});
new Chart(document.getElementById('cMember'),{type:'bar',data:{labels:memOrder,
 datasets:[{label:'완료',data:memOrder.map(m=>memAgg[m].done),backgroundColor:'#16a34a'},
  {label:'진행',data:memOrder.map(m=>memAgg[m].inp),backgroundColor:'#d97706'},
  {label:'신규',data:memOrder.map(m=>memAgg[m].nw),backgroundColor:'#0ea5e9'}]},
 options:{responsive:true,maintainAspectRatio:false,scales:{x:{stacked:true},y:{stacked:true,beginAtZero:true}},plugins:{legend:{position:'bottom'}}}});
new Chart(document.getElementById('cCycle'),{type:'bar',data:{labels:memOrder,
 datasets:[{label:'사이클타임 중앙값(일)',data:memOrder.map(m=>median(memAgg[m].cyc)||0),backgroundColor:'#7c3aed'}]},
 options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true}},plugins:{legend:{display:false}}}});
</script>
</body>
</html>'''

def build_html(obj):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=WINDOW_DAYS)
    range_label = "%s ~ %s" % (start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"))
    cut14 = (now - timedelta(days=SUMMARY_DAYS)).strftime("%Y-%m-%d")
    html = TEMPLATE
    html = html.replace("__DATA__", json.dumps(obj, ensure_ascii=False))
    html = html.replace("__PDESC__", json.dumps(PROJECT_DESC, ensure_ascii=False))
    html = html.replace("__GENDATE__", now.strftime("%Y-%m-%d"))
    html = html.replace("__RANGELABEL__", range_label)
    html = html.replace("__MEMLABEL__", "·".join(MEMBERS))
    html = html.replace("__CUT14__", cut14)
    html = html.replace("__EDITBASE__",
                        "https://dev.azure.com/%s/%s/_workitems/edit/" % (ORG, PROJECT))
    return html

def main():
    if os.environ.get("TEST") == "1" and "AZDO_PAT" not in os.environ:
        obj = json.load(open("data.json", encoding="utf-8"))
        print("[TEST] data.json 사용, rows=%d" % len(obj["rows"]))
    else:
        obj = collect()
        print("수집 완료: rows=%d" % len(obj["rows"]))
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(obj))
    print("index.html 작성 완료")

if __name__ == "__main__":
    main()
