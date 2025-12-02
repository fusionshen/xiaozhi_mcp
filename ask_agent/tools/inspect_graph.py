import os
import gzip
import pickle
from pprint import pprint

def load_pickle(file_path: str):
    """加载 pickle 或 pickle.gz 文件"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    if file_path.endswith(".gz"):
        with gzip.open(file_path, "rb") as f:
            data = pickle.load(f)
    else:
        with open(file_path, "rb") as f:
            data = pickle.load(f)
    return data

def print_graph_summary(graph):
    """打印 ContextGraph 概览"""
    print("\n=== Graph Meta ===")
    pprint(graph.meta)

    print("\n=== 节点列表 ===")
    for node in graph.nodes:
        entry = node.get("indicator_entry", {})
        nid = node.get("id")
        indicator = entry.get("indicator")
        formula = entry.get("formula")
        timeString = entry.get("timeString")
        status = entry.get("status")
        print(f"[{nid}] indicator: {indicator}, formula: {formula}, time: {timeString}, status: {status}")

        # 打印备选公式
        cands = entry.get("formula_candidates") or []
        if cands:
            print("  公式候选:")
            for cand in cands:
                print(f"    {cand.get('number')}. {cand.get('FORMULANAME')} ({cand.get('FORMULAID')}) score={cand.get('score'):.4f}")
        print("-" * 40)

def main():
    file_path = input("请输入 pickle 文件路径 (.pkl 或 .pkl.gz): ").strip()
    try:
        graph = load_pickle(file_path)
        print(f"✅ 成功加载: {file_path}, 类型: {type(graph)}")
        print_graph_summary(graph)
    except Exception as e:
        print(f"❌ 加载失败: {e}")

if __name__ == "__main__":
    main()
