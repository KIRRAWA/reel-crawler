import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import feed_collector as f


def visual(**changes):
    return dict(political='no',sensitive='no',meaningful_text_language='english',us_audience_context='suitable',category='comedy',confidence=.95,reason='ordinary joke',**{}) | changes

class FeedTests(unittest.TestCase):
    def test_language_and_content_gates(self):
        self.assertEqual(f.decide({'status':'english'},[visual()])[0],'screened_candidate')
        for status in ['uncertain','no_speech_detected']:
            self.assertEqual(f.decide({'status':status},[visual()])[0],'review')
        self.assertEqual(f.decide({'status':'non_english'},[visual()]),('excluded','non_english_audio'))
        self.assertEqual(f.decide({'status':'english'},[visual(),visual(political='yes')])[0],'excluded')
        self.assertEqual(f.decide({'status':'english'},[visual(sensitive='yes')])[0],'excluded')
        self.assertEqual(f.decide({'status':'english'},[visual(meaningful_text_language='mixed')])[0],'excluded')
        self.assertEqual(f.decide({'status':'english'},[visual(confidence=.6)])[0],'review')
        self.assertEqual(f.decide({'status':'no_audio_stream'},[visual(meaningful_text_language='none')])[0],'screened_candidate')
        self.assertEqual(f.decide({'status':'english'},[])[0],'review')

    def test_invalid_model_output(self):
        for v in [visual(confidence=float('nan')),visual(political='maybe'),{}]:
            with self.assertRaises(ValueError): f.validate_visual(v)

    def test_feed_parser(self):
        payload={'items':[{'media':{'code':'AB12','product_type':'clips','media_type':2,'user':{'username':'test'},'caption':{'text':'Hello'}}},{'code':'POST','media_type':2}]}
        items=f.parse_media(payload)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['url'],'https://www.instagram.com/reel/AB12/')
        self.assertEqual(items[0]['username'],'test')

    def test_storage_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            s=f.Store(d)
            item={'url':'https://www.instagram.com/reel/A/','caption':'=danger'}
            self.assertTrue(s.add(item,'r'))
            self.assertFalse(s.add(item,'r'))
            s.result(item['url'],'screened_candidate','ok','comedy',20,{'status':'english','transcript':'hello'},[visual()],1)
            result=s.export()
            self.assertEqual(result['screened_candidates'],1)
            self.assertEqual(result['categories'][0]['percent_of_candidates'],100)
            self.assertIn("'=danger",(Path(d)/'candidates.csv').read_text(encoding='utf-8-sig'))
            self.assertTrue((Path(d)/'analysis.html').is_file())
            s.db.close()

    def test_end_to_end_screen_success_and_failure(self):
        from types import SimpleNamespace
        args=SimpleNamespace(max_seconds=120,vision_model='test')
        item={'url':'https://www.instagram.com/reel/A/','caption':'hello'}
        with tempfile.TemporaryDirectory() as d:
            s=f.Store(d);s.add(item,'r')
            with patch.object(f,'fetch_video',return_value=Path('dummy')),patch.object(f,'sample_frames',return_value=([Path('frame')],10)),patch.object(f,'analyze_audio',return_value={'status':'english','transcript':'Hello'}),patch.object(f,'vision_review',return_value=[visual()]):
                f.screen_item(item,None,None,args,s)
            self.assertEqual(s.export()['screened_candidates'],1)
            with patch.object(f,'fetch_video',side_effect=RuntimeError):
                f.screen_item(item,None,None,args,s)
            self.assertEqual(s.export()['needs_review'],1)
            self.assertEqual(s.export()['screened_candidates'],0)
            s.db.close()

    def test_main_run_and_export(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            with patch.object(sys,'argv',['feed_collector.py','--collect-only','--output',d]),patch.object(f,'run'):
                with self.assertRaises(SystemExit) as ex:f.main()
            self.assertEqual(ex.exception.code,0)
            self.assertTrue((Path(d)/'runs.csv').is_file())
            s=f.Store(d)
            self.assertEqual(s.db.execute('SELECT status FROM feed_runs').fetchone()[0],'finished')
            s.db.close()

if __name__=='__main__':unittest.main()
