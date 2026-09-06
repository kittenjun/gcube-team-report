"""Import weekly pages below the team meeting root. Credentials stay in env."""
import base64
import json
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

SITE = 'https://data-alliance.atlassian.net'
ROOT = '2747334657'

def report_date(title):
    match = re.fullmatch(r'주간업무\s+(\d{4})[.\- ]+\s*(\d{1,2})[.\- ]+\s*(\d{1,2})\s*', title)
    return date(*map(int, match.groups())).isoformat() if match else None

class Client:
    def __init__(self):
        email = os.environ['CONFLUENCE_EMAIL']
        token = os.environ['CONFLUENCE_API_TOKEN']
        if not email or not token:
            raise ValueError('Confluence Secrets are empty')
        self.auth = 'Basic ' + base64.b64encode(f'{email}:{token}'.encode()).decode()

    def get(self, path):
        url = urljoin(SITE, path)
        if urlsplit(url).netloc != urlsplit(SITE).netloc:
            raise ValueError('Unexpected pagination host')
        with urlopen(Request(url, headers={'Authorization': self.auth, 'Accept': 'application/json'}), timeout=60) as response:
            return json.load(response)

    def pages(self, path):
        while path:
            data = self.get(path)
            yield from data['results']
            path = data.get('_links', {}).get('next')

def collect(client):
    reports = {}
    candidates = {}
    for entry in client.pages(f'/wiki/api/v2/pages/{ROOT}/descendants?limit=250'):
        if entry.get('type') != 'page':
            continue
        day = report_date(entry['title'])
        if not day:
            continue
        candidates.setdefault(day, {})[entry['id']] = entry
    for day in sorted(candidates, reverse=True)[:2]:
        if len(candidates[day]) > 1:
            raise ValueError(f'Duplicate recent weekly report date: {day}')
        entry = next(iter(candidates[day].values()))
        page = client.get(f'/wiki/api/v2/pages/{entry["id"]}?body-format=storage')
        comments = list(client.pages(f'/wiki/api/v2/pages/{entry["id"]}/footer-comments?body-format=storage&limit=100'))
        reports[day] = dict(id=page['id'], title=page['title'], body='',
            storage=page['body']['storage']['value'], comments=comments,
            webUrl=f'{SITE}/wiki/spaces/PLAT/pages/{page["id"]}')
    if not reports:
        raise ValueError('No weekly reports found; preserving existing reports')
    return reports

def main():
    reports = collect(Client())  # Fetch everything before changing local files.
    for day, report in reports.items():
        Path(f'weekly_report_{day}.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    print(f'Imported {len(reports)} Confluence weekly reports')

if __name__ == '__main__':
    main()
