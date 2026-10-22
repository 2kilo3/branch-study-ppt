# 工具链：从能力到动作

本文件补充执行路径，不改变学习强国主源、默认40—45分钟、可编辑PPTX或独立审查要求。先读[portability.md](portability.md)、[runtime.md](runtime.md)和当前阶段。仅维护技能包不授权制作试验PPT、下载选题媒体或操作用户电脑。

## 1. 先复用已有能力

优先级：宿主已提供且获准的演示文稿／浏览／渲染工具 → 已连接的应用及其正式接口 → 已安装且宿主允许使用的库／CLI。安装、新连接、权限变更分别遵守宿主要求，不为缺一个库重建整套基础设施。宿主指定某个制作工具时遵从该要求，本表不授权换用被禁止的工具。

先登记：能力、工具／应用及版本、所在环境、是否连接、授权范围、最小实际验证、未验证范围。`command -v`、预检或发现应用只能证明“发现候选”，不能填“渲染／播放通过”。具体制作任务中用S05代表页检验链路，不另造与任务无关的试验文件；未获制作授权只检查文档与能力信息。

| 能力 | 首选可执行动作 | 验证产物 | 缺失／失败后的路径 |
|---|---|---|---|
| 官方全文、JS页面 | 可靠搜索取得真实详情URL；静态无正文且无拒绝时，用宿主现有渲染浏览器打开同页，等正常加载、检查新标签与分页 | 标题、来源、日期、全文首尾及定位；不只看首屏 | 按[source-recovery.md](source-recovery.md)恢复。先检查现有浏览器，不猜URL／私有API、不先写自制爬虫；外站替代仍需相应批准 |
| 原生可编辑PPTX | 已有演示工具或PowerPoint创建文本、表格、图表、备注，保存PPTX；逐项确认其媒体能力 | 重开候选，检查对象类型、备注、字体及实际媒体 | 已有LibreOffice或获准库可以分别评估；缺python-pptx不是整个任务阻塞 |
| Python／JS制作候选 | 宿主允许时，按当前安装版本的[python-pptx API](https://python-pptx.readthedocs.io/en/latest/)或[PptxGenJS文档](https://gitbrent.github.io/PptxGenJS/docs/usage-pres-create/)调用公开接口 | 原生对象、备注、保存后重开与媒体关系逐项验，不凭“成功写文件”通过 | 库缺失先用已有应用；确需安装先按宿主取得授权，不自动pip/npm安装。库不等于渲染器或PowerPoint播放器 |
| 全页静态渲染 | 现有宿主渲染工具；或PowerPoint导出PDF／全页图片；或LibreOffice headless导出PDF，再转逐页图片 | 候选哈希、渲染器版本、全部页图、页序映射、隐藏页清单、逐页检查 | 按第2节更换获准渲染路径。替代渲染器通过仅覆盖该渲染器，不冒充目标PowerPoint |
| 图片正确映射 | 每张图以固定media_id绑定文件、内容、来源与目标页；逐张核对原图，必要时生成带ID和文件名标签的缩略图总览 | 图中对象与正文／图注相符，返回对象ID与文件一致 | 不按批量读取返回顺序猜配图；标签不符即停止使用该图，回到原始资产核对 |
| 视频获取、裁剪、解码 | 官方下载或宿主允许的公开播放器资源路径；已有ffprobe/FFmpeg或正式媒体工具 | 原片与片段哈希、实际时长、编码、裁剪区间、解码报告 | 见[media-workflow.md](media-workflow.md)。缺工具不绕过网站／版权限制，不把链接当嵌入 |
| 目标放映与声音 | 在获准的目标PowerPoint打开最终候选，按明确播放模式进入视频页实测 | 应用版本、当前页、启动／进度／声音／结束结果与观察者 | 不能听到音频或无法确认放映态时，精确标未验证；按媒体清单请求最小补测，不循环采样屏幕 |

python-pptx的`add_movie`在官方文档中仍标为实验性：尺寸、MIME与封面需显式处理，不能据此承诺自动播放或跨平台一致。[电影对象API](https://python-pptx.readthedocs.io/en/latest/api/shapes.html)、[备注API](https://python-pptx.readthedocs.io/en/latest/user/notes.html)、[PptxGenJS媒体API](https://gitbrent.github.io/PptxGenJS/docs/api-media/)可作候选路线，实际支持以安装版本与重开结果为准。不要为未支持功能直接拼未知OOXML。

## 2. 全页渲染路线与系统差异

### PowerPoint应用路线

- Windows：打开候选后用“文件 → 导出 → 创建PDF/XPS”，确认导出范围是全部演示页而非当前页、讲义或备注。需要覆盖隐藏页时显式选择并在映射中另标。获准的Windows自动化也可调用公开的`Presentation.Export`逐页导出图片，先验证接口与导出过滤器，不假设安装PowerPoint就能调用COM。
- macOS：用PowerPoint“文件 → 导出”或“另存为 → PDF”。不要照搬Windows COM脚本。官方说明的PDF选项与Windows并不相同，尤其隐藏页／备注范围须现场核查；无法覆盖的页用获准的其他逐页导出方式补齐并标注。
- Linux／无目标桌面PowerPoint：可以用宿主渲染器或LibreOffice生成静态预览。不要把这项结果标成Windows或macOS PowerPoint放映测试。PowerPoint网页版也是独立环境，不能代替指定桌面应用。

依据：[Microsoft PDF导出](https://support.microsoft.com/en-us/powerpoint/training/save-powerpoint-presentations-as-pdf-files)、[Presentation.Export](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.presentation.export)。

### LibreOffice → PDF → 全页PNG

仅在已安装、宿主允许、候选与输出目录均获授权时使用。以下为未执行的命令示例，不是本包实测报告。把输入、输出与可执行程序换成实际路径；先创建本轮新的输出目录，避免覆盖。程序不在PATH时使用已确认安装路径，不猜路径、不改全局PATH。

Linux／macOS shell（`soffice`实际可调用时）：

```sh
soffice --headless --convert-to 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}' --outdir "render-v001" "candidate-v001.pptx"
```

Windows PowerShell（先将 `$sofficePath` 设为本机实际发现的 LibreOffice 可执行文件路径）：

```powershell
& $sofficePath --headless --convert-to 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}' --outdir 'render-v001' 'candidate-v001.pptx'
```

上例含隐藏页，便于完整检查；按真实页序建立映射，不把隐藏页加入正式口播时长。若另需只含放映页的预览，使用另一输出目录并明确其范围。LibreOffice需要可写的用户配置目录；若现有会话／配置冲突，先记录实际错误。可依官方参数使用本轮独立、获准的`-env:UserInstallation=file:///...`配置目录，但不能关闭用户会话、禁用锁检查或改变全局权限来强行运行。

已有Poppler时，以下命令把PDF全部页面转图，不用`-singlefile`：

```sh
pdfinfo "render-v001/candidate-v001.pdf"
pdftoppm -png -r 150 "render-v001/candidate-v001.pdf" "render-v001/slide"
```

`150`是初始查看分辨率，不是通过阈值；文字细节不足就提高分辨率或放大原PDF。先检查PDF存在且非空，再核对PDF页数、PNG数量与PPT实际页序。文件名数字不能自行替代PPT关系映射。逐页打开检查，带标签的缩略图总览只用于观察整套节奏；PDF／PNG不证明编辑性、动画、媒体或声音正常。

依据：[LibreOffice启动参数](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)、[Impress转换过滤器](https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html)、[PDF导出选项](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html)。Poppler命令以安装版本的`pdftoppm -h`／`pdfinfo -h`复核；本次仅核对了可用工具帮助，未执行PPT转换或渲染。

## 3. 失败时只修失败层

一次失败写清“动作、输入版本、工具版本、实际返回、已产生文件、拒绝／未执行／不确定、下一条件”。先检查是否已有可用结果，再决定重试；输入已纠正、临时故障恢复或替换了实质不同且获准的路径，才有重试依据。同输入同条件重复执行、重复Select、重复像素采样不构成诊断。

不是“失败两次即环境阻塞”：错误可能在素材、编码、页序、播放设置或观察能力。根据证据归因；当前可行路径耗尽或下一步需要新权限／用户输入时停止该项，保留无依赖工作，给一个最小解阻动作。精确报告“无法观察音频”“此渲染器缺字体”等，不笼统说“电脑不支持PPT”。
