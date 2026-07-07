import json
from pathlib import Path

NEWS_TEMPLATES_FILE = Path(__file__).parent.parent / "data" / "news_templates.json"

DEFAULT_TEMPLATES = ["نقلاً من", "خاص", "عاجل", "مصدر موثوق"]


def load_templates() -> list[str]:
    if not NEWS_TEMPLATES_FILE.exists():
        save_templates(DEFAULT_TEMPLATES)
        return list(DEFAULT_TEMPLATES)
    try:
        data = json.loads(NEWS_TEMPLATES_FILE.read_text())
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, Exception):
        pass
    return list(DEFAULT_TEMPLATES)


def save_templates(templates: list[str]) -> None:
    NEWS_TEMPLATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    NEWS_TEMPLATES_FILE.write_text(json.dumps(templates, ensure_ascii=False))
