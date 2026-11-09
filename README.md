# 视频复刻工厂

**版本 v1 · 维护者 [ccofallen](https://github.com/ccofallen)**

本项目基于 [T8mars/video-replacement-skill-factory-T8](https://github.com/T8mars/video-replacement-skill-factory-T8)，保留原项目来源与作者资源，在已有制作流程上加入物理一致性、关键状态证据、混合素材与可靠恢复改进。详见 [来源说明](ORIGIN.md)。

> **默认使用已有的本地／局域网 ComfyUI H3 原生 API，无需 RunningHub Key。** 配置与 API 图留在技能包外，见[本地接入说明](references/local-comfyui.md)。用户明确使用 RunningHub（RH）时仍需配置自己的 API Key。
>
> 注册入口（按作者提供的站点分类）：
> - **海外（无审核）**：[RunningHub 海外站注册](https://www.runninghub.ai/?inviteCode=rh-v1121)
> - **国内（强审核）**：[RunningHub 国内站注册](https://www.runninghub.cn/?inviteCode=rh-v1121)
>
> 实际账号权限、可用模型和审核要求以平台当前规则为准。注册入口不会自动切换脚本的接口地址。

**技能标识：** `video-replication-factory`  
**版本：** `v1`  
**专属维护仓库：** [ccofallen/video-replication-factory](https://github.com/ccofallen/video-replication-factory)

给 Codex 原视频、人物资料和本次要求，工厂组织源分析、人物替换、完整窗口修复、实际验收与组装，并为每条原片建立带中文名称的独立专属技能。模板保存中性源事实；本轮人物、品牌、候选、授权、审批和后期配置留在制作run。

默认使用用户已有本地／局域网 ComfyUI；RunningHub 只在明确选择时使用。新身份与新输出需要当前试窗和实际画面验收。技术回执、离线测试、安装和模板升级都不证明新影片或GPU画面已经合格。

## v1：从新源建立结构与状态证据

结构产品制作先读[源结构与一致性](references/object-consistency.md)：从实际原片建立物理面、内外关系、局部方向、连接、开合/层叠及印刷允许范围，保留未知并补必要视图。关键状态检查绑定当前源与输出的原尺寸图和过渡观察；导出证据保持pending。重复同类结构错误时先补资料依据，再修改受影响完整窗口，不靠重复措辞或贴片修补。

v1包含源结构与状态审核、运行绑定和混合素材合同。本版离线工具与回归不代表新的生产影片或GPU画面通过。

## 按本轮范围执行生产合同

详细字段与命令见 [生产合同](references/production-contracts.md)。这些能力按适用条件使用；没有要求样图/试听审核时，不增加阶段审批；没有授权后期时，保留原音轨与正常组装流程。

1. **运行绑定。** 新run记录实际技能、源SHA、运行时摘要和所需能力，准备、提交前、审核与组装检查当前绑定。旧run保留诊断与原ID恢复；新增生成前明确采用或迁移运行时，统一启动器选择绑定的专属版本。
2. **素材职责。** 人物A/B与模型Picture槽位分开；输入分别声明identity、product、background、continuation及源区间/产品/角色。实际提示词、上传顺序和图节点一致。同人多图不增加人物，旧式仅人物输入保持兼容。
3. **授权后期。** 基础画面通过后，可执行明确授权的宣传文案与音轨调整，保存文字大小写、字号、位置、颜色、时段、安全区及音乐文件/截取/增益/淡变。仅允许声明字幕层和编码变化；人物、产品和动作错误仍重新生成完整窗口。
4. **条件审批。** 只有真实用户要求先样图/试听审核时建立阶段条件。批准绑定当前资产SHA、范围、消息与批准人；新设计只撤销相关旧批准。用户明确授权自主审批时在授权范围内执行。
5. **升级不降级。** 工厂版本、运行时版本/摘要和源专属revision分开。下一版大于历史、移除记录与安装目录中最大revision；删除旧版不重用编号。保留源证据与专属入口/初始化/守卫能力，缺能力拒绝升级。
6. **图案母版。** 声明物理面、特征、锚点、状态对应和exact/structural/approximate严格程度；exact未满足保持failed或pending。某片的机构事实只来自该片源证据。
7. **可见身份。** 对照当前参考覆盖与源画面可见部位，分别核手臂、腕、掌、指、袖口比例与接触；画外脸不可评估，不把性别比例成见写成身份要求。
8. **交付状态。** 基础技术、基础视觉、预览、已知问题、用户暂时通过和正式通过分开。硬要求未解决阻止正式master_ready；例外接受须真实用户消息、具体问题与当前输出绑定。

历史维护使用离线合同、故障与合成媒体回归。具体通过数量、全套集成结果和安装包验证以该次交付报告为准；本版能力说明不声称已生成或验收新的生产影片。

## 使用与运行绑定

在Codex中调用 `$video-replication-factory`，提供原视频与本轮人物资料；也可用“视频复刻工厂”描述任务。入口见 [SKILL.md](SKILL.md)，源分析/制作流程见 [workflow.md](references/workflow.md)，既有JSON字段见 [schemas.md](references/schemas.md)。角色对调只改变身份映射，保留源位置、动作承担者和时序。

新run由ingest或专属模板instantiate绑定实际运行时。准备与执行优先使用统一启动器：

```text
python scripts/run_skill.py --project RUN factory prepare
python scripts/run_skill.py --project RUN comfy_runner tick
python scripts/runtime_binding.py diagnose --project RUN
```

如果已安装同名shell入口，可使用 `run-skill --project RUN factory prepare`。`--skill SKILL`可指定已安装技能ID或实际目录，但仍须满足run绑定；不能借此跨版本绕过守卫。旧run采用/迁移须引用已有的真实用户授权消息，不能因为软件更新自动重新提交已受理任务。

源片分段按真实镜头与已核自然动作阶段，不设固定5秒。明确数值 `profile.quality_level≤1.0` 时单次完整生成最多15秒；`>1.0`或未指定最多10秒，不从像素推断档位。context、preroll、慢速扩展和尾部补齐都计入上限。帧网格依据当前实际API图；无替换目标的镜头直接保留。见 [生成规则](references/generation-policy.md)。

## 后端与恢复

本地接入见 [local-comfyui.md](references/local-comfyui.md)。检查用户提供的API图、真实输入/输出和节点schema，保留模型/LoRA选择，不猜UI控件顺序、不安装模型、不把私人工作流封进模板。同服务共享一个串行执行位，等待外部队列；未知提交先对账，已知prompt_id只恢复查询与下载。

RunningHub按 [backends.md](references/backends.md) 与 [local-runninghub.md](references/local-runninghub.md) 配置自己的权限、Key和包外共享账本。新付费请求使用新上传句柄；同账号最多3个在途生成，正常批次以3个为目标。只剩1～2个问题窗时，准备3个有实质差异且分别已审批的方案；全部通过即停止新增。忙队列等待，不为缩短等待重复提交原taskId。

API Key、连接配置和账本存放在包外私有位置，使用脚本支持的 `--key-file` / `--ledger` 参数或私有连接文件。账号注册入口不自动切换接口地址；接口存在也不证明当前账号已开通权限。仓库不提供默认Key。

## 审核与修复

当前源、身份、实际后端及风险路线先试窗；旧profile的历史成功不代替新身份验收。源帧有且只有一个输出owner，context和补齐不进入成片。完整输出看到真实末帧；脸、遮挡、手袖接触、产品各物理面与接点按原尺寸核对，实际1×连续观看另行记录。

已通过且签名未变的窗口冻结；改动只撤销相关审批，全源与owner计划仍整体校验。重复失败先核引用、构图、身份范围、真实动作阶段与实际时钟，再换策略重生成完整窗口。接点回归也重做相关完整窗口，不用混合平滑、贴脸、产品贴图或局部蒙版掩盖错误。旧face_swap/face_detail修改入口保持禁用。

默认按源PTS、帧数、画幅/旋转/SAR、颜色与全部原音轨组装，完整解码和独立RGB/PTS证明不能由短样片或编码正常退出替代。后期仅在本次明确授权时按 [受限后期合同](references/production-contracts.md) 执行；原音轨默认检查不放宽，授权替换时核目标音轨且独立有声听检。

媒体处理可后台进行；用户要求后台时不操纵桌面播放器。证据准备、技术、视觉与播放记录分别保存，未知保留pending。身份独立回对用户原始资料；衣服、发型或动作改变不证明换对人。当前参考只覆盖手或上肢时，不评估画外脸。

恢复、缓存、费用核对见 [production-reliability.md](references/production-reliability.md)，失败与验收规则见 [quality-and-repair.md](references/quality-and-repair.md)；新源结构和关键状态见 [object-consistency.md](references/object-consistency.md)。费用只按保存回执去重核算，三并发主要减少等待，情景估计不能当作已实测省币率。

## 创建与升级专属技能

制作期间可保存 `draft`，不声称影片通过。正式ready必须满足当前最终记录、适用生产合同与真实用户最终接受；暂时通过保留为provisional，不升级为正式master。

```text
python scripts/factory.py build-skill --project RUN --skills-root SKILLS --status draft --display-name "原片内容名·换角复刻"
python scripts/factory.py build-skill --project RUN --skills-root SKILLS --upgrade-runtime
python scripts/factory.py version-list --skills-root SKILLS --source-sha256 SOURCE_SHA256
python DEDICATED_SKILL/scripts/factory.py instantiate --skill DEDICATED_SKILL --project NEW_RUN
```

源专属包包含原片、中性源分析/计划/证据、自足运行时、中文内容名与可安装ZIP；身份、生成候选、当前目标/审核、私人连接/工作流、凭据和账本不进入模板。新run身份和profile为空，生成授权为false。不同原片使用独立模板；同源按历史最大revision递增，版本列表与移除记录只提供事实，不执行删除。升级保留专属源能力，不用共享脚本覆盖丢失源事实。

## 安装与验证

可从 [Releases](https://github.com/ccofallen/video-replication-factory/releases/latest) 获取已发布安装包，或使用当前交付的工厂ZIP；核对包内meta/manifest版本。解压后的 `video-replication-factory` 文件夹可交给Agent安装。

需要Python3.10+、PyAV、Pillow、NumPy与PATH中的ffmpeg/ffprobe，依赖列在requirements.txt。媒体命令支持 `--deps`；Windows已证实的解码问题可按文档使用 `--scalar-cpu`。

```bash
git clone https://github.com/ccofallen/video-replication-factory.git ~/.agents/skills/video-replication-factory
python3 -m pip install -r ~/.agents/skills/video-replication-factory/requirements.txt
```

```powershell
git clone https://github.com/ccofallen/video-replication-factory.git "$env:USERPROFILE\.agents\skills\video-replication-factory"
python -m pip install -r "$env:USERPROFILE\.agents\skills\video-replication-factory\requirements.txt"
```

离线回归保留既有工厂、runner、审片、媒体恢复、本地后端及既有合同检查，并包含源事实激活、状态证据和实际请求集成测试。新测试可单独运行：

```text
python -m unittest discover -s scripts -p test_media_references.py -v
python -m unittest discover -s scripts -p test_runtime_binding.py -v
python -m unittest discover -s scripts -p test_run_skill.py -v
python -m unittest discover -s scripts -p test_production_policy.py -v
python -m unittest discover -s scripts -p test_postproduction.py -v
python -m unittest discover -s scripts -p test_upgrade_lifecycle.py -v
python -m unittest discover -s scripts -p test_physical_contract.py -v
python -m unittest discover -s scripts -p test_v5_integration.py -v
python -m unittest discover -s scripts -p test_physical_source.py -v
python -m unittest discover -s scripts -p test_consistency_review.py -v
```

媒体环境、全部旧回归、实际集成和新解包实例化须按交付验证报告检查；单个模块通过不替代全套发布检查。离线验证不调用新生产生成，不会自动写视觉或听觉通过。

## 后续维护与固定发布

本仓库发布视频复刻工厂及安装包，维护目标为`ccofallen/video-replication-factory`。manifest与 [publish-policy.json](https://github.com/ccofallen/video-replication-factory/blob/main/publish-policy.json) 共同限定发布文件；源专属素材、专属包与生产项目留本地。维护规则见 [AGENTS.md](AGENTS.md)。

```text
python tools/sync_skill.py --source FACTORY_DIRECTORY
python tools/verify_publish.py --staged
git config core.hooksPath .githooks
```

按核对过的具体文件暂存，扫描全部待推提交并核对固定仓库。ROADMAP.MD任意大小写/目录、凭据、模型、输入图/视频、候选/成片、运行日志和私有账本均禁止发布。

## 原项目作者与资源

以下链接由 T8 提供，作为社媒与资源入口：

| 资源 | 链接 |
| --- | --- |
| B站 | [T8 的 B站空间](https://space.bilibili.com/385085361) |
| YouTube | [T8star-Aix](https://www.youtube.com/@T8star-Aix/) |
| API 服务入口 | [API 注册入口](https://api.seedance.nz/sign-up?aff=5f4w) |
| 免费画廊 | [贞贞免费画廊](https://www.openzhenzhen.com) |
| 在线 AI 应用 | [RunningHub 应用主页](https://www.runninghub.ai/zh-cn/user-center/1907375370302308353/userPost?inviteCode=rh-v1121) |
| ComfyUI 整合包 | [夸克网盘整合包](https://pan.quark.cn/s/264edb7e36bd) |
| Hugging Face | [t8star](https://huggingface.co/t8star) |

工厂当前的生成后端按本次 `job.profile` 和接口文档配置；资源列表中的 API 注册链接是作者提供的独立资源入口。

## English guide: scoped production contracts

Version v1 binds a run to its actual source-specific runtime and separates human roles from model image slots. Identity, product, background and continuation inputs have explicit scopes and authority. Conditional stage gates apply only when requested; exact artwork masters cannot be silently relaxed. Visible identity checks use current reference coverage and actually visible parts.

Authorized caption/audio postproduction starts after the base film passes. It preserves the source clock/canvas and proves the allowed rendering/audio chain; actual visual and audible listening reviews remain separate. Person/product patches stay disabled. Template revisions increase above all historical and removed revisions while preserving source facts and capabilities. Offline checks and template installation do not approve a new film or GPU result.

It also adds source-first physical authoring and state-specific native evidence. Unknown source structure must be resolved from actual views; evidence export never approves a state or transition. Repeated structural failures trigger a review of missing input views before another generation. Offline validation does not establish production movie quality.
