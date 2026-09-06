"""Monthly work explorer. No external AI or browser-side service calls."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

RULES = [
    ('팀 공유·권한', r'팀|team|권한|인가|role'),
    ('스토리지·Snapshot', r'storage|스토리지|저장소|snapshot|스냅샷|볼륨'),
    ('인증·계정', r'인증|로그인|회원가입|signup|credential|계정'),
    ('정산·포인트', r'정산|포인트|billing|잔액|결제|수익|충전'),
    ('PC방·Agent 안정화', r'PC\s?방|에이전트|agent|드라이버|드라이브|락스크린|VMC|WOL|재조인'),
    ('테스트·검증', r'테스트|test|검증|toolkit'),
    ('워크로드·노드 관리', r'워크로드|노드|K8S|instance|인스턴스|배포'),
    ('콘텐츠·사이트 개선', r'SEO|랜딩|콘텐츠|템플릿|블로그|약관'),
    ('외부 서비스 연계', r'한자연|NHN|OpenClaw'),
]

TAG_TOPICS = {'gcube': 'GCUBE 플랫폼', 'pcbang': 'PC방 솔루션',
              'edu': '강의 솔루션', 'test': '테스트 TOOLS'}

def topics(tags, description=''):
    tags = {t.strip().lower() for t in (tags or '').split(';') if t.strip()}
    return [name for tag, name in TAG_TOPICS.items() if tag in tags] or ['기타']

def status_group(state):
    return {'New':'새로열림', 'Ready':'새로열림', 'In Progress':'진행',
            'Active':'진행', 'Blocked':'진행', 'In Review':'리뷰',
            'Done':'완료', 'Closed':'완료'}.get(state, '새로열림')

def prepare(obj, now=None):
    now = now or datetime.now(timezone(timedelta(hours=9)))
    end = now.date().isoformat()
    start = (now.date() - timedelta(days=29)).isoformat()
    entries = []
    for r in obj['rows']:
        state, title, desc = obj['s'][r[2]], r[6] or '', r[7] or ''
        closed, changed = r[5], r[13]
        recent = bool(changed and start <= changed <= end)
        done = status_group(state) == '완료'
        completed = bool(done and closed and start <= closed <= end)
        flags = []
        if not done:
            if state == 'Blocked': flags.append('차단 상태 · 해소 조건 확인')
            if not recent: flags.append('30일 미갱신 · 현재 진행 여부 확인')
            if r[9] is None: flags.append('상태 시작일 확인 불가')
            elif state == 'In Review' and r[9] >= 7: flags.append('검토 상태 7일 이상 · 남은 검증 확인')
            elif state == 'In Progress' and r[9] >= 14: flags.append('진행 상태 14일 이상 · 최근 진척 확인')
            if not desc.strip(): flags.append('설명 미등록')
        areas = []
        for label, pattern in [('CLI', r'\bCLI\b'), ('VSCode', r'VSCE|VSCODE|EXT:|Extension'), ('Console', r'console|콘솔|User Site|Admin'), ('Agent', r'agent|에이전트|VMC'), ('API', r'API|백엔드|backend')]:
            if re.search(pattern, title, re.I): areas.append(label)
        entries.append(dict(id=r[0], title=title, description=desc, state=state,
                            who=obj['a'][r[3]], type=obj['t'][r[1]], created=r[4], closed=closed,
                            changed=changed, recent=recent, completed=completed, done=done,
                            topics=topics(r[14] if len(r)>14 else ''),
                            tags=r[14] if len(r)>14 else '', group=status_group(state),
                            areas=areas, flags=flags, dwell=r[9]))
    return dict(start=start, end=end, generated=now.isoformat(timespec='minutes'),
                preview=obj.get('preview', False), entries=entries)

def render(obj, now=None):
    payload = json.dumps(prepare(obj, now), ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return Path(__file__).with_name('report_template.html').read_text(encoding='utf-8').replace('__REPORT_DATA__', payload).replace('__WEEKLY_REPORTS__', __import__('weekly_reports').render())


def render_charts(obj, now=None):
    payload = json.dumps(prepare(obj, now), ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return Path(__file__).with_name('chart_template.html').read_text(encoding='utf-8').replace('__REPORT_DATA__', payload)

