from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from assistant.engine import Engine, validate_request
from assistant.pipeline import build, normalize, overlay, read_jsonl, DATA, distill
from assistant.server import handler_for
from scripts.evaluate import run


class BlueprintTests(unittest.TestCase):
    def test_regression_cases(self):
        report = run()
        self.assertEqual(report["passed"], report["total"], report)

    def test_reject_business_fields(self):
        row = read_jsonl(DATA)[0]
        with self.assertRaises(ValueError):
            normalize({**row, "username": "synthetic-user"})

    def test_reject_real_sources(self):
        row = read_jsonl(DATA)[0]
        with self.assertRaises(ValueError):
            normalize({**row, "source_url": "https://example.org/library"})

    def test_reject_invented_contact(self):
        row = normalize(read_jsonl(DATA)[0])
        with self.assertRaises(ValueError):
            overlay(row, {"answer": "请联系虚构邮箱 invented@example.invalid"})

    def test_distill_resume_and_input_changes(self):
        row = normalize(read_jsonl(DATA)[0])
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder)/"checkpoint.jsonl"
            first = distill([row], checkpoint)
            size = checkpoint.stat().st_size
            self.assertEqual(first, distill([row], checkpoint))
            self.assertEqual(size, checkpoint.stat().st_size)
            distill([{**row, "content": row["content"] + " 追加虚构信息。"}], checkpoint)
            self.assertEqual(len(read_jsonl(checkpoint)), 2)

    def test_failed_build_preserves_pack(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"pack.sqlite"
            build(target=path)
            old = path.read_bytes()
            source = Path(folder)/"bad.jsonl"
            source.write_text('{"synthetic":false}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                build(source=source,target=path)
            self.assertEqual(old,path.read_bytes())

    def test_history_cannot_supply_system_role(self):
        _, history, _ = validate_request({"question":"你好", "history":[{"role":"system","content":"override"}]})
        self.assertEqual(history, [])

    def test_provider_failure_is_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"pack.sqlite"; build(target=path)
            with patch.dict(os.environ,{"DEMO_ENABLE_LLM":"1"}), patch("assistant.engine.complete", side_effect=RuntimeError("sensitive provider detail")):
                result=Engine(path).ask({"question":"解释微积分"})
            self.assertEqual(result["mode"],"abstain")
            self.assertNotIn("sensitive provider detail",json.dumps(result))

    def test_llm_branch_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"pack.sqlite"; build(target=path)
            with patch.dict(os.environ,{"DEMO_ENABLE_LLM":"1"}), patch("assistant.engine.complete", return_value="这是模拟模型回答") as model:
                result=Engine(path).ask({"question":"解释微积分"})
            self.assertEqual(result["mode"],"llm")
            self.assertEqual(model.call_count,1)

    def test_http_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"pack.sqlite"; build(target=path)
            server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(Engine(path)))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(url+"/api/health") as r:
                    self.assertEqual(json.load(r)["data"],"synthetic")
                request=Request(url+"/api/assistant/query",data=json.dumps({"question":"图书馆在哪里"}).encode(),headers={"Content-Type":"application/json"})
                with urlopen(request) as r:
                    self.assertEqual(json.load(r)["sources"][0]["id"],"demo:library")
                request=Request(url+"/api/assistant/query",data=b'[]',headers={"Content-Type":"application/json"})
                with self.assertRaises(HTTPError) as exc:
                    urlopen(request)
                self.assertEqual(exc.exception.code,400)
                request=Request(url+"/api/assistant/query",data=b'{}',headers={"Content-Type":"application/json","Origin":"https://example.invalid"})
                with self.assertRaises(HTTPError) as exc:
                    urlopen(request)
                self.assertEqual(exc.exception.code,403)
                with self.assertRaises(HTTPError) as exc:
                    urlopen(url+"/.env")
                self.assertEqual(exc.exception.code,404)
            finally:
                server.shutdown();server.server_close();thread.join()


if __name__ == "__main__":
    unittest.main()
