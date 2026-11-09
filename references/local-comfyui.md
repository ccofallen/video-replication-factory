# 默认本地／局域网 ComfyUI 后端

适用于使用者已有可运行的 H3 模型、节点与 **API 格式工作流**。默认沿用已配置的 ComfyUI 原生 API；只有用户指定时使用 RunningHub。本地路径不需要 RH Key，不安装模型、不寻找其他工作流、不改使用者的原始工作流。1.4.0 的维护使用离线和模拟 HTTP 验证；后续本地实测已复现并修正数值类型导致的任务恢复误判。每个新工作流与身份仍需真实试窗和原尺寸、原速验收。

## 已配置的局域网 H3 工作流

本机连接保存在技能目录外的 `$HOME/ai_video_generation/private/comfyui/connection.json`。读取 `url`、`workflow_path`、`workflow_sha256` 后校验原图字节。该配置指向用户提供指南中的服务器，不能换成调用设备的 localhost；无需 API Key。配置缺失时才询问实际地址与同工作流 API 导出，不安装模型或修改服务器。通用技能／新专属包只带适配代码，不带此连接文件和原图。

运行脚本使用 `$HOME/ai_video_generation/run-skill`。为每个人数路由生成独立、run内的 API 图和 profile（以下 `<API图>` 与 `<服务URL>` 取自连接配置）：

```text
run-skill comfy_workflow h3-profile --workflow <API图> --url <服务URL> --identity-slots 1 --quality-level <用户明确画质数值> --project <run> --workflow-out local/h3-one.api.json --out <run>/local/h3-one.profile.json
```

把生成的 profile 对象赋给新run的 `job.json.profile`；混合人数镜头分别生成匹配人数的图，填相应 `plan.windows[].profile_override`，每次使用不同 `--workflow-out` 和 `--out`。命令拒绝覆盖已有图或配置，不更改 job、授权或审批；已有run换后端后重新 `refresh-plan`／`prepare` 并审核受影响输入，已受理旧任务仍按原 ID 恢复。

该适配器针对已提供的原生 H3 API 图：265为 MiniMaxH3ReferenceToVideo，397为 sampler seed，364为最终 VHS saver。动态建立1…9个 LoadImage 和一个 VHS_LoadVideo，把当前上传返回路径依序接到 `ref_images.ref_image_N`／`ref_videos.ref_video_0`；保留模型、LoRA、CFG、步数和 SelfLift 配置。图片决定身份，视频决定源动作与镜头，默认不把参考视频音轨送进模型，最终仍组装原片全部音轨。多角度图按工厂当前身份派生策略处理，不自动增加角色槽位。

本图固定24fps，生成帧满足 `17n+5`。明确 `profile.quality_level≤1.0` 时完整生成最多15秒、网格内最多345帧；>1.0或未指定时最多10秒、226帧。5秒对齐为124帧；362帧和243帧分别超出15秒和10秒上限。参考视频加载帧数现在绑定当前完整generation_frames，不固定截为240帧。输出宽高必须为32的倍数；源画幅不满足时先明确并审核生成投影，再把 profile 的 width／height 运行绑定改为对应显式 `parameters`，记录实际画幅与信息损失，不静默裁切或拉伸。

节点校验支持当前实际 schema 的 COMBO、COMFY_AUTOGROW_V3、COMFY_DYNAMICCOMBO_V3 及 VHS 当前格式附属控件。动态名称、连续索引、数量、链接类型、已选分支及数值范围均检查；未知动态形式仍拒绝。上传后才重新读取 `/object_info`，因此文件枚举应含本次服务返回的名称。下载只取成功历史中364.gifs实际 MP4，不猜结果路径。真实测试及身份质量分别报告。

## 检查与配置

使用本次明确提供或已明确复用的 API 工作流；缺少工作流或服务地址时集中询问必要信息。已有制作授权持续有效，不为本地接入重复要求批准生成。纯研究、安装与维护不启动生成；用户明确要求 API 测试时，可执行最小测试并保存任务 ID 和结果，不据此批准人物画面。

```text
python scripts/comfy_workflow.py inspect --workflow <用户提供的API工作流.json> --url http://127.0.0.1:8188 --out <新的检查报告.json>
```

`--url` 只读 `/object_info`；服务离线时省略该参数，可检查图与字面控件，也可用 `--schemas <已获取的object_info.json>`。报告不会激活配置，不会上传素材，不会提交执行。UI 格式要求同一工作流的 API 导出，不能猜测 widgets 顺序；API 图中仍不支持的动态节点须完成明确适配，重复导出不能代替适配。保留原模型、LoRA、采样器与步数；仅根据本次选择填写实际存在的字段。

在新制作 run 的 `local/workflow.api.json` 保存该文件的副本，原文件保持不动。`job.json.profile` 示例（节点和字段仅是结构示例，必须替换为实际检查结果）：

```json
{
  "kind": "local-comfyui",
  "url": "http://127.0.0.1:8188",
  "workflow_path": "local/workflow.api.json",
  "workflow_sha256": "使用检查报告中的完整SHA256",
  "bindings": [
    {"source": "prompt", "node_id": "10", "input": "text"},
    {"source": "video", "node_id": "11", "input": "video"},
    {"source": "reference", "index": 0, "node_id": "12", "input": "image"},
    {"source": "frames", "node_id": "13", "input": "num_frames"},
    {"source": "fps", "node_id": "13", "input": "fps"},
    {"source": "output_prefix", "node_id": "20", "input": "filename_prefix"}
  ],
  "output": {"node_id": "20", "field": "gifs", "index": 0},
  "extra_output_node_ids": [],
  "parameters": [],
  "limits": {
    "identity_slots": 1,
    "fps": ["24"],
    "frame_grid": {"step": 17, "offset": 5, "minimum": 22}
  }
}
```

`bindings` 指向图中未连接的真实字面输入，不支持嵌套字段猜测。必备 prompt、video、frames、fps、output_prefix；参考图 index 从0开始，必须恰好覆盖当前图的 `identity_slots`。同一张参考图可绑定多个输入。窗口人数与图槽位须一致，单/双人混合时使用各自明确的 `profile_override`，不能重复图片填满槽位。`parameters` 如需调整，逐项使用 `node_id/input/value`，不能与运行绑定覆盖同一字段。

为已有窗口选择不同工作流时，同时按该图能力调整 `generation_frames`、`generation_fps` 和 `duration=frames/fps`，再运行 `factory.py refresh-plan` 重建源映射；仅改 `profile_override` 不会自动重算时钟。源owner及已核动作边界保持，修改后的输入重新完成当前审核。

可选运行值还包括 seconds、width、height、aspect_ratio、seed。width/height 来自源展示尺寸；aspect_ratio 包含源 SAR。节点可接受的数值和枚举由当前 `/object_info` 验证，不能以字段名推断语义。需要其他路径或复合媒资清单的自定义节点须开发经验证的适配器，不能伪装为已支持。

帧率和网格由当前实际工作流决定，示例的24fps与 `17*k+5` **不是通用默认值**。也可用正整数 `frame_counts` 列表替代 `frame_grid`，两者互斥。完整派生输入连同缓冲、上下文、慢速扩展和补帧须满足当前明确画质档位的15／10秒上限。短镜头选择足够的最小支持帧数；长连续镜头按已核自然动作阶段分窗。本地生成窗及其上下文不跨真实切镜，最终仍按原源逐帧 PTS 组装。没有目标人物的镜头原样保留，不受生成时长上限限制。

## 准备、执行与恢复

按工厂公共流程完成源分析、身份观察和 `factory.py prepare`。实际审过语义与时间投影后才记录对应审批。工作流字节、绑定、限制、参数和媒体一起进入当前输入摘要；改变任何一项后重建、重审对应输入。

```text
python scripts/comfy_runner.py tick --project <制作run> --ledger <所有本地项目共用的私有comfy.sqlite>
python scripts/comfy_runner.py status --project <制作run>
python scripts/comfy_runner.py recover --project <制作run> --url http://127.0.0.1:8188
python scripts/comfy_runner.py select-output --project <制作run> --attempt <原attempt> --selection <选择记录.json>
python scripts/comfy_runner.py stop --project <制作run>
python scripts/comfy_runner.py resume --project <制作run>
```

默认账本为 `$CODEX_HOME/private/video-replacement-skill-factory/comfy.sqlite`，未设置 CODEX_HOME 时用用户目录 `.codex`。所有同服务项目使用同一账本，显式 `--ledger` 时所有命令保持一致。localhost、127.0.0.1、[::1]同端口共享一个执行位。支持 loopback 与显式 RFC1918 IPv4 局域网 HTTP（10/8、172.16/12、192.168/16）；不同局域网 host/port 分别串行，调用时统一使用连接配置中的同一地址。无代理、重定向、URL 凭据、公网地址或 DNS 别名；不清空队列，不打断别人的执行。外部队列非空时等待下次 tick。

`tick` 执行一次查询、恢复和至多一次新提交。Agent 持续监控并按需要再次调用，正常长采样及历史暂缺不当作失败。新路由先生成已授权试窗，实际身份、构图、动作与时钟通过后才将该路由的质量证据提升为 case-verified，再扩批。RH 的同账户3并发不套给本地；本地直到输出下载并完整解码才释放串行位。

每次提交以新 attempt 上传素材，使用服务返回的真实名称。当前官方 `/upload/image` 可保存视频字节，但 H3 自定义读取节点是否接受该输入仍需试窗验证。实际提交图保存在 run 的 `local_submissions/`，prompt_id 和恢复信息保存在私有账本。

- **响应丢失/未知提交**：保留执行位，按 attempt UUID、client_id 和完整提交图与队列/历史唯一对账。未匹配或多匹配时保持 UNKNOWN；队列空、服务重启或历史被清理均不能证明没有提交，不能重投。
- **已有 prompt_id**：核对历史的原 attempt 和提交图，原 ID 查询和下载，不重新上传或生成。有效 prompt_id 同时附带部分 node_errors 仍是已受理任务，先恢复原 ID。
- **上传/准备失败**：明确尚未调用 `/prompt` 才记录 PREPARATION_FAILED 并停止新增。修复原因后 resume 可以用同一输入建立新 attempt，旧记录保留。FAILED 与 UNKNOWN 不获得该重投许可。
- **执行失败**：停止该服务新增，保留记录，诊断后在独立候选中修改有实质差异的输入并重审。resume 本身不会重复同输入的失败任务。
- **下载失败或输出映射不清**：原 ID 和成功历史保持，完整解码后才原子保存候选；不会把多视频、预览图片、越界索引或损坏文件视为完成。`recover` 不读取新 queue，不执行新的生成，适合当前配置已变更后的历史恢复。

输出选择记录包含 `{"output":{"node_id":"原saver节点","field":"gifs","index":1},"notes":"实际查看成功回执后选择此文件的依据"}`。`select-output` 只允许在原成功待下载任务、原saver及其实际文件内重选，不改变提交图或制作输入。新选择使用带选择摘要的候选路径，保留崩溃前可能已保存的旧文件；随后 `recover` 补下载并重新审片。

下载完成只证明文件完整。随后调用 `factory.py inspect-candidate`、完整输出时钟/原尺寸连续帧证据工具，实际完成身份、遮挡、道具、动作、原速和接点验收，再组装与核全片。任何本地技术成功都不自动通过视觉检查。

## 专属技能与证据范围

ComfyUI 校验 FLOAT 控件时可能把提交图里的 `24` 改成 `24.0`。恢复比较允许数值完全相等的整数／浮点数表示变化，仍严格核对 UUID、client_id、完整图结构和其他值；不放宽数值误差，不把字符串或布尔值当数字。该情况只恢复原任务，不重新提交。模型节点实际报错时仍保存原 ID 和失败回执，修因并建立有依据的新输入版本后再执行。

Windows VideoHelperSuite 的相对 subfolder 可含反斜杠。下载前统一为 `/`，再执行上级目录、绝对路径、盘符、文件名及输出类型检查；不使用返回的 fullpath 读取本地文件。已成功任务发生这类下载兼容问题时，从持久回执恢复原结果，不重新生成。

新专属技能携带通用本地适配器及本说明，**不携带本次私人工作流、本机路径、模型配置、服务记录或人物图**。新 run 的 profile 和制作授权仍清空，按本次环境选路；原源事实与时间轴可以复用。

本次设计参考 [gosick233-cloud/h3-video-replace](https://github.com/gosick233-cloud/h3-video-replace/tree/961847e484bc06df4f615db88d72b1e4b610ed13)，采用独立实现，保留工厂完整验收与成片交付合同。接口依据 [ComfyUI 官方服务路由](https://docs.comfy.org/development/comfyui-server/comms_routes)。详细20轮研究记录留在本地维护目录，未发布私人研究及运行数据。

画质数值由用户明确指定，不从当前画幅反推；未指定不传--quality-level并按10秒。规则与重新生成限制见 [generation-policy.md](generation-policy.md)。
