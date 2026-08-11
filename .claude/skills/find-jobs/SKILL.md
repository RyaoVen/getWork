---
name: find-jobs
description: 校招/实习岗位搜寻与邮件推送。用户发来简历、或口述想做什么方向/有什么技术栈、或说"帮我找岗位/找实习/看看最近校招"时使用。流程：构建求职画像 → 调 getWork MCP 抓取岗位 → 匹配筛选 → 渲染简报 → 邮件推送。需要登录的站点向用户索要账号密码，SMTP 未配置时引导用户填写。
---

# find-jobs：帮我找校招/实习岗位

用户把简历交给 Agent，或口述求职方向，目标是找到匹配的岗位、生成简报并邮件推送。你负责指挥，MCP 工具负责干活。

## 0. 前提检查

先确认 getWork MCP 可用（工具列表里有 `list_sources`/`crawl_jobs`/`login`/`render_briefing`/`send_email`）。若不可用，告诉用户先在该项目里启用 getwork 这个 MCP server（.mcp.json 已配置好）。

## 1. 构建求职画像（写 `config/profile.yaml`）

- **简历文件入口**：先读文件提取文本——PDF 用 `anthropic-skills:pdf-reading`，Word 用 `anthropic-skills:docx`，普通文本直接 Read。从中抽取：目标方向（如"后端开发"）、技术栈、期望地点、岗位类型（日常实习|校招|提前批）、关键词，并**记下简历里的项目经历和技能**——匹配时用得上（比如对方要求 Spring Boot，你简历里有）。把简历路径写进 profile 的 `resume` 字段。
- **口述入口**：若信息不全（方向、技术栈、地点至少得有方向），用 AskUserQuestion 或直接问，问清：目标方向、技术栈、地点偏好、岗位类型、是否只投特定公司。**绝不猜测用户的求职偏好。**
- 若 `config/profile.yaml` 已存在，读出并合并本次更新的字段，再写回。

profile.yaml 结构：

```yaml
profile:
  direction: "后端开发"
  tech_stack: ["Python", "Go", "MySQL", "Docker"]
  job_type: "日常实习"
  locations: ["北京", "上海", "远程"]
  keywords: ["后端", "Python", "Go"]
  target_companies: []
  recipient_email: ""    # 收件邮箱；留空则问用户
```

## 2. 抓取岗位

### 添加目标公司（用户给了公司名 + 链接，说"添加这个公司"时）

1. 调 `add_source(name=公司名, url=链接)`（strategy 会自动探测；若用户/你知道是平台 API 可带 `platform`/`company_key`）。
2. 立即对返回的 `source.key` 调 `crawl_jobs` 验证能否抓到岗位。
3. 若抓不到或字段为空：用 WebFetch/浏览器看页面结构，推断 `selectors`（static/dynamic）或 `api`+`fields`（platform），再调 `add_source` 传这些配置覆盖（同名 key 覆盖）。
4. 确认可用后，把公司名写进画像的 `target_companies`，存回 `config/profile.yaml`。

然后继续：

1. `list_sources` 查看已配置的来源。
2. 逐个 `crawl_jobs(source=<key>)`（可按需传 `since_days`）。
3. 若返回 `status: "login_required"`：向用户索要该来源的**账号和密码**（说明只用于本次登录、不落盘），调用 `login(source, username, password)`，成功后重试 `crawl_jobs`。若登录返回 `captcha_required`，用 `headed: true` 重试，让用户在弹出的浏览器窗口里手动完成验证码/滑块。
4. 汇总所有 `status:"ok"` 的岗位。

## 3. 匹配筛选（只留相关岗位，给匹配度）

- **先过滤**：只保留与画像相关的岗位——后端/全栈/研发类岗位。**与画像无关的岗位（纯运营、市场、销售、产品、设计、HR、算法/AI 等与后端开发无关的）直接剔除，不要放进简报。**（可调用 `getwork/match.py` 的 `filter_and_score` 做机械打分，再用你的判断修正。）
- **给每条匹配的岗位打匹配度**：用一个分数（如 72 分）或档位（高/中/低），依据是岗位方向、技术栈命中、职责匹配程度。理由写清楚命中点（如"命中: Go、Java、后端方向；对方要求 Spring Boot 你简历里有"）。
- 按公司分组，组内按匹配度从高到低排。
- 简报开头说明：抓了多少条、筛出多少条相关、剔除了多少无关。
- 若来源没配好（`unknown_source` 或空来源），如实告诉用户当前配置里有哪些公司，问是否要新增。

## 4. 生成简报（Markdown）

用 `render_briefing(markdown, title)`。简报**固定分两部分**：

### (a) 顶部总表格
一张总表，一眼看全貌：`公司 | 岗位数 | 匹配关键词 | 匹配理由概述 | 申请链接`

### (b) 下方每个岗位的内容块
每个岗位一个内容块（小标题），包含四要素：

- **岗位方向**：这个岗位是做什么的（从岗位描述里提炼）
- **要求**：优先用抓取到的 `requirement`/`description` 原文摘要；**抓不到就写"详见官网"并附详情链接**，不要编造要求
- **发展建议**：结合你的画像和岗位要求，建议补什么、准备什么；一句话即可
- **附**：地点 / 发布日期 / 截止 / 申请链接

**详情链接**：每个岗位必须给一条可达链接——有详情页用详情页，没有就用公司岗位列表页/校招首页，别让用户摸不着门。

**完整呈现（硬性）**：简报必须包含抓到的**每一个岗位**，禁止悄悄截断或只列前几条。岗位多、内容长时也要全部写入；开头明确标注总数（如「共 370 条」），让用户知道每一家抓到了多少、列了多少。实在需要省略时，必须显式说明「省略了哪几家、共 N 条」。

**文案风格**：像人整理的摘要，平实具体，不要感叹号、不要堆形容词、不要"解锁""赋能""不容错过"这类空话，也不要一坨 emoji。你负责筛选和判断，不负责吆喝。

`render_briefing` 会返回 `html_path` 和 `png_path`（相对 data/ 的路径）。

## 5. 邮件推送

- 先确认收件邮箱（画像里 `recipient_email` 或 .env 的 `SMTP_TO`，否则问用户）。
- 若 `send_email` 返回 `not_configured`：说明 SMTP 还没配置，**引导用户一次性配置**——在项目根目录的 `.env`（没有就复制 `.env.example`）填：
  - `SMTP_HOST`/`SMTP_PORT`：QQ 邮箱 `smtp.qq.com` 465；网易 163 `smtp.163.com` 465
  - `SMTP_USER`：邮箱地址
  - `SMTP_AUTHCODE`：**授权码**（QQ：设置 → 账户 → 开启 SMTP 服务 → 生成 16 位授权码；163：设置 → POP3/SMTP → 开启后按提示生成）。授权码不是登录密码。
  - 配好后由用户保存，你再调 `send_email` 重试。SMTP 配置是一次性的，之后每次跑都会复用。
- 调 `send_email(to, subject, html=<render_briefing 的 html>, attachment_path=<png_path>)`：HTML 正文 + PNG 附件。
- 若返回 `auth_failed`：授权码可能过期/填错，提示用户重新生成。

## 6. 汇报

向用户说明：抓了几家公司、匹配出几条、简报文件路径（HTML+PNG）、是否已发送到哪个邮箱。若某来源登录失败或抓取失败，如实说明并给出下一步建议。

## 原则

- **缺什么要什么**：要登录就向用户要账号密码；要发信就向用户要邮箱/配置。不要擅自假设。
- **密码不落盘**：只在调用 login 时传入，会话 cookie 由 MCP 持久化，密码本身不保存。
- **画像持久化**：每次跑完把更新后的画像写回 `config/profile.yaml`，下次直接复用。
