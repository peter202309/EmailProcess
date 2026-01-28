# Gemini API 配额限制解决方案

## 问题描述
您遇到了 Gemini API 的 429 RESOURCE_EXHAUSTED 错误，这意味着您已达到免费配额限制。

## 当前限制（免费版）
- **每分钟请求数 (RPM)**: 15 次
- **每天请求数 (RPD)**: 1,500 次
- **每分钟输入 Token 数**: 有限制

## 解决方案

### 方案 1: 等待配额重置 ⏰
- **每分钟配额**: 等待 1 分钟后自动重置
- **每天配额**: 等待到第二天（UTC 时间）自动重置
- **优点**: 免费
- **缺点**: 需要等待

### 方案 2: 升级到付费计划 💳
访问 https://ai.google.dev/pricing 了解 Gemini API 付费计划：
- **按使用量付费**: 只为实际使用付费
- **更高的配额**: 
  - 2,000 RPM
  - 无每日限制
- **更快的响应**: 优先处理

### 方案 3: 使用新的 API Key 🔑
1. 访问 https://aistudio.google.com/app/apikey
2. 创建新的 API Key（可以使用不同的 Google 账号）
3. 在 `.env` 文件中替换：
   ```
   VITE_GEMINI_API_KEY=你的新API密钥
   ```
4. 重启后端服务

### 方案 4: 优化使用策略 📊
1. **减少分析频率**: 只对重要附件使用 AI 分析
2. **批量处理**: 将多个附件合并后一次性分析
3. **缓存结果**: 避免重复分析相同文件

## 当前系统状态

### ✅ 仍可正常使用的功能：
- 邮件接收和显示
- 邮件分类和分析（使用 OpenAI API）
- AI 自动回复生成（使用 OpenAI API）
- 知识库搜索
- 模板管理

### ❌ 暂时不可用的功能：
- 附件深度分析（图片/PDF 识别）
  - 这个功能专门使用 Gemini Vision API

## 技术细节

### 错误信息解析
```
429 RESOURCE_EXHAUSTED
- Quota exceeded for: generativelanguage.googleapis.com/generate_content_free_tier_input_token_count
- Quota exceeded for: generativelanguage.googleapis.com/generate_content_free_tier_requests
```

### 已实施的改进
1. **友好的错误提示**: 现在错误信息会直接显示在分析面板中
2. **错误日志记录**: 所有配额错误都会记录到系统日志
3. **不影响其他功能**: 附件分析失败不会影响邮件处理

## 推荐做法

### 短期解决（今天）
1. 等待 1 小时后再使用附件分析功能
2. 优先使用邮件分析功能（不受影响）

### 长期解决（持续使用）
1. **如果是个人使用**: 使用免费配额，注意使用频率
2. **如果是商业使用**: 建议升级到付费计划
3. **如果是开发测试**: 准备多个 API Key 轮换使用

## 监控配额使用

访问以下链接查看当前配额使用情况：
- https://ai.dev/rate-limit
- https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas

## 需要帮助？

如果您需要进一步的帮助，请提供以下信息：
1. 您的使用场景（个人/商业）
2. 预计每天的附件分析次数
3. 是否愿意升级到付费计划

---
**最后更新**: 2026-01-28
**系统版本**: AI Mailguard v1.0
