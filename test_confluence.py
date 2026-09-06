import unittest
from collect_confluence import collect, report_date
from weekly_reports import contents

class ConfluenceTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(report_date('주간업무 2026. 09. 04'), '2026-09-04')
        self.assertIsNone(report_date('2026'))

    def test_descendants_only(self):
        class Fake:
            def pages(self, path):
                if 'descendants' in path:
                    return [{'id':'1','type':'folder','title':'2026'}, {'id':'2','type':'page','title':'주간업무 2026. 09. 04'}]
                return []
            def get(self, path):
                return {'id':'2','title':'주간업무 2026. 09. 04','body':{'storage':{'value':'<p>Report</p>'}}}
        self.assertEqual(list(collect(Fake())), ['2026-09-04'])

    def test_html_safety_and_structure(self):
        rendered = contents({'storage':'<table><tr><td onclick="bad()">Text</td></tr></table><img src=x onerror=bad()>'})
        self.assertIn('<td>Text</td>', rendered)
        self.assertNotIn('onclick', rendered)
        self.assertNotIn('<img', rendered)

    def test_only_latest_two_bodies_are_fetched(self):
        class Fake:
            fetched = []
            def pages(self, path):
                if 'descendants' in path:
                    return [dict(id=str(d), type='page', title=f'주간업무 2026. 09. {d:02}') for d in (4, 18, 11)]
                return []
            def get(self, path):
                self.fetched.append(path)
                return dict(id='1', title='report', body={'storage': {'value': '<p>Report</p>'}})
        client = Fake()
        self.assertEqual(list(collect(client)), ['2026-09-18', '2026-09-11'])
        self.assertEqual(len(client.fetched), 2)
        self.assertFalse(any('/pages/4?' in p for p in client.fetched))

if __name__ == '__main__':
    unittest.main()
