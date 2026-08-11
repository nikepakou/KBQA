"""Qdrant 连接测试脚本"""
import json, urllib.request

BASE = "http://localhost:6333"

def api(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

# 1. 插入测试向量
vec = [round(0.1 * (i % 10 + 1), 2) for i in range(1024)]
print("=== 1. 插入测试向量 ===")
r = api("PUT", "/collections/knowledge_base/points", {
    "points": [{
        "id": 1,
        "vector": vec,
        "payload": {"content": "Qdrant 向量数据库部署测试", "source": "setup"}
    }]
})
print(f"  插入结果: {r['status']}")

# 2. 搜索测试
print("\n=== 2. 向量搜索测试 ===")
query_vec = [round(0.1 * (i % 10 + 1), 2) for i in range(1024)]
r = api("POST", "/collections/knowledge_base/points/search", {
    "vector": query_vec,
    "limit": 5,
    "with_payload": True
})
for hit in r["result"]:
    score = hit["score"]
    payload = hit.get("payload", {})
    print(f"  score={score:.4f}  content={payload.get('content', '')}")

# 3. Collection 信息
print("\n=== 3. Collection 详情 ===")
r = api("GET", "/collections/knowledge_base")
info = r["result"]["config"]["params"]
print(f"  向量维度: {info['vectors']['size']}")
print(f"  距离度量: {info['vectors']['distance']}")
print(f"  已存点数: {r['result']['points_count']}")

print("\n✅ Qdrant 全部功能验证通过！")
