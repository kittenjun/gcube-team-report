import unittest
from datetime import datetime, timezone
from report_view import prepare, render, topics

class ReportTests(unittest.TestCase):
    def data(self):
        return {'a':['담당'], 's':['Done','Blocked','In Progress'], 't':['Task'], 'rows':[
            [1,0,0,0,'2026-01-01','2026-01-10','old','',0,None,0,0,9,'2026-09-04'],
            [2,0,1,0,'2026-01-01',None,'blocked','',0,2,0,0,None,'2026-09-04'],
            [3,0,2,0,'2026-01-01',None,'stale','description',0,90,0,0,None,'2026-06-01']]}
    def test_old_done_not_monthly_completion(self):
        d=prepare(self.data(),datetime(2026,9,5,tzinfo=timezone.utc))
        self.assertTrue(d['entries'][0]['recent'])
        self.assertFalse(d['entries'][0]['completed'])
        self.assertTrue(d['entries'][1]['flags'][0].startswith('차단'))
        self.assertFalse(d['entries'][2]['recent'])
        self.assertIn('30일 미갱신 · 현재 진행 여부 확인',d['entries'][2]['flags'])
    def test_cross_channel_topics(self):
        self.assertEqual(['GCUBE 플랫폼','PC방 솔루션'],topics(' GCUBE ; pcbang ; unrelated'))
        self.assertEqual(['기타'],topics('gcube-other'))
        self.assertEqual(['강의 솔루션','테스트 TOOLS'],topics('edu;test'))
        self.assertEqual(['기타'],topics(''))

    def test_status_groups(self):
        from report_view import status_group
        self.assertEqual('새로열림',status_group('Ready'))
        self.assertEqual('진행',status_group('Blocked'))
        self.assertEqual('리뷰',status_group('In Review'))
        self.assertEqual('완료',status_group('Done'))
    def test_embedded_data_cannot_close_script(self):
        d=self.data();d['rows'][0][7]='</script><script>alert(1)</script>'
        self.assertNotIn('</script><script>alert(1)',render(d))

if __name__=='__main__':unittest.main()
