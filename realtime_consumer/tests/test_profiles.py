"""Profiles must produce a config the SDK accepts and that loses nothing silently."""
import os

import pytest
import yaml

import vdu_profiles as p

HERE = os.path.dirname(__file__)
BASE = os.path.join(HERE, "..", "config.yaml")
PROFILES = p.available()


def test_the_shipped_profiles_exist():
    assert {"finance", "academic"} <= set(PROFILES)


@pytest.mark.parametrize("profile", ["default"] + PROFILES)
def test_every_profile_is_clean(profile, tmp_path):
    path, data = p.resolve(BASE, profile, p.PROFILES_DIR, str(tmp_path))
    assert p.check(data) == []


@pytest.mark.parametrize("profile", ["default"] + PROFILES)
def test_every_profile_is_accepted_by_the_sdk(profile, tmp_path):
    glmocr_config = pytest.importorskip("glmocr.config")
    path, _ = p.resolve(BASE, profile, p.PROFILES_DIR, str(tmp_path))
    glmocr_config.GlmOcrConfig.from_yaml(path)


def test_charts_are_described_not_dropped():
    data = p.load(BASE)
    layout = data["pipeline"]["layout"]
    assert "chart" in layout["label_task_mapping"]["chart"]
    assert "chart" not in layout["label_task_mapping"]["skip"]
    assert data["pipeline"]["page_loader"]["task_prompt_mapping"]["chart"].strip()
    assert "chart" not in data["pipeline"]["result_formatter"]["label_visualization_mapping"]["image"]


def test_finance_reads_headers_and_footers_but_still_drops_page_numbers(tmp_path):
    _, data = p.resolve(BASE, "finance", p.PROFILES_DIR, str(tmp_path))
    mapping = data["pipeline"]["layout"]["label_task_mapping"]
    assert {"header", "footer", "footnote"} <= set(mapping["text"])
    assert "number" in mapping["abandon"]
    # Buckets the profile does not mention come from the base config.
    assert mapping["table"] == ["table"]
    assert mapping["chart"] == ["chart"]


def test_merge_replaces_lists_and_merges_maps():
    base = {"a": {"x": 1, "y": [1, 2]}, "b": 2}
    assert p.merge(base, {"a": {"y": [3]}}) == {"a": {"x": 1, "y": [3]}, "b": 2}
    assert base["a"]["y"] == [1, 2], "the base is not modified"


def test_unknown_profile_is_refused_with_the_list(tmp_path):
    with pytest.raises(SystemExit) as e:
        p.resolve(BASE, "legal", p.PROFILES_DIR, str(tmp_path))
    assert "available: default, academic, finance" in str(e.value)


def _mutate(tmp_path, edit):
    data = p.load(BASE)
    edit(data)
    return p.check(data)


def test_check_catches_a_label_in_no_bucket(tmp_path):
    problems = _mutate(tmp_path, lambda d: d["pipeline"]["layout"]["label_task_mapping"]["table"].clear())
    assert "label 'table' is in no bucket, so it would be dropped silently" in problems


def test_check_catches_a_label_in_two_buckets(tmp_path):
    problems = _mutate(tmp_path, lambda d: d["pipeline"]["layout"]["label_task_mapping"]["skip"].append("table"))
    assert any("'table' is in both" in x for x in problems)


def test_check_catches_a_task_with_no_prompt(tmp_path):
    problems = _mutate(tmp_path, lambda d: d["pipeline"]["page_loader"]["task_prompt_mapping"].pop("chart"))
    assert "task 'chart' has no prompt in task_prompt_mapping" in problems


def test_check_catches_a_typo_in_a_label(tmp_path):
    problems = _mutate(tmp_path, lambda d: d["pipeline"]["layout"]["label_task_mapping"]["text"].append("paragraph_tittle"))
    assert "label 'paragraph_tittle' is not a label the layout model produces" in problems


def test_check_catches_text_hidden_behind_an_image_placeholder(tmp_path):
    def edit(d):
        d["pipeline"]["result_formatter"]["label_visualization_mapping"]["image"].append("chart")
    assert any("'chart' is transcribed but shown as an image placeholder" in x for x in _mutate(tmp_path, edit))


def test_profile_files_are_small_overrides_not_copies():
    for name in PROFILES:
        with open(os.path.join(p.PROFILES_DIR, f"{name}.yaml"), encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert set(data) == {"pipeline"}
        assert "ocr_api" not in data["pipeline"] and "maas" not in data["pipeline"], \
            "connection settings belong to the base config, not a profile"
