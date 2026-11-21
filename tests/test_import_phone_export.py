import json, sqlite3, tempfile, unittest, zipfile
from pathlib import Path
from import_phone_export import import_export
import app

class ImportTests(unittest.TestCase):
 def test_order_lifts_labels_and_idempotency(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); z=root/'export.zip'; db=root/'db.sqlite'
   doc={'samples':[{'id':'a','kind':'strokes','width':100,'height':100,'label':'ab','created_at':'2026-01-01T00:00:00Z','strokes':[{'points':[{'x':2,'y':3,'t':0},{'x':4,'y':5,'t':9}]},{'points':[{'x':8,'y':9,'t':0}]}]}, {'id':'p','kind':'photo','label':'not motion','strokes':[]}]}
   with zipfile.ZipFile(z,'w') as f: f.writestr('dataset.json',json.dumps(doc))
   self.assertEqual(import_export(z,db),{'inserted':1,'already_imported':0,'skipped_non_motion':1})
   self.assertEqual(import_export(z,db),{'inserted':0,'already_imported':1,'skipped_non_motion':1})
   c=sqlite3.connect(db); row=c.execute('select text,strokes_json from samples').fetchone(); c.close()
   self.assertEqual(row[0],'ab'); self.assertEqual(json.loads(row[1]),[[{'x':2,'y':3,'t':0,'pressure':.5},{'x':4,'y':5,'t':9,'pressure':.5}],[{'x':8,'y':9,'t':0,'pressure':.5}]])
   library=app.Store(db).all(); result=app.compose({'text':'ab','seed':1},library); self.assertEqual(result['stroke_count'],2); self.assertEqual(result['missing'],[])
if __name__=='__main__': unittest.main()
