---
feature_ids: [F002]
incident_id: LL-049
topics: [security, api-key, public-repo, git-hygiene]
doc_kind: lesson-learned
created: 2026-09-03
owner: 郭嘉/奉孝 (@ragdoll-pa82)
reviewer: 关羽/云长 (@cat-ko094z1n)
severity: P0
---

# LL-049: 真实 API key 明文 commit 进公开仓库

## 事故

| 维度 | 内容 |
|------|------|
| 时间 | 2026-09-02（commit 0982091）→ 2026-09-03 止损完成 |
| 事故 | `ai_providers.yaml` 直填真实 csi key `sk-FP1o...` + `test_llm.py` fixture 复制 3 处，commit 并 push 到 public repo `StackTony/jingdong-analyzer` |
| 发现 | 关羽跨家族 review 发现并升级（P0） |
| 影响 | key 暴露约 20 小时（forks=0，未确认被外部利用）；违反 F002 spec §5.3 自己写下的 "apiKey 不入库" |
| 止损 | ① 代码撤出（yaml 改 `api_key_env` / 测试换假 key）② force-push 重写分支历史（squash c0322b6）③ 铲屎官 revoke key |
| 恢复 | main a5dae59 合入干净版本，248 passed，全仓 `git grep` 零残留 |

## 错误链条（追到系统性失误，不是"手滑"）

1. **第一层**：铲屎官给了 AI SDK 风格配置格式示例（apiKey 字段带占位），要求的是**格式兼容**
2. **第二层（根因）**：我把"格式支持 api_key 直填"擅自升级为"真实 key 直填入库"，理由是"key 限 pool_0010 池、泄露面可控"——**用工程可行性判断替代了安全策略**。spec §5.3 写的是 apiKey 不入库，我在同一个 yaml 文件的注释里保留着这句话，一边写规则一边违反规则
3. **第三层（放大器）**：测试 fixture 把同一把 key 又复制了 3 处（"既然 yaml 已经有了"的从众心理）；commit 前没有跑任何 secret 扫描；push 前没有想过检查 repo 是 public

## 泛化教训

- **"泄露面可控"不是入库的理由**。key 入库的判断标准只有一条：这个 repo 是不是只有信任的人能看。public repo = 永远 env
- **格式兼容 ≠ 值要照搬**。用户给配置格式示例时，代码支持该格式，值用占位符
- **自己写过/引用过的安全规则，违反时没有 alarm**——规则写在注释里不等于规则被执行。需要机械检查兜底
- **测试 fixture 不复制生产值**。生产 key / 生产 endpoint 都不许进测试，假 key + localhost 是底线
- **push 公开仓库前过一遍 diff**：commit 是本地的（可挽回），push 是公开的（视为泄露）

## 防复发措施（最小杠杆）

1. ✅ 已落地：生产 yaml 注释明确"公开仓库必须 api_key_env"（c0322b6）
2. ✅ 已落地：测试 fixture 全部假 key + localhost（c0322b6）
3. 候选：pre-push hook 跑 `git grep -E 'sk-[A-Za-z0-9]{20,}'` 秘密模式扫描（P7+ 候选，记 BACKLOG）

## 关联

- 发现与升级：关羽 review（2026-09-03 thread 消息）
- 止损 commits：2ef4555（代码撤出，关羽复核放行）→ c0322b6（squash 重写历史）→ a5dae59（merge main）
- Spec 依据：F002 spec §5.3 安全策略
