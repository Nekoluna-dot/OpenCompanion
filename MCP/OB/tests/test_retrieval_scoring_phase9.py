def _bucket(bucket_id: str, **metadata):
    base = {"type": "dynamic", "importance": 5}
    base.update(metadata)
    return {"id": bucket_id, "content": f"memory {bucket_id}", "metadata": base}


def test_retrieval_candidate_score_is_weighted_sum():
    from ombrebrain.retrieval.scoring import (
        PolicyGatedRetrievalScorer,
        RetrievalFeatures,
        RetrievalWeights,
    )

    scorer = PolicyGatedRetrievalScorer(
        weights=RetrievalWeights(
            semantic=2.0,
            lexical=1.0,
            temporal=0.5,
            affective=0.25,
            unresolved=3.0,
            promise=4.0,
            graph_neighbor=5.0,
        )
    )

    score = scorer.score_bucket(
        _bucket("weighted"),
        RetrievalFeatures(
            semantic_similarity=0.5,
            lexical_similarity=0.25,
            temporal_proximity=0.2,
            affective_proximity=0.4,
            unresolved_relevance=0.1,
            promise_relevance=0.05,
            graph_neighbor_relevance=0.02,
        ),
        mode="search",
    )

    assert score.candidate_score == 2.05
    assert score.surface_score == 2.05


def test_retrieval_surface_score_applies_all_philosophy_gates():
    from ombrebrain.retrieval.scoring import (
        PolicyGatedRetrievalScorer,
        RetrievalFeatures,
        RetrievalGates,
        RetrievalWeights,
    )

    scorer = PolicyGatedRetrievalScorer(weights=RetrievalWeights(semantic=10.0))

    score = scorer.score_bucket(
        _bucket("gated"),
        RetrievalFeatures(semantic_similarity=0.8),
        gates=RetrievalGates(
            accessibility=0.5,
            dignity=0.5,
            scarcity=0.5,
            intent=0.5,
            non_cognition=0.5,
        ),
        mode="search",
    )

    assert score.candidate_score == 8.0
    assert score.surface_score == 0.25
    assert score.gates.to_dict() == {
        "accessibility": 0.5,
        "dignity_gate": 0.5,
        "scarcity_gate": 0.5,
        "intent_gate": 0.5,
        "non_cognition_gate": 0.5,
    }


def test_high_candidate_score_cannot_bypass_zero_policy_gate():
    from ombrebrain.retrieval.scoring import (
        PolicyGatedRetrievalScorer,
        RetrievalFeatures,
        RetrievalWeights,
    )

    scorer = PolicyGatedRetrievalScorer(weights=RetrievalWeights(semantic=100.0))

    score = scorer.score_bucket(
        _bucket("hidden", dont_surface=True),
        RetrievalFeatures(semantic_similarity=1.0),
        mode="spontaneous",
    )

    assert score.policy_allowed is False
    assert score.candidate_score == 100.0
    assert score.gates.accessibility == 0.0
    assert score.surface_score == 0.0
    assert "dont_surface" in score.policy_reasons


def test_dont_surface_is_available_to_explicit_search_mode():
    from ombrebrain.retrieval.scoring import PolicyGatedRetrievalScorer, RetrievalFeatures

    score = PolicyGatedRetrievalScorer.default().score_bucket(
        _bucket("hidden", dont_surface=True),
        RetrievalFeatures(semantic_similarity=1.0),
        mode="search",
    )

    assert score.policy_allowed is True
    assert score.gates.accessibility == 1.0
    assert score.surface_score > 0


def test_retrieval_rank_uses_surface_score_not_raw_candidate_score():
    from ombrebrain.retrieval.scoring import (
        PolicyGatedRetrievalScorer,
        RetrievalCandidate,
        RetrievalFeatures,
        RetrievalWeights,
    )

    scorer = PolicyGatedRetrievalScorer(weights=RetrievalWeights(semantic=100.0))
    candidates = [
        RetrievalCandidate(
            bucket=_bucket("hidden", dont_surface=True),
            features=RetrievalFeatures(semantic_similarity=1.0),
        ),
        RetrievalCandidate(
            bucket=_bucket("visible"),
            features=RetrievalFeatures(semantic_similarity=0.2),
        ),
    ]

    ranked = scorer.rank(candidates, mode="spontaneous")

    assert [item.bucket_id for item in ranked] == ["visible", "hidden"]
    assert ranked[0].surface_score > ranked[1].surface_score
    assert ranked[1].candidate_score > ranked[0].candidate_score


def test_retrieval_score_is_json_safe_and_preserves_policy_decision():
    from ombrebrain.retrieval.scoring import PolicyGatedRetrievalScorer, RetrievalFeatures

    data = PolicyGatedRetrievalScorer.default().score_bucket(
        _bucket("archived", type="archived"),
        RetrievalFeatures(lexical_similarity=1.0),
        mode="search",
    ).to_dict()

    assert data["bucket_id"] == "archived"
    assert data["policy_allowed"] is False
    assert data["surface_score"] == 0.0
    assert data["policy_reasons"] == ["archived"]


def test_retrieval_package_exports_policy_gated_scorer():
    from ombrebrain.retrieval import PolicyGatedRetrievalScorer, RetrievalFeatures

    assert PolicyGatedRetrievalScorer.default() is not None
    assert RetrievalFeatures() is not None
