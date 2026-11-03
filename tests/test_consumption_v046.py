import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lekarnicka'))
from consumption import apply_consumption

class ConsumptionTests(unittest.TestCase):
    def test_start_full(self):
        self.assertEqual(apply_consumption(None,None,'','30','0','tablety'),(30,30,'tablety'))
    def test_deduct(self):
        self.assertEqual(apply_consumption(30,30,'tablety','30','5','tablety'),(30,25,'tablety'))
    def test_deduct_last(self):
        self.assertEqual(apply_consumption(30,5,'tablety','30','5','tablety'),(30,0,'tablety'))
    def test_no_tracking_remains_off(self):
        self.assertEqual(apply_consumption(None,None,'','','0','tablety'),(None,None,''))
    def test_rejects_bad_inputs(self):
        cases=[(30,5,'tablety','30','6','tablety'),(30,5,'tablety','31','1','tablety'),(30,5,'tablety','30','-1','tablety'),(30,5,'tablety','30','1','kapsle'),(None,None,'','','1','tablety'),(None,None,'','0','0','tablety'),(30,None,'tablety','30','0','tablety'),(30,5,'tablety','30','1.5','tablety')]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError): apply_consumption(*case)
if __name__=='__main__': unittest.main()
