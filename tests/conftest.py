"""Shared test fixtures.

`tiny_model` builds a small ONNX model with the same inputs, outputs and files as
the real one, so the real loading/scoring code is exercised without a download.
It scores a sentence as an insult when it contains the word "trash" or "worthless".
"""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

LABELS = ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]


def _build_tiny_model(d):
    import numpy as np
    import onnx
    from onnx import TensorProto, helper
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

    vocab = {"[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3, "trash": 4, "worthless": 5}
    for i, w in enumerate("you are a the is so this that was really good day nice kill time".split()):
        vocab[w] = 10 + i
    tok = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tok.normalizer = normalizers.Lowercase()
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 2), ("[SEP]", 3)])
    tok.save(str(d / "tokenizer.json"))

    # logits = count(bad tokens) * W + b   (insult and toxic go up; others stay low)
    W = np.array([[8, 0, 0, 0, 10, 0]], dtype=np.float32)
    b = np.array([-4, -6, -6, -6, -5, -6], dtype=np.float32)
    nodes = [
        helper.make_node("Constant", [], ["four"], value=helper.make_tensor("v4", TensorProto.INT64, [], [4])),
        helper.make_node("Constant", [], ["five"], value=helper.make_tensor("v5", TensorProto.INT64, [], [5])),
        helper.make_node("Equal", ["input_ids", "four"], ["is4"]),
        helper.make_node("Equal", ["input_ids", "five"], ["is5"]),
        helper.make_node("Or", ["is4", "is5"], ["bad"]),
        helper.make_node("Cast", ["bad"], ["badf"], to=TensorProto.FLOAT),
        helper.make_node("Cast", ["attention_mask"], ["maskf"], to=TensorProto.FLOAT),
        helper.make_node("Mul", ["badf", "maskf"], ["badm"]),
        helper.make_node("ReduceSum", ["badm", "axes"], ["count"], keepdims=1),
        helper.make_node("MatMul", ["count", "W"], ["xw"]),
        helper.make_node("Add", ["xw", "b"], ["logits"]),
    ]
    graph = helper.make_graph(
        nodes, "tiny",
        [helper.make_tensor_value_info(n, TensorProto.INT64, ["batch", "seq"])
         for n in ("input_ids", "attention_mask", "token_type_ids")],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["batch", 6])],
        initializer=[helper.make_tensor("W", TensorProto.FLOAT, [1, 6], W.flatten()),
                     helper.make_tensor("b", TensorProto.FLOAT, [6], b),
                     helper.make_tensor("axes", TensorProto.INT64, [1], [1])])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(d / "model_optimized_quantized.onnx"))
    (d / "config.json").write_text(json.dumps({
        "id2label": {str(i): lab for i, lab in enumerate(LABELS)},
        "problem_type": "multi_label_classification"}))


def spec_for(d):
    """A model spec (like ml.MODEL) whose fingerprints match the files in d."""
    files = {}
    for name in ("model_optimized_quantized.onnx", "tokenizer.json", "config.json"):
        data = (d / name).read_bytes()
        files[name] = (len(data), "sha256", hashlib.sha256(data).hexdigest())
    return {"name": "tiny", "repo": "test/tiny", "revision": "0" * 40, "files": files,
            "onnx": "model_optimized_quantized.onnx", "max_tokens": 64}


@pytest.fixture(scope="session")
def tiny_model(tmp_path_factory):
    d = tmp_path_factory.mktemp("tiny_model")
    _build_tiny_model(d)
    return d


@pytest.fixture(scope="session")
def tiny_scorer(tiny_model):
    from cleanly.ml import Scorer
    return Scorer(tiny_model, spec_for(tiny_model))


class FakeAI:
    """A local HTTP server that speaks the Ollama, Anthropic and OpenAI APIs.

    `answer` is a function(request_json) -> the JSON text the "model" replies with.
    Every request is kept in `requests` so tests can inspect what was sent.
    """

    def __init__(self):
        self.requests = []
        self.answer = lambda req: '{"decisions": [], "missed": []}'
        self.status = 200
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"models": [{"name": "llama3.2:3b"}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "headers": dict(self.headers), "body": req})
                text = fake.answer(req)
                if self.path == "/api/chat":
                    out = {"message": {"role": "assistant", "content": text}}
                elif self.path == "/v1/messages":
                    out = {"content": [{"type": "text", "text": text}]}
                else:
                    out = {"choices": [{"message": {"content": text}}]}
                body = json.dumps(out).encode()
                self.send_response(fake.status)
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def last_user_message(self):
        body = self.requests[-1]["body"]
        return body["messages"][-1]["content"]


@pytest.fixture
def fake_ai():
    f = FakeAI()
    yield f
    f.server.shutdown()
