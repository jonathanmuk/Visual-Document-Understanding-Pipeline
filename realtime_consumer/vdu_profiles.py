"""Profiles: domain-specific prompts and region rules layered over config.yaml.

A profile is a small YAML file in profiles/ holding only what differs from the
base config. At start-up the worker merges it over the base and hands the SDK the
merged file. Maps are merged key by key; anything else (a list, a string) in the
profile replaces the base value outright.

Profiles change prompts and which regions are read, which only matters in
self-hosted mode. In Z.ai mode the SDK sends the whole file to Z.ai's service,
which applies its own prompts and rules.
"""
import copy
import os

import yaml

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
# Tasks the SDK handles itself rather than by sending a prompt to the model.
NO_PROMPT_TASKS = {"skip", "abandon"}


def available(profiles_dir=PROFILES_DIR):
    if not os.path.isdir(profiles_dir):
        return []
    return sorted(f[:-5] for f in os.listdir(profiles_dir) if f.endswith(".yaml"))


def merge(base, override):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve(base_path, profile, profiles_dir, out_dir):
    """Return (path to hand the SDK, merged config as a dict)."""
    base = load(base_path)
    if profile in ("", "default"):
        return base_path, base
    profile_path = os.path.join(profiles_dir, f"{profile}.yaml")
    if not os.path.exists(profile_path):
        raise SystemExit(f"unknown profile '{profile}'; available: default, {', '.join(available(profiles_dir))}")
    merged = merge(base, load(profile_path))
    merged.pop("profile", None)
    out_path = os.path.join(out_dir, f"glmocr-{profile}.yaml")
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, sort_keys=False, allow_unicode=True)
    return out_path, merged


def check(config):
    """List the ways this config would lose content without saying so.

    The SDK silently drops a region whose label is in no bucket, uses the first
    bucket when a label is in two, and sends an empty prompt for a task with no
    prompt. Its config model accepts unknown keys, so a typo passes validation.
    """
    pipeline = config.get("pipeline") or {}
    layout = pipeline.get("layout") or {}
    labels = set((layout.get("id2label") or {}).values())
    mapping = layout.get("label_task_mapping") or {}
    prompts = (pipeline.get("page_loader") or {}).get("task_prompt_mapping") or {}
    image_category = set(((pipeline.get("result_formatter") or {}).get("label_visualization_mapping") or {}).get("image") or [])

    problems = []
    seen = {}
    for task, bucket in mapping.items():
        if not isinstance(bucket, list):
            problems.append(f"bucket '{task}' is not a list")
            continue
        for label in bucket:
            if label in seen:
                problems.append(f"label '{label}' is in both '{seen[label]}' and '{task}'")
            seen[label] = task
        if task not in NO_PROMPT_TASKS and bucket and not (prompts.get(task) or "").strip():
            problems.append(f"task '{task}' has no prompt in task_prompt_mapping")
    for label in sorted(labels - set(seen)):
        problems.append(f"label '{label}' is in no bucket, so it would be dropped silently")
    for label in sorted(set(seen) - labels):
        problems.append(f"label '{label}' is not a label the layout model produces")
    for label in sorted(image_category):
        if seen.get(label) not in (None, "skip"):
            problems.append(f"label '{label}' is transcribed but shown as an image placeholder, so its text is lost")
    return problems
