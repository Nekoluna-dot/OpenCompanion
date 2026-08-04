import pytest

from retrieval_eval import evaluate_cases, normalize_cases


def test_normalize_cases_accepts_wrapped_payload_and_domain_string():
    cases = normalize_cases({
        "cases": [{
            "name": "work",
            "query": "release lane",
            "expected_ids": "bucket-a",
            "domain": "work, deployment",
        }]
    })

    assert cases == [{
        "name": "work",
        "query": "release lane",
        "expected_ids": ["bucket-a"],
        "domain_filter": ["work", "deployment"],
    }]


@pytest.mark.parametrize("payload", [None, {}, [], [{"query": ""}], [{"query": "x"}]])
def test_normalize_cases_rejects_incomplete_payload(payload):
    with pytest.raises(ValueError):
        normalize_cases(payload)


@pytest.mark.asyncio
async def test_evaluate_cases_calculates_hit_recall_and_mrr():
    class Manager:
        async def search(self, query, **kwargs):
            assert kwargs["vector_scores"] == {}
            if query == "first":
                return [{"id": "noise"}, {"id": "wanted-a"}]
            return [{"id": "wanted-b"}, {"id": "wanted-c"}]

    cases = normalize_cases([
        {"name": "rank two", "query": "first", "expected_ids": ["wanted-a"]},
        {"name": "two expected", "query": "second", "expected_ids": ["wanted-b", "missing"]},
    ])
    report = await evaluate_cases(Manager(), cases, top_k=2)

    assert report["hit_rate"] == 1.0
    assert report["mean_recall"] == 0.75
    assert report["mrr"] == 0.75
    assert report["cases"][0]["first_relevant_rank"] == 2
