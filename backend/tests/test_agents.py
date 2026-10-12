"""Agents: the Scout's learning / scoring and the Profiler's validation of the model's answer (no model needed)."""

from types import SimpleNamespace

from app.services.agents import profiler, scout


def company(industry, city="Beirut", status="new", brief=None, employees=None, website="https://x.com"):
    return SimpleNamespace(industry=industry, headquarters_city=city, status=status, brief=brief,
                           employee_count_estimate=employees, website=website, primary_phone=None)


def test_scout_waits_for_enough_outcomes():
    few = [(scout.features(company("Education")), True)] * 3 + [(scout.features(company("Retail")), False)] * 9
    assert scout.learn(few) is None  # 3 leads < scout_min_labels: no score rather than a made-up one


def test_scout_learns_what_converts():
    samples = ([(scout.features(company("Manufacturing", brief="Factory producing plastic packaging")), True)] * 6
               + [(scout.features(company("Restaurants & Cafés")), False)] * 6)
    model = scout.learn(samples)
    good, reasons = scout.score(model, scout.features(company("Manufacturing", brief="Plastic packaging maker")))
    bad, _ = scout.score(model, scout.features(company("Restaurants & Cafés")))
    assert good > 80 and bad < 35
    assert any(r.startswith("Industry Manufacturing: 6 of 6") for r in reasons)


def test_profiler_rejects_empty_or_invented_answers():
    allowed = ["Education", "Retail"]
    assert profiler.clean({"brief": "", "description": "x"}, allowed) is None  # the pages did not say
    assert profiler.clean("nonsense", allowed) is None
    ok = profiler.clean({"brief": "  Private school   in Beirut for K-12 students. ", "description": "A school.",
                         "offerings": ["K-12", " ", "Summer camp"], "industry": "Banking"}, allowed)
    assert ok["brief"] == "Private school in Beirut for K-12 students."
    assert ok["offerings"] == ["K-12", "Summer camp"]
    assert ok["industry"] is None  # not one of LeadFinder's industries: ignored
