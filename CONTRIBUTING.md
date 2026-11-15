# 参与贡献 / Contributing

欢迎提 Issue，也欢迎提 Pull Request——本项目采用 [PolyForm Noncommercial 1.0.0](LICENSE)，**允许修改和再分发**，所以你的改动是可以被合并的。

只有一条底线：**不能商用**。

---

## 最重要的一条：不要提交真实聊天数据

这是唯一的硬规矩。以下东西**绝对不能**出现在 Issue、PR 或提交历史里：

- 真实的 `config/groups.yaml`（含真实群名、同事/同学姓名）
- `runs/`、`share/`、`logs/` 下的任何产物
- 任何 `.db` / `.db-wal` / `.db-shm` 文件
- 截图里直接显示真实群名与聊天内容的图片
- 含有个人绝对路径（`C:\Users\你的名字\...`）或微信 ID（`wxid_xxx`）的代码与文档

提交前自查：

```bash
# 微信 ID、个人绝对路径、群 ID
git diff --cached | grep -iE "wxid_|C:\\\\Users|D:\\\\|@chatroom"
```

再对着 `config/groups.yaml` 看一眼：你提交的内容里有没有真实群名或真实姓名。有就撤掉。

示例数据请用 `XX项目工作群` / `张总` 这类明显的占位符。

---

## 提交 Issue

请写清楚：

1. **环境**：Windows 版本、Python 版本、微信 PC 版版本号；
2. **复现步骤**：从哪一步开始、点了什么、期望什么、实际什么；
3. **报错**：`logs/hub.log` 里的相关片段（**先脱敏**）；
4. **模型配置**：用的哪个服务商、`summarizer.provider` 是什么、有没有开语音转写。

如果是「跑不起来」，先确认这三点：微信 PC 版已登录、解密工具已成功执行、`.env` 里的 `WX_DECRYPTED_DIR` 指向的目录里确实有 `*.db`。

> 提示：如果你刚更新了代码却看到「未知接口」，通常是后端进程还是旧的——双击 `一键启动.bat` 重启即可。

---

## 提交 Pull Request

- 一个 PR 只做一件事，不要顺手重构无关文件；
- **保持依赖最小化**：核心链路只用 `requests` + `PyYAML` + 标准库，不要为了小功能引入 Flask / FastAPI / pandas 这类重依赖；可选能力必须做成懒加载 + 缺失降级；
- 新增的异常分支必须有兜底：**单条消息处理失败不能中断整批任务**；
- 改动了边界逻辑，请在 `tests/test_regression.py` 里补一个用例，命名说明它防的是哪个故障；
- 提交前跑一遍：

```bash
python tests/test_regression.py
python tools/test_model_api.py    # 改动了模型配置相关代码时
```

---

## 代码风格

- 遵循 PEP 8，行宽 100（见 `pyproject.toml` 的 black / isort 配置）；
- 公开函数写 docstring，说明参数与失败时的行为；
- 注释写「为什么这么做」，不要写「这行在做什么」；
- 前端在 `web/assets/`，零框架、无构建步骤，改完刷新即可（缓存按文件 mtime 自动失效）；
- 动效遵守两条既有约束：时长 200–420ms、统一用 spring 曲线（`cubic-bezier(.22,1.35,.36,1)`），不使用 `linear`。

---

## 提交信息

一句话说清改了什么、为什么改：

```
修复：元旦当天 --date yesterday 抛 ValueError
新增：语音转写失败时在报告中标注原因
```

---

## 许可

你的贡献将以本项目的 [PolyForm Noncommercial 1.0.0](LICENSE) 授权发布：可自由修改与再分发，但不得用于商业用途。
