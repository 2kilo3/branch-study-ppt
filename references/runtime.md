# 运行要求、编码契约与已测边界

## 两层能力，不把一个库当成整套环境

阅读技能文档不需要Python。可选结构审计、预检和合成测试仅用Python标准库，零pip依赖；不需要`python-pptx`，没有安装器，也不修改全局环境。未装Python只会阻塞这些辅助脚本，不自动阻塞宿主其他工具能完成的PPT工作。

完整制作另需真实可用的来源访问、可编辑PPTX、备注／媒体、全页渲染、中文字体、独立审查和交付能力，按[portability.md](portability.md)逐项映射。`python-pptx`只是一个候选；PowerPoint、LibreOffice或宿主其他能力也可使用，但须分别验证编辑性、备注、媒体、保存和渲染。发现库／应用不等于接口已连通，更不等于放映通过。缺能力时报告具体受影响步骤，不默认要求安装软件。

## 版本与命令

- 静态API下限：Python 3.7，依据包括`subprocess.run(capture_output=..., text=...)`及UTF-8模式；这不是已测试全部3.7及以上版本的承诺。
- 本轮验证（2026-10-22）：Windows，CPython 3.12.10；81 项离线合成测试中 74 项通过、7 项因平台／权限跳过，预检通过。范围与跳过项见 [validation.md](../docs/validation.md)。随包历史文档曾记录 Linux x86_64、CPython 3.12.14 和 3.13.5 的检查，本轮未重新验证这些环境。
- 本轮未验证：macOS、Linux、其他 Python 版本、Codex／Claude Code／DeepSeek harness 安装与发现流程、真实浏览器连接、完整 PPT 任务及桌面放映。Windows 脚本测试不代表跨机器制作验收。

先确认当前宿主实际命令是`python`、`python3`还是Windows的`py -3`，下列`python`替换为该命令；不为此修改PATH。从技能根目录运行：

```sh
python -B -X utf8 scripts/preflight.py
python -B -X utf8 -m unittest discover -s scripts -v
```

预检只读取本包文件、导入标准库／本包模块、探测可选模块位置和PATH命令，并启动同一解释器做内存中的UTF-8管道探针。不联网、不导入／启动第三方应用、不创建测试PPT、不安装、不改变权限或系统环境；不输出凭据、环境全量或本机绝对路径。退出0仅表示本包Python辅助能力就绪；退出2表示解释器要求、文件或探针存在问题。无法启动Python时预检当然不能运行，直接记录该辅助能力缺口。资产“可读”不代表内容、授权或视觉验收通过。

预检列出的浏览器、编辑、渲染、媒体、独立审查及交付能力仍须宿主实际验证；PATH未发现应用也不能证明应用不存在。单元测试在临时目录创建并清理合成文件，不使用用户原稿；不是完整试跑。

## 父子进程都固定UTF-8

审计CLI成功报告和可处理的文件／ZIP／XML／参数错误均在stdout输出单个UTF-8 JSON；分别退出0和2。参数错误的`file`可能为`null`。`--help`是普通帮助文本，不是JSON；解释器启动失败、脚本缺失、操作系统拒绝或管道断开不属于可保证的JSON业务错误。退出0不表示PPT合格。

正常管道／文件输出直接写UTF-8字节，因此不受系统默认编码或继承的`PYTHONIOENCODING=gbk/ascii`影响；不只依赖`-X utf8`。嵌入调用若替换stdout为StringIO等纯文本流，接收Unicode；受限纯文本编码器可回退为等价ASCII转义JSON。字段语义不变。

父进程读取必须显式约定解码，不能以宿主默认`cp936`等编码读取UTF-8。例如：

```python
subprocess.run(
    [sys.executable, "-B", "-X", "utf8", "scripts/audit_pptx.py", "材料🙂.pptx"],
    capture_output=True, text=True, encoding="utf-8", check=True,
)
```

若需要处理退出2的JSON错误，使用`check=False`并检查`returncode`；二进制捕获则用`proc.stdout.decode("utf-8")`。子进程`-X utf8`和父进程`encoding="utf-8"`各管一侧，不能相互代替。无需永久改`PYTHONUTF8`或`PYTHONIOENCODING`。UTF-8模式也不把所有任意旧文件转成UTF-8。

CLI可直接接收中文／emoji路径；若外层shell或调用程序在传参前已经损坏路径，脚本不能恢复。文件重定向保持原始stdout字节时报告为UTF-8；某些shell会先解码再编码原生命令输出，应用上述Python捕获并按UTF-8保存，或核查shell自己的编码规则，不能保证任意shell转码后的文件。

## 运行缓存不等于发行污染

分发包不得含`__pycache__`、`.pyc`、日志、私有路径或测试输出。普通Python导入可能在运行时产生缓存，不等于发行ZIP已夹带缓存，也不等于修改了PPTX。“只读PPTX”不是“所有测试都不写临时文件”。

默认命令使用`-B`，测试启动的子进程也带`-B`；它阻止新字节码缓存，不删除已有缓存。预检另在本进程禁用字节码写入。合成回归会比较全新技能副本运行前后的文件清单和哈希，确认辅助命令未新增缓存／改动包内容。测试输出如需留存，放在技能包外，打包前再次检查；不自动清理用户现有文件。

## v1.2辅助工具的职责

plan_timing.py在没有PPTX时计算条件式时长预算；audit_pptx.py读取候选并给出绑定SHA-256的测量；freeze_review.py按显式输入创建新送审快照，verify只读核对。三个工具均不替代来源、内容、视觉或播放审查。冻结工具有写入行为但不覆盖既有文件，不应称整包所有脚本都只读。用法分别见timing.md和review-control.md。
