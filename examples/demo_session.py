"""Build a small, inspectable VKF database; no LLM or network calls.

Run: python examples/demo_session.py --db ./vkf-demo.db
Refuses an existing path to avoid silently duplicating knowledge.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

# Permit direct execution from the repository without pip installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vkf_storage import Storage


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="./vkf-demo.db")
    args = p.parse_args(argv)
    db_path = Path(args.db)
    if db_path.exists():
        print(f"Error: {db_path} exists; choose a new --db path", file=sys.stderr)
        return 2
    Storage.initialize(db_path)
    with Storage(db_path) as vkf:
        kv = vkf.create_object("knowledge", "KV Cache", "复用历史注意力中的 K/V 状态来减少重复计算。")
        view = vkf.create_object("knowledge", "物化视图", "数据库可以持久保存预计算结果，以便复用查询工作。")
        question = vkf.create_object("question", "Agent Memory 何时应该重新计算？",
                                     "哪些信息值得长期保存，哪些应在需要时重新推理？")
        insight = vkf.create_object(
            "cross_insight", "存储与计算的跨领域权衡",
            "相似：通过额外存储换取计算复用。\n差异：失效语义、准确性要求和缓存内容不同。\n新猜想：可为 Agent Memory 设计可度量的替换策略。",
            synthesized_from=[kv["id"], view["id"]],
            synthesis_rationale="二者都围绕空间、计算和更新代价优化，但不能直接视为等价")
        vkf.add_relation(insight["id"], question["id"], "raises", "类比暴露了长期记忆的重计算问题")
        conv = vkf.create_conversation("新一轮 VKF 脑暴")
        msg = vkf.append_message(conv["id"], "assistant", "可能用访问频率和重建成本调整长期记忆淘汰策略。")
        candidate = vkf.propose_candidate(conv["id"], msg["id"], "idea", "以重建成本评估记忆价值",
                                          "为 Agent Memory 的记忆写入与淘汰增加重建成本指标。")
        suggestion = vkf.suggest_frontier(kv["id"], question["id"], "cross_domain",
                                          "KV Cache 的成本分析可能帮助细化长期记忆的取舍。")
        report = vkf.doctor()
        result = {
            "database": str(db_path.resolve()),
            "ids": {"kv_cache": kv["id"], "materialized_view": view["id"],
                    "open_question": question["id"], "cross_insight": insight["id"],
                    "conversation": conv["id"], "message": msg["id"],
                    "pending_candidate": candidate["id"], "frontier_suggestion": suggestion["id"]},
            "expected": {"formal_objects": 4, "pending_candidates": 1, "relations": 3,
                         "open_questions": 1, "pending_frontier": 1},
            "doctor": report,
            "next_steps": ["python -m vkf_storage --db <your-db> candidate list",
                           "python -m vkf_storage --db <your-db> search 缓存",
                           "python -m vkf_storage --db <your-db> doctor"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
