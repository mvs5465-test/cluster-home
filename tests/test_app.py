import unittest

from app import create_app, load_config


class HomeAppTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SITE_CONFIG": {
                    "title": "Test Home",
                    "subtitle": "Testing dashboard",
                    "groups": [
                        {
                            "name": "Infra",
                            "items": [
                                {
                                    "name": "Grafana",
                                    "icon": "GF",
                                    "url": "http://grafana.test",
                                    "description": "Dashboards"
                                }
                            ]
                        }
                    ]
                },
            }
        )
        self.client = self.app.test_client()

    def test_home_page_renders_cards(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Home", response.data)
        self.assertIn(b"Grafana", response.data)
        self.assertIn(b"GF", response.data)
        self.assertIn(b"http://grafana.test", response.data)

    def test_health_endpoint_reports_counts(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")
        self.assertEqual(response.json["groups"], 1)
        self.assertEqual(response.json["links"], 1)

    def test_load_config_falls_back_to_default(self):
        config = load_config("/tmp/cluster-home-missing-config.json")
        self.assertEqual(config["title"], "Cluster Home")


if __name__ == "__main__":
    unittest.main()
