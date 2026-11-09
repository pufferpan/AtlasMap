import unittest
from core.system_usage import ue_import_memory,ue_import_capacity

GB=1024**3

class ImportMemoryTests(unittest.TestCase):
    def test_large_texture_shards_use_one_editor_on_16gb_machine(self):
        # Compressed 1024px PNGs can expand to ~16GB in one native worker.
        cost=ue_import_memory({'images':[{'size':[1024,1024]}]*1000},200*1024**2)
        self.assertGreater(cost,16*GB)
        snapshot=dict(memory_total=16*GB,memory_available=11*GB,commit_available=28*GB)
        self.assertEqual(ue_import_capacity(6,[cost]*6,snapshot),1)

    def test_roomy_machine_keeps_multiple_independent_editors(self):
        snapshot=dict(memory_total=64*GB,memory_available=56*GB,commit_available=90*GB)
        self.assertEqual(ue_import_capacity(6,[16*GB]*6,snapshot),3)
        self.assertEqual(ue_import_capacity(2,[16*GB]*6,snapshot),2)

    def test_commit_limit_and_largest_shard_bound_parallelism(self):
        snapshot=dict(memory_total=64*GB,memory_available=56*GB,commit_available=22*GB)
        self.assertEqual(ue_import_capacity(6,[16*GB,10*GB,4*GB,4*GB],snapshot),1)
        snapshot['commit_available']=40*GB
        self.assertEqual(ue_import_capacity(6,[16*GB,10*GB,4*GB,4*GB],snapshot),4)

    def test_missing_counters_still_allow_a_single_worker(self):
        self.assertEqual(ue_import_capacity(6,[16*GB]*6,{}),1)
