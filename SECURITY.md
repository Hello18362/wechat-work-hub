# 安全策略 / Security Policy

## 本项目的安全边界

本软件在**本机**读取微信解密后的 SQLite 数据库，并可能把聊天文本发送给你自行配置的大模型 API。因此以下三类问题属于安全范畴：

1. **密钥泄漏**：`.env` 中的 API Key 被写入日志、报告、错误信息或被提交进仓库；
2. **隐私外泄**：真实聊天内容、微信 ID、本机绝对路径被写入产物、示例文件或提交历史；
3. **服务端风险**：本地控制台（`127.0.0.1:5710`）出现目录穿越、越权读文件、命令注入等可被网页利用的问题。

## 报告漏洞

请**不要**通过公开 Issue 报告安全问题。任选其一：

- 使用 GitHub 的 [Private vulnerability reporting](https://docs.github.com/zh/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)（仓库 Security 标签页 → Report a vulnerability）；
- 或发邮件至仓库所有者邮箱（见 GitHub 个人主页）。

报告时请包含：复现步骤、影响范围、你的环境（系统版本 / Python 版本 / 微信版本）、必要时的截图或日志片段（**请先脱敏，勿贴真实聊天内容与 Key**）。

我通常会在 7 天内回复。修复前请勿公开细节。

## 密钥泄漏处置

如果你不小心把自己的 Key 提交进了仓库或贴进了公开 Issue：

1. **立即到服务商控制台吊销该 Key** 并重新生成——这是唯一有效的止损动作，删 commit 不能挽回已经泄漏的 Key；
2. 用新 Key 更新本机 `.env`；
3. 如果发生在 fork 或公开仓库，告知我，我会协助清理历史。

## 支持范围

| 版本 | 安全更新 |
| --- | --- |
| 最新 main 分支 | 支持 |
| 更早的 release / commit | 不保证 |

本项目为个人开源项目，不提供 SLA 或商业支持。

## 已知的设计取舍（不是漏洞）

- 控制台默认只监听 `127.0.0.1`，**没有登录鉴权**。不要把它暴露到公网或 `0.0.0.0`；如需远程访问，请自行套反向代理并加认证。
- 报告默认包含聊天原文（这是产品设计），分享前需自行脱敏。
- 解密数据库目录由 `.env` 的 `WX_DECRYPTED_DIR` 指定，程序对该目录有读权限，请确保该目录仅本机用户可访问。
