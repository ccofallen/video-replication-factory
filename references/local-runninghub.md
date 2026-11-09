# 本地 RunningHub 自定义 H3 工作流

历史 RunningHub 兼容配置（仅用户明确选择云端时使用；当前默认 ComfyUI）使用海外站工作流 `2117403951334162433`。本机连接配置在 `$HOME/ai_video_generation/workflows/runninghub-2117403951334162433/connection.json`，私有 Key 文件路径由该配置指定。使用 `$HOME/ai_video_generation/run-runninghub`；此工作流不能通过内置旧应用的固定节点或标准 H3 接口提交。

已绑定的专属run使用统一入口：`run-skill --project <run> runninghub_workflow <command> <参数>`，由启动器选择实际专属运行时。传入自定义配置时，`--config <包外配置>` 放在 `<command>` 前。profile、prepare-factory、submit和原ID恢复均可从此入口执行；submit的request仍使用实际传输bundle。下文旧入口命令说明相同参数和恢复语义，专属run新增任务采用统一入口。

## 配置与校验

`run-runninghub check` 仅查询工作流，不生成。配置和导出图只在本机工作目录保存；Key 不进入 job、队列、bundle、共享账本请求或专属技能。

节点：视频 `27.video`；Picture 1 是 `51.image`；Picture 2 是 `49.image`；提示词 `263.text`；秒数 `259.value`；画幅/像素量 `252.aspect_ratio` / `252.megapixels`；种子 `397.seed`；最终输出 `364`，24fps。实际输出帧数必须为 5 mod17，完整生成按明确画质数值选择上限：≤1.0最多15秒／345帧，>1.0或未指定最多10秒／226帧。补齐计入完整时长，超过当前上限时在已核动作边界拆分。

导出图中17秒、横屏、品牌/人物/音频编辑提示词都是旧示例参数，不代表本次用户要求。实际提示词使用工厂六段编译结果。画幅从本次派生视频的实际展示尺寸确定；模型、LoRA、采样参数保留原图设置。

## 由 Codex 完成的制作步骤

1. 按原技能 `factory ingest` 分析源视频，真实核对角色、镜头、动作、原图身份和替换范围。制作run留在项目目录；仅安装或配置时不索取素材、不启动生成。
2. 在run中调用 `run-runninghub profile --project <run> --seed <本候选种子> [--instance-type plus]`。它复制私有工作流快照并输出 `runninghub-workflow` profile。将输出作为本次 `job.json.profile`；按真实任务记录授权，不把本次Key放进job。默认实例沿用技能的plus；不得自动升级机器档位。
3. 使用正常 `factory prepare`，由Codex审阅源事实、提示词和时间投影后记录语义/投影审批。新profile自动按24fps与5 mod17规划，不套固定5秒。新身份/后端/风险仍需代表性试窗，后续批次通过 `pilot-promote` 解锁。本图需要两条真实图片输入，不能复制一张人物图填槽。按 [素材职责合同](production-contracts.md) 显式声明两条identity/product/background/continuation输入，真实上传顺序对应Picture1/2；一个人物可以有两条用途不同或明确同人多角度的资料，人物仍只有一个。只有一条实际输入时选择匹配的单图工作流，或补齐本次明确需要的真实素材，不虚构第二个人物或用途。
4. `run-runninghub prepare-factory --project <run> --window <ID>` 从已准备的工厂队列生成传输bundle。检查bundle对应的是本次已审批输入，使用打印的digest提交：`run-runninghub submit --request <bundle路径> --approve-digest <digest> --production-request <实际用户制作要求记录>`。这些记录由Codex维护，不要求用户手填。
5. 提交会再次检查当前job授权、队列输入、语义/投影审批、pilot范围、文件字节、两条实际图片的顺序/节点、帧数/时长/画幅和完整工作流。共用工厂的私有共享账本和 `default` 账号上限3。新付费请求fresh上传，任务回执即刻保存；提交未知会挡住所有新请求。
6. `run-runninghub recover --attempt <attempt>` 仅查询/下载原任务，保留轮询退避；需要持续执行时由Codex按退避再次调用。断线后未知提交先从RunningHub任务历史找到原taskId，再使用 `recover --attempt <attempt> --task-id <原ID>` 对账。错误/未核实ID不能解除UNKNOWN。不要更换window ID重投未知任务。此适配器不自动重试已失败生成；修复后按新候选和当前制作授权处理。
7. 下载结果必须来自输出节点364；随后正常调用 `factory inspect-candidate` 和 `candidate_review` 检查完整输出时钟、源动作、身份、风险区和原速。实际通过后做pilot推广/批量候选；失败仍按原技能修复。导出图的生成音频仅用于候选，最终由工厂按源所有权组装并保留原音轨（实际用户另有音频要求时单独处理）。
8. 专属技能继续使用工厂 `build-skill`；private-workflows、rh-requests、连接配置和Key留在run/本机。新的工厂会清除模板plan内该私有profile override；新run重新选择生成后端和当前身份。

`prepare` 是独立离线诊断命令，它生成的未绑定bundle不能提交，避免绕过工厂审核。安装验证只证明连接与离线流程；机器显存、节点加载和真实人物生成效果仍需实际制作试窗。

官方接口：
- https://www.runninghub.ai/runninghub-api-doc-en/api-425761093
- https://www.runninghub.ai/runninghub-api-doc-en/api-425761094
- https://www.runninghub.ai/runninghub-api-doc-en/api-425761033
- https://www.runninghub.ai/runninghub-api-doc-en/api-425761034
