import unittest
from urllib.parse import parse_qs, urlsplit

from ad_inputs import ACTORS, search_plan


class InputTests(unittest.TestCase):
    def test_meta_keywords_become_separate_search_urls(self):
        plan = search_plan({"platform": "facebook", "queries": "Cheap Insurance\nLower your rate"})
        self.assertEqual(plan["actor"], "JJghSZmShuco4j9gJ")
        self.assertEqual(len(plan["runs"]), 1)
        actor_input = plan["runs"][0]["input"]
        self.assertEqual(actor_input["resultsLimit"], 10)
        self.assertEqual(len(actor_input["startUrls"]), 2)
        query = parse_qs(urlsplit(actor_input["startUrls"][0]["url"]).query)
        self.assertEqual(query["q"], ["Cheap Insurance"])
        self.assertEqual(query["country"], ["US"])
        self.assertEqual(query["publisher_platforms[0]"], ["facebook"])
        self.assertFalse(actor_input["enrichWithEcommerceData"])

    def test_youtube_uses_one_run_per_keyword(self):
        plan = search_plan({"platform": "youtube", "queries": "Auto Insurance\nLower your rate", "region": "", "limit": 20})
        self.assertEqual(plan["actor"], "iRsL8PTQjmWC1SaPQ")
        self.assertEqual(plan["maximumResults"], 40)
        self.assertEqual([run["input"]["searchQuery"] for run in plan["runs"]], ["Auto Insurance", "Lower your rate"])
        for run in plan["runs"]:
            self.assertEqual(run["input"]["platform"], "youtube")
            self.assertEqual(run["input"]["maxResults"], 20)

    def test_advertisers_and_duplicates(self):
        url = "https://www.facebook.com/example"
        plan = search_plan({"platform": "facebook", "queries": url + "\n" + url, "searchBy": "advertiser"})
        self.assertEqual(plan["queryCount"], 1)
        self.assertEqual(plan["runs"][0]["input"]["startUrls"], [{"url": url}])
        google = search_plan({"platform": "youtube", "queries": "insurance.example", "searchBy": "advertiser"})
        self.assertEqual(google["runs"][0]["input"]["searchQuery"], "insurance.example")

    def test_unsupported_or_unbounded_inputs_rejected(self):
        for overrides in ({"mode": "organic"}, {"limit": 0}, {"limit": True}, {"limit": 101},
                          {"queries": ""}, {"queries": "\n".join(str(n) for n in range(11))},
                          {"region": "unsupported"}, {"searchBy": "invalid"},
                          {"searchBy": "advertiser", "queries": "https://other.example/page"}):
            with self.assertRaises(ValueError):
                search_plan({"platform": "facebook", "queries": "Insurance", **overrides})


if __name__ == "__main__":
    unittest.main()
