"""Render locally imported weekly reports without remote browser dependencies."""
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

class SafeHTML(HTMLParser):
    allowed = set('p br ul ol li strong b em i h1 h2 h3 h4 h5 h6 table thead tbody tr th td blockquote pre code hr'.split())
    def __init__(self):
        super().__init__()
        self.output = []
    def handle_starttag(self, tag, attrs):
        if tag in self.allowed:
            self.output.append('<'+tag+'>')
    def handle_endtag(self, tag):
        if tag in self.allowed and tag not in ('br', 'hr'):
            self.output.append('</'+tag+'>')
    def handle_data(self, data):
        self.output.append(html.escape(data))

def contents(report):
    if 'storage' not in report:
        return body(report['body'])
    parser = SafeHTML()
    parser.feed(report['storage'])
    for comment in report.get('comments', []):
        parser.feed('<hr><h3>댓글</h3>'+comment.get('body', {}).get('storage', {}).get('value', ''))
    return ''.join(parser.output)

def inline(text):
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html.escape(text.replace('\\~', '~')))

def body(markdown):
    output = []
    table = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith('|'):
            if re.fullmatch(r'[| :\-]+', stripped):
                continue
            if not table:
                output.append('<div class="weekly-table"><table>')
                table = True
            output.append('<tr>' + ''.join('<td>'+inline(c.strip())+'</td>' for c in stripped.strip('|').split('|')) + '</tr>')
            continue
        if table:
            output.append('</table></div>')
            table = False
        if not stripped:
            continue
        heading = re.match(r'^(#{1,6}) (.*)', stripped)
        if heading:
            level = min(len(heading[1])+1, 6)
            output.append(f'<h{level}>{inline(heading[2])}</h{level}>')
        elif stripped == '---':
            output.append('<hr>')
        elif stripped.startswith('* '):
            inset = ' nested' if line.startswith('    ') else ''
            output.append(f'<p class="weekly-bullet{inset}">• {inline(stripped[2:])}</p>')
        else:
            output.append('<p>'+inline(stripped)+'</p>')
    if table:
        output.append('</table></div>')
    return ''.join(output)

def render():
    reports = []
    for path in sorted(Path(__file__).parent.glob('weekly_report_*.json'), reverse=True)[:2]:
        report = json.loads(path.read_text(encoding='utf-8'))
        date = path.stem.removeprefix('weekly_report_')
        reports.append((date, report))
    options = ''.join(f'<option value="{date}">{date} 주간보고</option>' for date, _ in reports)
    cards = ''.join(f'<article data-weekly-date="{date}"'+(' hidden' if i else '')+'>'
        + f'<h3>{html.escape(r["title"])}</h3><p><a href="{html.escape(r["webUrl"], quote=True)}" target="_blank" rel="noopener">Confluence 원문 열기</a></p>'
        + contents(r) + '</article>' for i, (date, r) in enumerate(reports))
    return '<label>보고일<select id="weeklyDate">'+options+'</select></label><p class="muted">가져온 시점의 보고서 · 티켓 조회 필터와 별도로 표시됩니다.</p><div class="weekly-content">'+cards+'</div>'
