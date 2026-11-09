# 新源结构与关键状态一致性

在新源涉及可运动产品、开合、层叠、附着图案/文字，或收到内外面、方向、孔/把手、装饰时段、跨缝图案等反馈时读本页。只替换人物且没有额外产品要求时沿用普通流程；已有同SHA的已核中性事实直接复用。现有母版、素材职责和运行绑定见[生产合同](production-contracts.md)，无需重新建立另一套批准流程。

本页的“源结构模式”把原片可观察的事实变为当前源的合同，不预设物体数量、盒型、机构角度、品牌、颜色或目标设计。源事实随该源复用；本轮目标图案、人物、参考图、假设和候选审核留制作run。安装、维护和生成证据不启动模型生成，也不产生视觉通过。

## 先确定物理面，再配置目标外观

从完整原片及必要相邻原尺寸帧建立稳定product/panel ID。面随物体运动，不随镜头的屏幕左右重新命名；同一零件的内面与外面若可区分，应分别标识。看不见的背面、连接或内部状态保留资料未覆盖，不能由常见盒型或生成图推定。只为本源可见内容和影响本轮目标的必要关系建立检查；必要关系看不清时才记unknown并补证据，不为画外无关部件增加采集要求。

实际需要时记录局部轴`u/v/normal`：轴由该物理面的边和朝外法向定义，面转动时轴随面转动。印刷相对物理面附着，不能为了始终正对观众而漂移、镜像或跨到另一面。是否旋转、折起或被遮挡依据本源动作；不固定使用某个角度或要求每帧屏幕朝上。

先核以下关系，再把用户本轮外观写进目标合同：

| 原片关系 | 需要保留的事实或适用检查 |
| --- | --- |
| 面与内外 | 零件/物理面的稳定ID、可见状态、内外对应；允许印刷的面及明确排除的面 |
| 接缝与连接 | 哪些面相连、真实铰链/折线或分离边；连接约束与图案跨面关系分别记录 |
| 孔与五金 | 穿孔/凹口/把手/金属件的真实类别、归属、连接与遮挡，不能只记为相似的深色图形 |
| 开合与层叠 | 开始、过渡和结束状态；哪一层/部件在何时可见、前后关系及原动作中实际发生的连接变化 |
| 印刷与装饰 | 图案/文字附着的物理面、局部方向、跨缝分配及可见区间；可移动装饰与固定印刷分开 |

原片几何、动作、连接和时序与本轮产品外观同时进入实际生成提示；目标配色或品牌不应吞掉源结构。规则来自`source`、`user`或`target_reference`，写清依据和半开源区间。只在用户实际要求的面、属性和时段覆盖旧规则；不把局部例外推广到全片。

有对称或双端印刷时，分别记录每个印刷单元对应的端部和局部方向；图案、logo与文字作为一个组合随面转动。“对称”不等于字形镜像，也不等于两端文字都朝屏幕正上方。文字位置以实际承载印字的物理面为范围，不能把多片搭接顶面当作一块大盖整体居中。

内面、裁切边与压线分别依据实际源/本次目标，不能由外部配色推断。堆叠时分别核单体轮廓、角数、数量、朝向和层间遮挡；透视和叠放不能产生额外的边或零件。原型/目标是什么形状就核什么形状，不把某片的矩形或固定层数变成通用默认。

首轮试窗优先覆盖本次实际存在的高风险变化，如翻面、压平、遮挡重现、搭接或叠放。先用已有素材；只有必要结构仍有歧义才补对应视图。静态成品通过不能批准尚未覆盖的开合运动，开合正确也不证明图案位置或文字已经满足exact要求。

## 源结构模式：草稿、验证、激活

先完成普通ingest及真实源analysis。使用当前run绑定的运行时，创建草稿：

```text
python scripts/physical_source.py draft --project RUN --product product_1
python scripts/physical_source.py validate --project RUN
python scripts/physical_source.py activate --project RUN
```

也可通过`run_skill.py --project RUN physical_source ...`选择绑定运行时。`--product`可重复，仅用于draft收集本源产品ID；默认草稿为`evidence/physical-source.draft.json`，`--draft`可指定run内另一草稿。示例ID不代表任何特定盒型或默认产品数。

draft只创建待观察骨架：每个产品的`source_interval:null`、空`panels`和`hinges`，顶层空`rules/consistency_checks`；`source_review.status`为pending。Codex实际查看原片后填写产品范围、物理面、连接、规则、必要检查及来源依据。用户不需要手填内部合同。

`source_review`包含`status`、实际观察的`notes`和`capture`字典。capture必须覆盖现有9类：

```text
surfaces, connections, fold_state, artwork, openings,
stacking, occlusion, continuity, text_legibility
```

每项结构为`{status,notes,check_ids}`：

- `observed`：已有实际源观察、非空notes，并列出该criterion对应的有效consistency check ID。
- `not_applicable`：确实不适用，写明本源原因；不能用它代替看不清或缺资料。
- `unknown`：仍有必要关系无法判断，保留未知并补必要证据，不能激活。

只有实际源审查完成后，Codex才填写`source_review.status:passed`及真实notes。validate/activate核当前源SHA、完整实解帧数、已通过的analysis、物理面/规则/区间及capture覆盖；它们不判断图像内容，也不代写观察通过。新源未知项阻止activate；未声明新结构能力/检查的旧式已核源事实保留兼容，不补造历史观察。

activate将有效事实写入`evidence/physical-source.json`，初始化待填目标/物理审核，并合并源所需能力；不会自动批准目标、生成或迁移运行绑定。随后由Codex填写实际目标与素材，在已有任务授权范围内引用真实用户消息完成必要的runtime migrate，再准备/审核受影响输入。无需为这项内部维护重新向用户索取同一制作授权。已受理任务仍用原ID和冻结输入恢复。

本轮使用product参考时，提交前必须有匹配源的已激活物理事实；prepare允许保留pending草稿以便继续独立准备，不表示可以提交。已有不同active事实时activate拒绝覆盖，先保留原制作合同与已受理任务，再按实际范围维护修订；不能删除旧事实凑激活，也不能让两个目录互相遮蔽。后续事实修订会使相关合同/证据失效。

## 把反馈变成有范围的检查

已有`rules`负责当前产品、面、属性和时段；`consistency_checks`选择必须实际对照的源状态。每项包含`id/product/panel/source_interval/criterion/rule_ids/states`，可选`local_axes:{u,v,normal}`和`forbidden_panels`。criterion取上面9类之一。每个state保存`id/source_frame/description`，所选源帧必须属于当前检查及产品的真实范围。

例如，检查某图案在运动前后是否仍附着同一面，可以记录两个实际源状态；不要把示例帧号或描述直接当作观察证据：

```json
{
  "id": "mark_attachment",
  "product": "product_1",
  "panel": "panel_outer",
  "source_interval": [0, 12],
  "criterion": "artwork",
  "rule_ids": ["mark_on_outer"],
  "states": [
    {"id": "before_motion", "source_frame": 0, "description": "The inspected mark on the named physical face before motion."},
    {"id": "after_motion", "source_frame": 11, "description": "The same physical face after its actual source motion."}
  ],
  "local_axes": {"u": "toward the identified right edge", "v": "toward the identified upper edge", "normal": "outward from this physical face"},
  "forbidden_panels": ["panel_inner"]
}
```

这里只展示字段。产品、面、规则和帧均须已在当前源中确认；检查状态不是固定首中尾，也不是每类一律多取几张图。

| 具体反馈 | 应形成的中性检查 |
| --- | --- |
| 图案在翻转时倒向不对 | 核相对该面的局部方向和附着；运动前后、遮挡重现后都核，不用屏幕朝向代替物理面方向 |
| 外部图案跑到内部 | 核稳定内外面ID、允许/排除面；分别看两面实际露出的状态，未露出部分不编造结论 |
| 孔变成装饰或把手消失 | 核开口/五金类别、所属部件、连接和手部遮挡；有遮挡时不能以“看不见”判为移除或保留 |
| 装饰提前出现或后段仍在 | 按源时段记录该物件的出现、附着/脱离及遮挡，区分装饰物和固定印刷 |
| 跨接缝文字断裂、复制或漂移 | 核图案在各真实物理面的分配；检查接缝闭合、运动中与展开后的对应关系，而非只看静态完整字样 |

这些是条件化检查类型，不是新源必须具有的物体或动作。用户要求exact时继续使用原母版严格程度；结构检查不把exact降为近似。

## 当前候选与组装的状态证据

当前候选已登记到reviews后，为有consistency_checks的窗口准备原尺寸证据：

```text
python scripts/factory.py consistency-evidence --project RUN --window-id WINDOW --out candidate-evidence/structure-v1
python scripts/factory.py consistency-evidence --project RUN --final --out candidate-evidence/structure-final-v1
```

输出目录必须为新的run内目录，位于可复用assets/evidence以外。工具按当前source_to_output映射导出实际源/输出状态PNG并生成pending记录；它不选择视觉通过、不凭首尾图批准中间运动。检查头绑定owner范围内的check_digest、当前输出完整签名，以及候选input_digest或最终composition_digest。

导出的`review.json`内容在实际审查后保存到当前记录的`physical.consistency_review`：每项check写实际结论与notes，各state实际看过才写observed及notes。Codex亲看每个状态对应的源/输出原尺寸PNG；相邻状态还须有from/to过渡观察，核整个过渡中面、连接、开口、附着与遮挡的连续性。静态两张图本身不证明连续变化，仍保留完整原速播放和原尺寸风险审核。最终成片要核当前组装和所有适用检查，不能继承旧候选或局部比较run的通过。

图片、映射、源帧、输出帧、当前输入、检查或组装改变后，旧结构证据失效。缺状态、错映射、旧PNG或漏过渡不能用笼统“产品正常”覆盖；结构校验成功也不能自动生成视觉通过。准确JSON与守卫字段以当前脚本返回的pending记录为准。

## 重复失败先补依据

同一物理关系在已改策略的候选中再次失败，或当前原片/参考无法辨识必要关系时，下一次提交前先做资料缺口诊断：

1. 对照实际坏帧和输入，明确是面归属、局部方向、连接、开口、状态时段还是图案跨面对应出错；保存当前候选SHA、范围和假设。
2. 先看已有原片及原始参考的相关视图。能从已有素材确认就补事实/检查，不重复索图；无法确认才集中补必要的内外面、连接、开合中间态或跨缝细节。
3. 明确新增资料解决哪个未知。参考图和导引是模型输入，生成的示意不能自行成为真实结构的证明；不得将补图贴到视频或局部合成修错。
4. 更新受影响的事实、目标或输入并重新审核相关窗口；其他未变的已通过窗口保留。新候选重新核该状态、过渡及接点。

这不是固定次数的质量停止线，也不自动扩大索图、接口切换或用户审批范围。没有新依据时不继续只改措辞重投；仍可完成独立的事实整理、证据准备和模板工作。已有制作/自主审批授权继续适用，只有用户明确要求先审的阶段才增加相应条件。
