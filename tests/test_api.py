"""API tests. Run with pytest or: python3 -m unittest discover -s tests

Skipped automatically when fastapi/httpx are not installed (engine-only
environment); they always run inside the Docker image / dev venv.
"""
import unittest

try:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
except ModuleNotFoundError:  # pragma: no cover - engine-only environment
    client = None


def payload(measures, **extra):
    body = {"measures": measures}
    body.update(extra)
    return body


@unittest.skipIf(client is None, "fastapi is not installed")
class TestApi(unittest.TestCase):
    def test_health(self):
        r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_expand_simple_repeat(self):
        r = client.post("/expand", json=payload([
            {"number": 1},
            {"number": 2, "markers": ["repeat_begin"]},
            {"number": 3, "markers": ["repeat_end"]},
            {"number": 4},
        ]))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total_steps"], 6)
        self.assertEqual([s["measure"] for s in data["steps"]], [1, 2, 3, 2, 3, 4])
        self.assertEqual([s["step"] for s in data["steps"]], [1, 2, 3, 4, 5, 6])

    def test_expand_endings_and_ds_al_coda(self):
        r = client.post("/expand", json=payload([
            {"number": 1},
            {"number": 2, "markers": ["repeat_begin", "segno"]},
            {"number": 3, "markers": ["ending_begin"], "ending_numbers": [1]},
            {"number": 4, "markers": ["ending_end", "repeat_end"]},
            {"number": 5, "markers": ["ending_begin"], "ending_numbers": [2]},
            {"number": 6, "markers": ["ending_end", "to_coda"]},
            {"number": 7, "markers": ["ds_al_coda"]},
            {"number": 8, "markers": ["coda_sign"]},
            {"number": 9},
        ]))
        self.assertEqual(r.status_code, 200)
        seq = [s["measure"] for s in r.json()["steps"]]
        # 1,2,3,4 (1st ending) -> 2,5,6 (2nd ending) -> D.S. to 2 -> 5,6 to_coda -> 8,9
        self.assertEqual(seq, [1, 2, 3, 4, 2, 5, 6, 7, 2, 5, 6, 8, 9])

    def test_expand_unclosed_repeat_returns_located_error_and_no_steps(self):
        r = client.post("/expand", json=payload([
            {"number": 1},
            {"number": 2, "markers": ["repeat_begin"]},
            {"number": 3},
        ]))
        self.assertEqual(r.status_code, 422)
        body = r.json()
        self.assertNotIn("steps", body)
        self.assertEqual(body["errors"][0]["code"], "UNCLOSED_REPEAT")
        self.assertEqual(body["errors"][0]["measure"], 2)

    def test_expand_illegal_jump(self):
        r = client.post("/expand", json=payload([
            {"number": 1, "markers": ["ds_al_fine"]},
            {"number": 2, "markers": ["segno"]},
            {"number": 3, "markers": ["fine"]},
        ]))
        self.assertEqual(r.status_code, 422)
        codes = {e["code"] for e in r.json()["errors"]}
        self.assertIn("ILLEGAL_JUMP", codes)

    def test_expand_max_steps_exceeded_no_partial_sequence(self):
        r = client.post("/expand", json=payload(
            [
                {"number": 1, "markers": ["repeat_begin"]},
                {"number": 2, "markers": ["repeat_end"], "repeat_times": 64},
            ],
            max_steps=10,
        ))
        self.assertEqual(r.status_code, 422)
        body = r.json()
        self.assertNotIn("steps", body)
        self.assertEqual(body["errors"][0]["code"], "MAX_STEPS_EXCEEDED")
        self.assertIsNotNone(body["errors"][0]["measure"])

    def test_validate_ok(self):
        r = client.post("/validate", json=payload([
            {"number": 1},
            {"number": 2, "markers": ["repeat_begin"]},
            {"number": 3, "markers": ["ending_begin"], "ending_numbers": [1]},
            {"number": 4, "markers": ["ending_end", "repeat_end"]},
            {"number": 5, "markers": ["ending_begin"], "ending_numbers": [2]},
            {"number": 6, "markers": ["ending_end"]},
        ]))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["errors"], [])

    def test_validate_reports_all_errors(self):
        r = client.post("/validate", json=payload([
            {"number": 1, "markers": ["repeat_begin"]},
            {"number": 1},
            {"number": 2, "markers": ["ds_al_fine"]},
        ]))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["valid"])
        codes = {e["code"] for e in data["errors"]}
        self.assertTrue({"DUPLICATE_MEASURE", "UNCLOSED_REPEAT", "DS_WITHOUT_SEGNO"} <= codes)

    def test_unknown_marker_rejected(self):
        r = client.post("/expand", json=payload([
            {"number": 1, "markers": ["bogus"]},
        ]))
        self.assertEqual(r.status_code, 422)

    def test_empty_measures_rejected(self):
        r = client.post("/expand", json={"measures": []})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
