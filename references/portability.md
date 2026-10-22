# 便携使用与能力映射

## 使用包，不自动安装

本文件夹采用Agent Skills的最小公共结构：根目录`SKILL.md`含标准YAML `name`、`description`，其余为Markdown、相对路径引用、JSON模板及可选Python脚本。复制时保留整个`branch-study-ppt`目录，不能只复制入口而丢失references或assets。安装位置、上传接受条件和运行权限由宿主决定；本包不自动修改它们。

最通用的手动入口：将完整目录放入获授权工作区，告诉智能体：“先读取branch-study-ppt/SKILL.md，再按其中链接读取当前步骤所需文件。开始前检查能力，按workflow.md每次只做一个next_action。任务是：[实际任务与范围]。”

这属于显式加载指令，不等于宿主自动发现或已经安装。用户仅要求打包／审计时，不执行具体PPT任务、试跑、回测、上传或安装。

## 主流入口与已知差异

- **Claude Code**：官方文档支持项目内`.claude/skills/branch-study-ppt/SKILL.md`及个人技能目录。经用户要求安装时，保留完整文件夹，按[官方Skills说明](https://code.claude.com/docs/en/skills)选择作用域；不把它等同于所有Claude产品的上传规则。
- **Codex**：当前官方文档支持项目内`.agents/skills/branch-study-ppt/SKILL.md`及个人技能目录；按[官方技能文档](https://learn.chatgpt.com/docs/build-skills)配置，不假定历史目录或某个产品版本始终相同。
- **DeepSeek harness（dsh）**：官方 `skill-filesystem` 文档支持项目 `.dsh/skills/branch-study-ppt/SKILL.md` 或 `.agents/skills/branch-study-ppt/SKILL.md`，直接子目录中的入口含 `name`、`description`。宿主需配置 `skill`、`skill-filesystem` 提供方与 `dsh-tool-skill` 工具；这只是已核对的文件发现机制，不代表本包已完成 dsh 实测或自动具备 PPTX 编辑／渲染能力。机制来源及核对版本见 [sources.md](../docs/sources.md)。
- **WorkBuddy本地导入**：官方入口为“专家·技能·连接器 → 技能 → 添加技能 → 上传技能”，见[技能市场说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)。确切ZIP根目录嵌套要求未从该说明验证，不承诺一键导入。若解析拒绝，可经用户选择解压整个文件夹到工作区，再用上面的显式加载方式；不能声称自动发现成功。
- **其他智能体**：支持[Agent Skills规范](https://agentskills.io/specification)的宿主有格式层面的可移植基础；不支持时可显式读取完整文档。实际加载、PPT工具、渲染和隔离审查能力仍须现场检查。

WorkBuddy开放平台的市场发布是另一个流程，其[官方发布文档](https://open.workbuddy.cn/en/docs/skill)要求额外的description_zh、description_en、version、author等字段。本公共包不加入这些非公共字段，不等于已满足市场发布条件。发布适配或账号操作另需授权。

以上是基于官方文档的格式与入口说明，不是各平台端到端实测报告；版本变化时重新查官方说明。未承诺所有平台、模型或低算力配置都能产出相同质量。

## 能力预检与诚实降级

| 能力 | 用途 | 缺失时 |
|---|---|---|
| 获取真实当前日期、搜索并读取官方全文 | 当期选题、来源和动态事实核验 | 按[source-recovery.md](source-recovery.md)区分入口、渲染、工具及权限缺口；可整理用户提供的完整资料，但未完成的最新核验仍标未验证 |
| 实际存在、连接就绪且获授权的渲染浏览／浏览器桥接（条件性） | 静态读取无正文时访问真实文章详情页 | 先检查宿主真实能力及环境；未测不写失败，缺失不虚构工具，不要求安装或改全局权限；可请求文章全文／导出 |
| 本地文件读取／获准目录写入 | 产物、台账、状态和报告 | 只提供可见文字方案，不声称保存成功 |
| 创建原生可编辑PPTX | 正文、图表、表格、备注和媒体 | 可提供逐页大纲，明确不是PPTX交付；不改扩展名伪装 |
| PPTX全页渲染及视觉查看 | 字体、溢出、裁切与逐页验收 | 不能通过视觉验收；XML或缩略图抽样不替代 |
| 读取媒体时长／解码，必要时目标PowerPoint播放 | 视频可用性和时长 | 各层单独标未验证，不能以关系存在代替播放 |
| 真正全新且不继承作者对话的审查上下文 | 独立审查及复审 | 标独立审查阻塞；角色扮演、另建文件夹不是替代 |
| Python标准库执行（可选，版本见runtime.md） | 只读结构辅助检查与离线预检 | 缺Python仅阻塞辅助脚本；可用其他能力完成必需检查，不因此自动判整个PPT任务不可行 |
| 已授权交付与最小权限检查 | 最终交付 | 保留文件ready、交付blocked或not_attempted，向用户说明缺口 |

工具名称不写死：把能力映射到宿主实际的浏览／搜索、文件、PPT编辑／渲染、媒体检查和新上下文执行能力。独立目录方便管理，不代表隔离会话或安全沙箱；保留宿主默认权限。WorkBuddy也建议独立目录、文件副本及审慎使用权限，参见[权限模式说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Permission-Modes)。

Python的静态API下限、实际已测版本、UTF-8父子进程契约、无缓存命令及离线预检见[runtime.md](runtime.md)。预检仅发现辅助环境与候选工具，不会验证浏览器桥接连接、编辑器自动化或渲染成功；不能用“检测到”代替“实际可用”。

能力清单逐项记“实际工具／应用、是否存在、是否已连接或可调用、最小验证证据、授权范围、尚未验证内容”，不要只列已安装软件名。缺`python-pptx`只说明该库不可用，不证明无法制作PPTX；若宿主已有获准的PowerPoint、LibreOffice或其他原生编辑／导出能力，应分别检查其实际可编辑对象、备注、媒体、PPTX保存及全页渲染能力再选择。应用存在不等于自动化接口可用，导出成功也不等于目标PowerPoint播放通过。无需为使用另一可行工具默认安装依赖。已有真实隔离审查能力就使用它，不因制作库缺失将独立审查一并判为不可用。

对较弱模型的操作规则：一次只推进run_state中的next_action；遇阻塞只处理已明确的原因；不要“为了完成”跳过证据、改验收标准或猜工具结果。能力不足可以交付明确标注的部分成果，不能宣称完整完成。
