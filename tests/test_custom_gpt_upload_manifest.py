from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
MANIFEST = ROOT / "CUSTOM_GPT_UPLOAD_MANIFEST.md"

EXPECTED_KNOWLEDGE = {
    "三国杀模拟规范.md",
    "三国杀模式规则.md",
    "三国杀基础术语与通用机制.md",
    "三国杀卡牌效果.md",
    "三国杀武将规则补充.md",
    "三国杀增量规则整理_第二次汇总之后.md",
    "三国杀卡牌结构化数据.csv",
    "三国杀卡牌使用方式.csv",
    "三国杀牌堆数据.csv",
    "三角洲枪械分析规范.md",
    "Overlord_DND换算规范.md",
    "通用概率分析规范.md",
}


def test_knowledge_root_has_one_unique_formal_copy_per_manifest_entry() -> None:
    root_files = {path.name for path in KNOWLEDGE.iterdir() if path.is_file()}
    assert root_files == EXPECTED_KNOWLEDGE

    for name in EXPECTED_KNOWLEDGE:
        matches = [
            path
            for path in ROOT.rglob(name)
            if not any(part in {".git", ".pytest_cache", "__pycache__"} for part in path.parts)
        ]
        assert matches == [KNOWLEDGE / name]


def test_manifest_upload_section_lists_only_the_twelve_formal_files() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    upload_section = text.split("## 2. 上传到 Knowledge", 1)[1].split(
        "## 3. 更新现有自定义 GPT", 1
    )[0]

    for name in EXPECTED_KNOWLEDGE:
        assert upload_section.count(f"knowledge/{name}") == 1
    listed = {
        line.split("`knowledge/", 1)[1].split("`", 1)[0]
        for line in upload_section.splitlines()
        if line[:1].isdigit() and "`knowledge/" in line
    }
    assert listed == EXPECTED_KNOWLEDGE
    assert "archive/" in upload_section
    assert "不属于正式上传集合" in upload_section


def test_manifest_routes_instructions_and_requires_backend_cleanup() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    instruction_section = text.split("## 1. 复制到“指令”框", 1)[1].split(
        "## 2. 上传到 Knowledge", 1
    )[0]
    assert instruction_section.count("GPT_INSTRUCTIONS.md") == 2
    assert "删除后台中所有旧附件" in text
    assert "先保存一次 GPT 配置" in text
    assert "本文件仅供本地维护" in text
