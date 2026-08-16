"""
模型配置测试

测试模型提供商的 LLM 和 Embedding 配置是否可用。
支持混合配置测试，例如：LLM 用 DeepSeek，Embedding 用 Ollama。
根据 .env 文件中的 LLM_PROVIDER 和 EMBEDDING_PROVIDER 配置自动选择测试目标。
"""

import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import logging
from llm_factory import LLMFactory
from config import (
    LLM_PROVIDER,
    EMBEDDING_PROVIDER,
    # LongCat 配置
    LONGCAT_BASE_URL,
    LONGCAT_API_KEY,
    LONGCAT_LLM_MODEL,
    LONGCAT_EMBEDDING_MODEL,
    # DeepSeek 配置
    DEEPSEEK_BASE_URL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_LLM_MODEL,
    # Ollama 配置
    OLLAMA_BASE_URL,
    LLM_MODEL_NAME,
    EMBEDDING_MODEL_NAME,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_llm_config(provider: str) -> dict:
    """获取指定提供商的 LLM 配置信息"""
    if provider == "ollama":
        return {
            "base_url": OLLAMA_BASE_URL,
            "api_key": None,
            "llm_model": LLM_MODEL_NAME,
        }
    elif provider == "longcat":
        return {
            "base_url": LONGCAT_BASE_URL,
            "api_key": LONGCAT_API_KEY,
            "llm_model": LONGCAT_LLM_MODEL,
        }
    elif provider == "deepseek":
        return {
            "base_url": DEEPSEEK_BASE_URL,
            "api_key": DEEPSEEK_API_KEY,
            "llm_model": DEEPSEEK_LLM_MODEL,
        }
    return {}


def get_embedding_config(provider: str) -> dict:
    """获取指定提供商的 Embedding 配置信息"""
    if provider == "ollama":
        return {
            "base_url": OLLAMA_BASE_URL,
            "api_key": None,
            "embedding_model": EMBEDDING_MODEL_NAME,
        }
    elif provider == "longcat":
        return {
            "base_url": LONGCAT_BASE_URL,
            "api_key": LONGCAT_API_KEY,
            "embedding_model": LONGCAT_EMBEDDING_MODEL,
        }
    return {}


def test_config_loading():
    """测试配置是否正确加载"""
    print("\n" + "=" * 60)
    print("测试 1: 配置加载")
    print("=" * 60)

    print(f"LLM_PROVIDER: {LLM_PROVIDER}")
    print(f"EMBEDDING_PROVIDER: {EMBEDDING_PROVIDER}")

    # 显示 LLM 配置
    llm_config = get_llm_config(LLM_PROVIDER)
    if llm_config:
        print(f"\n[LLM 配置 - {LLM_PROVIDER}]")
        print(f"  BASE_URL: {llm_config['base_url']}")
        if llm_config['api_key']:
            print(f"  API_KEY: {llm_config['api_key'][:10]}...")
        else:
            print(f"  API_KEY: 无需配置（本地服务）")
        print(f"  LLM_MODEL: {llm_config['llm_model']}")

    # 显示 Embedding 配置
    embedding_config = get_embedding_config(EMBEDDING_PROVIDER)
    if embedding_config:
        print(f"\n[Embedding 配置 - {EMBEDDING_PROVIDER}]")
        print(f"  BASE_URL: {embedding_config['base_url']}")
        if embedding_config['api_key']:
            print(f"  API_KEY: {embedding_config['api_key'][:10]}...")
        else:
            print(f"  API_KEY: 无需配置（本地服务）")
        print(f"  EMBEDDING_MODEL: {embedding_config['embedding_model']}")
    else:
        print(f"\n[Embedding 配置 - {EMBEDDING_PROVIDER}]")
        print(f"  ❌ 不支持的 Embedding 提供商")
        if EMBEDDING_PROVIDER == "deepseek":
            print(f"  提示：DeepSeek 不支持 Embedding 服务，请使用 ollama 或 longcat")
        return False

    # 验证在线提供商的 API Key
    if llm_config['api_key'] is not None:
        assert llm_config['api_key'] and llm_config['api_key'] != "your_api_key_here", \
            f"{LLM_PROVIDER}_API_KEY 未配置或使用占位符"

    if embedding_config['api_key'] is not None:
        assert embedding_config['api_key'] and embedding_config['api_key'] != "your_api_key_here", \
            f"{EMBEDDING_PROVIDER}_API_KEY 未配置或使用占位符"

    print("\n✅ 配置加载测试通过")
    return True


def test_llm_connection():
    """测试 LLM 连接"""
    print("\n" + "=" * 60)
    print(f"测试 2: LLM 连接 ({LLM_PROVIDER})")
    print("=" * 60)

    try:
        # 创建 LLM 实例
        llm = LLMFactory.create_llm()
        print(f"✅ LLM 实例创建成功: {LLMFactory.get_llm_model_name()}")

        # 测试简单问答
        print("\n测试问题: '你好，请用一句话介绍你自己'")
        response = llm.invoke("你好，请用一句话介绍你自己")
        print(f"回答: {response.content}")

        print("\n✅ LLM 连接测试通过")
        return True
    except Exception as e:
        print(f"\n❌ LLM 连接测试失败: {str(e)}")
        return False


def test_embedding_connection():
    """测试 Embedding 连接"""
    print("\n" + "=" * 60)
    print(f"测试 3: Embedding 连接 ({EMBEDDING_PROVIDER})")
    print("=" * 60)

    try:
        # 创建 Embedding 实例
        embedding = LLMFactory.create_embedding()
        print(f"✅ Embedding 实例创建成功: {LLMFactory.get_embedding_model_name()}")

        # 测试向量生成
        print("\n测试文本: '这是一个测试文本'")
        text = "这是一个测试文本"
        vectors = embedding.embed_query(text)
        print(f"向量维度: {len(vectors)}")
        print(f"向量前 5 个值: {vectors[:5]}")

        print("\n✅ Embedding 连接测试通过")
        return True
    except ValueError as e:
        print(f"\n❌ Embedding 连接测试失败: {str(e)}")
        return False
    except Exception as e:
        print(f"\n❌ Embedding 连接测试失败: {str(e)}")
        return False


def test_batch_embedding():
    """测试批量 Embedding"""
    print("\n" + "=" * 60)
    print(f"测试 4: 批量 Embedding ({EMBEDDING_PROVIDER})")
    print("=" * 60)

    try:
        embedding = LLMFactory.create_embedding()

        # 测试批量文本
        texts = [
            "知识库问答系统",
            "RAG 技术介绍",
            "向量数据库应用",
        ]
        print(f"测试文本数量: {len(texts)}")

        vectors = embedding.embed_documents(texts)
        print(f"生成向量数量: {len(vectors)}")
        print(f"每个向量维度: {len(vectors[0])}")

        print("\n✅ 批量 Embedding 测试通过")
        return True
    except ValueError as e:
        print(f"\n❌ 批量 Embedding 测试失败: {str(e)}")
        return False
    except Exception as e:
        print(f"\n❌ 批量 Embedding 测试失败: {str(e)}")
        return False


def run_all_tests():
    """运行所有测试"""
    provider_name = LLM_PROVIDER if LLM_PROVIDER == EMBEDDING_PROVIDER else f"LLM={LLM_PROVIDER}/Embedding={EMBEDDING_PROVIDER}"

    print("\n" + "=" * 60)
    print(f"模型配置测试 ({provider_name})")
    print("=" * 60)

    results = []

    # 测试 1: 配置加载
    try:
        results.append(("配置加载", test_config_loading()))
    except AssertionError as e:
        print(f"\n❌ 配置加载测试失败: {str(e)}")
        results.append(("配置加载", False))

    # 测试 2: LLM 连接
    results.append(("LLM 连接", test_llm_connection()))

    # 测试 3: Embedding 连接
    results.append(("Embedding 连接", test_embedding_connection()))

    # 测试 4: 批量 Embedding
    results.append(("批量 Embedding", test_batch_embedding()))

    # 输出测试结果汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = 0
    failed = 0
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\n总计: {passed} 通过, {failed} 失败")

    if failed == 0:
        print(f"\n🎉 所有测试通过！配置正常可用。")
    else:
        print(f"\n⚠️ 部分测试失败，请检查配置和网络连接。")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
