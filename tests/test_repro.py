from bugmock.models import Trigger
from bugmock.repro import ReproStep, step_matches


def test_step_matches_param_subset():
    t = Trigger(screen="restaurant", action="open", params={"restaurant_id": "R-5520"})
    assert step_matches(ReproStep(screen="restaurant", action="open", params={"restaurant_id": "R-5520", "x": 1}), t)
    assert not step_matches(ReproStep(screen="restaurant", action="open", params={"restaurant_id": "R-2210"}), t)
    assert not step_matches(ReproStep(screen="restaurant", action="scroll", params={"restaurant_id": "R-5520"}), t)


def test_platform_mismatch_422(client, setup_user):
    mu = setup_user("android-18.5-DEL-G7-gold_annual", [])
    r = client.post("/repro/runs", json={"build_id": "ios-18.5", "mock_user_id": mu, "device_id": "iphone-15",
                                         "steps": [{"screen": "home", "action": "open"}]})
    assert r.status_code == 422 and "android" in r.json()["detail"] and "ios" in r.json()["detail"]


def test_unknown_build_404(client, setup_user):
    mu = setup_user("android-18.5-DEL-G7-gold_annual", [])
    r = client.post("/repro/runs", json={"build_id": "android-17.9", "mock_user_id": mu, "device_id": "pixel-7", "steps": []})
    assert r.status_code == 404 and "android-17.9" in r.json()["detail"]


def test_run_ids_and_default_result(client, setup_user, run):
    mu = setup_user("android-18.5-DEL-G7-gold_annual", [])
    first = run(mu, "android-18.5", "pixel-7", [{"screen": "search", "action": "open"}])
    assert first["run_id"] == "RUN-0001" and first["result"] == "not_reproduced"
    assert first["artifacts"]["video_url"].endswith("RUN-0001.mp4") and first["network"] == []
