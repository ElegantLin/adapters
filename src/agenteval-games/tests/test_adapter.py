import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import tomllib
import unittest
import urllib.error
import urllib.request
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from agenteval_games.adapter import AgentEvalGamesAdapter, DATA, records
from agenteval_games.runtime.engine import Session, parse_action, reference_actions
from agenteval_games.runtime.server import GameServer, canonical
from agenteval_games.runtime.verification import verify


class EngineTests(unittest.TestCase):
    def test_all_reference_episodes_win_and_cannot_restart(self):
        for task in records():
            config = {"game": task["game"], "index": task["index"]}
            with self.subTest(config=config):
                session = Session(config, DATA)
                for action in reference_actions(config, DATA):
                    result = session.step(action)
                self.assertEqual(result["reward"], 1)
                self.assertTrue(result["done"])
                with self.assertRaises(ValueError):
                    session.step("move down")

    def test_wordle_invalid_guesses_consume_six_attempts_without_reward(self):
        session = Session({"game": "wordle", "index": 0}, DATA)
        for i in range(6):
            response = session.step("INVALID")
            self.assertEqual(response["observation"], "invalid word")
            self.assertEqual(response["reward"], 0)
            self.assertEqual(response["done"], i == 5)
        self.assertTrue(session.done)

    def test_maze_external_cap_is_not_internal_terminal(self):
        session = Session({"game": "maze", "index": 0}, DATA)
        for _ in range(15):
            response = session.step("move up")
        self.assertTrue(response["episode_finished"])
        self.assertFalse(response["done"])
        self.assertEqual(response["reward"], 0)
        self.assertEqual(response["turns_remaining"], 0)

    def test_original_parser_edge_cases(self):
        self.assertEqual(parse_action("Thought: hi\nAction: move down\n"), "move down")
        self.assertEqual(parse_action("move down</s>"), "move dow")
        self.assertEqual(parse_action("Action:move leftAction:move right"), "move left")
        self.assertEqual(parse_action("MOVE UP"), "MOVE UP")


class GeneratorTests(unittest.TestCase):
    def test_all_tasks_reproducible_and_valid(self):
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            a = AgentEvalGamesAdapter(first).run()
            b = AgentEvalGamesAdapter(second).run()
            self.assertEqual(len(a), 50)
            self.assertEqual(
                len(
                    {
                        tomllib.loads((p / "task.toml").read_text())["task"]["name"]
                        for p in a
                    }
                ),
                50,
            )
            for left, right in zip(a, b):
                self.assertEqual(left.name, right.name)
                files = [p.relative_to(left) for p in left.rglob("*") if p.is_file()]
                for file in files:
                    self.assertEqual(
                        (left / file).read_bytes(), (right / file).read_bytes()
                    )
                main = (left / "environment/Dockerfile").read_text()
                self.assertNotIn("COPY data", main)
                self.assertNotIn("COPY config", main)
                self.assertNotIn("COPY runtime", main)
                compose = (left / "environment/docker-compose.yaml").read_text()
                self.assertIn("game-public:/game-public:ro", compose)
                self.assertNotIn("docker.sock", compose)

    def test_selection_validation_and_overwrite(self):
        with tempfile.TemporaryDirectory() as out:
            adapter = AgentEvalGamesAdapter(
                out, task_ids=["lmrlgym_wordle_24", "agenteval-maze-00"]
            )
            self.assertEqual(
                [p.name for p in adapter.run()],
                ["agenteval-maze-00", "agenteval-wordle-24"],
            )
            with self.assertRaises(FileExistsError):
                adapter.run()
            self.assertEqual(
                len(AgentEvalGamesAdapter(out, limit=1, overwrite=True).run()), 1
            )
            with self.assertRaises(ValueError):
                AgentEvalGamesAdapter(out, task_ids=["typo"]).run()
            with self.assertRaises(ValueError):
                AgentEvalGamesAdapter(out, limit=0).run()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {"game": "wordle", "index": 0}
        self.server = GameServer(
            ("127.0.0.1", 0), Session(self.config, DATA), self.temp.name
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.key = (Path(self.temp.name) / "key.pub").read_bytes()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, path, body=None):
        req = urllib.request.Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    def test_signed_authoritative_trace_and_replay(self):
        initial = self.request("/observation")
        self.assertEqual(initial["game"], "wordle")
        self.assertNotIn("index", initial)
        self.assertEqual(self.request("/observation"), initial)
        for action in reference_actions(self.config, DATA):
            self.request("/step", {"action": action})
        envelope = self.request("/transcript")
        self.assertEqual(verify(envelope, self.key, self.config, DATA), 1)
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/step", {"action": "again"})
        self.assertEqual(envelope, self.request("/transcript"))
        tampered = deepcopy(envelope)
        tampered["transcript"]["turns"][0]["action"] = "cheat"
        with self.assertRaises(InvalidSignature):
            verify(tampered, self.key, self.config, DATA)
        forged = deepcopy(envelope)
        forged["signature"] = base64.b64encode(
            Ed25519PrivateKey.generate().sign(canonical(forged["transcript"]))
        ).decode()
        with self.assertRaises(InvalidSignature):
            verify(forged, self.key, self.config, DATA)
        with self.assertRaises(ValueError):
            verify(envelope, self.key, {"game": "wordle", "index": 1}, DATA)

    def test_no_reset_secret_or_transport_cheat(self):
        for path in ("/reset", "/create", "/config", "/filtered_vocab", "/private-key"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path, {"action": "hello"})
            self.assertEqual(error.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/step", {"action": [], "reward": 1})
        envelope = self.request("/transcript")
        self.assertEqual(len(envelope["transcript"]["turns"]), 0)
        self.assertEqual(verify(envelope, self.key, self.config, DATA), 0)
        self.assertNotIn("seed", json.dumps(envelope))


if __name__ == "__main__":
    unittest.main()
