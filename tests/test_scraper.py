import unittest
from unittest.mock import patch

from scraper import ApifyClient


class ApifyTests(unittest.TestCase):
    def test_run_waits_for_success(self):
        client = ApifyClient("test")
        with patch.object(client, "request", side_effect=[
            {"data": {"id": "r1", "status": "RUNNING"}},
            {"data": {"id": "r1", "status": "SUCCEEDED", "defaultDatasetId": "d1"}},
        ]) as request, patch("scraper.time.sleep"):
            run = client.run("owner/actor", {"query": "ads"}, 60)
        self.assertEqual(run["defaultDatasetId"], "d1")
        self.assertEqual(request.call_args_list[0].args,
                         ("acts/owner~actor/runs", {"query": "ads"}))

    def test_failed_run_is_not_exported(self):
        client = ApifyClient("test")
        with patch.object(client, "request", return_value={
            "data": {"id": "r1", "status": "FAILED"}
        }):
            with self.assertRaisesRegex(RuntimeError, "FAILED"):
                client.run("actor", {}, 60)

    def test_dataset_reads_all_pages(self):
        client = ApifyClient("test")
        with patch.object(client, "request", side_effect=[[{"id": 1}], [{"id": 2}], []]) as request:
            self.assertEqual(client.items("d1"), [{"id": 1}, {"id": 2}])
        self.assertIn("offset=1", request.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
