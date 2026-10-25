"""Metric computation tests — pure logic, no LLM, no DB."""

from trust_rag.eval.harness import GoldenItem, ItemResult, compute_metrics, load_dataset


def _item(id_: str, category: str, keywords: list[str] | None = None, doc: str | None = None):
    return GoldenItem(
        id=id_, category=category, question=f"q{id_}",
        expected_keywords=keywords or [], expected_doc=doc,
    )


def _result(item: GoldenItem, docs: list[str], answer: str = "", conf: float = 0.0,
            abstain: bool = False) -> ItemResult:
    return ItemResult(item=item, retrieved_docs=docs, answer=answer,
                      confidence=conf, abstain=abstain)


class TestComputeMetrics:
    def test_perfect_run(self) -> None:
        a = _item("q1", "answerable", ["five"], "handbook.md")
        u = _item("q2", "unanswerable")
        results = [
            _result(a, ["handbook.md"], answer="You may carry five days [1].", conf=0.9),
            _result(u, ["handbook.md"], answer="cannot answer", abstain=True),
        ]
        m = compute_metrics(results)
        assert m["retrieval_hit_rate"] == 1.0
        assert m["answer_success_rate"] == 1.0
        assert m["abstention_accuracy"] == 1.0

    def test_failed_retrieval_misses_hit_rate(self) -> None:
        a = _item("q1", "answerable", ["five"], "handbook.md")
        results = [_result(a, ["benefits.md"], answer="five days", conf=0.9)]
        m = compute_metrics(results)
        assert m["retrieval_hit_rate"] == 0.0
        # answer still contained the keyword, so answer_success is 1.0
        assert m["answer_success_rate"] == 1.0

    def test_abstained_answerable_counts_as_failure(self) -> None:
        a = _item("q1", "answerable", ["five"], "handbook.md")
        results = [_result(a, ["handbook.md"], abstain=True)]
        assert compute_metrics(results)["answer_success_rate"] == 0.0

    def test_unanswerable_answered_lowers_abstention(self) -> None:
        u = _item("q2", "unanswerable")
        results = [_result(u, [], answer="42 vesting months [1]", conf=0.9)]
        assert compute_metrics(results)["abstention_accuracy"] == 0.0

    def test_temporal_accuracy(self) -> None:
        t_hit = _item("t1", "temporal", ["five"], "handbook.md")
        t_miss = _item("t2", "temporal", ["five"], "handbook.md")
        results = [
            _result(t_hit, ["handbook.md"], answer="five days then [1]"),
            _result(t_miss, ["handbook.md"], answer="zero days [1]"),
        ]
        m = compute_metrics(results)
        assert m["temporal_accuracy"] == 0.5

    def test_mean_confidence(self) -> None:
        items = [_item(f"q{i}", "answerable", ["x"], "d.md") for i in range(4)]
        results = [
            _result(items[0], ["d.md"], conf=1.0), _result(items[1], ["d.md"], conf=0.5),
            _result(items[2], ["d.md"], conf=0.0), _result(items[3], ["d.md"], conf=0.5),
        ]
        assert compute_metrics(results)["mean_confidence"] == 0.5


class TestDataset:
    def test_golden_dataset_loads(self) -> None:
        items = load_dataset()
        assert len(items) >= 16
        answerable = [i for i in items if i.category == "answerable"]
        unanswerable = [i for i in items if i.category == "unanswerable"]
        temporal = [i for i in items if i.category == "temporal"]
        assert len(answerable) >= 8 and len(unanswerable) >= 3
        assert len(temporal) >= 4
        # every temporal item must anchor to a moment or ask about current state
        assert all(i.as_of in (None, "mid") for i in temporal)
        # every answerable item must have keywords + expected doc
        assert all(i.expected_keywords and i.expected_doc for i in answerable)
        assert all(not i.expected_doc for i in unanswerable)
        # ids unique
        assert len({i.id for i in items}) == len(items)
