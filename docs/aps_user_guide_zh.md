# Injection APS 使用手册

## 1. 文档目的

这份文档说明当前已经落地到 `injection_aps` app 里的 APS 一期功能应该怎么用。

重点说明 3 件事：

1. 现在系统里已经实现了什么。
2. PMC、Sales、Production、Warehouse 实际应该按什么顺序操作。
3. 每一步会生成什么 APS 数据和下游执行单据。

这份手册只描述当前代码已经实现的能力，不把二期/规划中的功能当成现成功能来写。

---

## 1.1 中文界面说明

`Injection APS` 已补齐本模块自己的中文翻译，页面、Workspace、表单标签、状态值和大部分异常术语都会按中文显示。

如果你看到少量历史数据仍然是英文，通常是因为这些记录是在翻译补齐之前生成的。处理方式如下：

1. 历史异常记录可在 `APS Planning Run` 或 `Release & Exception Center` 里执行一次 `Rebuild Exceptions`
2. 历史排程结果建议重新执行一次 `Run Planning`
3. 新生成的 APS 数据会优先按当前中文词条落地

---

## 2. 当前 APS 的定位

当前 `Injection APS` 是一个独立 app，定位是“计划层”和“排程建议层”，不是现场执行层。

它的职责是：

1. 承接客户排期版本。
2. 汇总需求池。
3. 计算净需求。
4. 生成 APS Trial Run。
5. 产出机台级排程建议。
6. 经过审批后同步到现有执行层。
7. 只释放短期窗口的工单。
8. 集中展示异常和插单影响。

它不会替代你们现有的：

1. `Delivery Plan`
2. `Work Order Scheduling`
3. `Work Order`
4. `Job Card`
5. `Plant Floor`
6. `Workstation`
7. `Mold`

也就是说，APS 负责“先算、再审、再下发”，执行还是走你们现在已经在跑的对象。

---

## 3. 当前版本已实现的模块

当前版本已经可以使用的模块有：

1. `排期导入与版本对比`
2. `需求池重建`
3. `净需求重算`
4. `APS Run Trial`
5. `APS Run 审批`
6. `排程结果查看`
7. `同步到 Delivery Plan / Work Order Scheduling`
8. `短期窗口工单释放`
9. `异常重算`
10. `插单影响分析`

当前版本还没有做完或没有开放的能力有：

1. 真正拖拽式甘特编辑
2. 可视化审批流页面
3. 复杂多场景模拟对比
4. 自动采购下单
5. 全自动冻结区审批门户
6. 专门的“紧急需求录入”页面

所以现场应按“半自动计划”来用，而不是把它当成全自动优化器。

---

## 4. Desk 入口

安装成功后，Desk 里会有 `Injection APS` Workspace。当前主要入口有 5 个：

1. `Schedule Import & Diff`
2. `Net Requirement Workbench`
3. `APS Run Console`
4. `Machine Schedule Gantt`
5. `Release & Exception Center`

除此以外，也可以直接从列表或表单打开这些 Doctype：

1. `Customer Delivery Schedule`
2. `APS Schedule Import Batch`
3. `APS Demand Pool`
4. `APS Net Requirement`
5. `APS Planning Run`
6. `APS Schedule Result`
7. `APS Exception Log`
8. `APS Release Batch`
9. `APS Machine Capability`
10. `APS Mould-Machine Rule`
11. `APS Color Transition Rule`
12. `APS Freeze Rule`
13. `APS Settings`

---

## 5. 正式使用前的准备

### 5.1 必配基础

在第一次正式跑 APS 之前，建议先确认下面这些数据：

1. `APS Settings` 已维护默认公司、计划视窗、释放视窗、冻结天数。
2. `APS Settings` 里的字段映射已经对应到你们现场真实字段。
3. `APS Machine Capability` 已有机台能力数据。
4. `APS Mould-Machine Rule` 已配置关键产品或模具的优选机台关系。
5. `APS Color Transition Rule` 已配置关键颜色切换规则。
6. `Item` 已有默认 BOM，或者至少能通过默认 BOM 找到生产 BOM。
7. `Plant Floor` 上的 WIP / Source / FG / Scrap 仓库字段有值。
8. `Workstation`、`Plant Floor`、`Mold`、`Mold Product` 的主数据可用。

### 5.2 字段映射

APS 不把你们现场字段名写死在代码里，而是通过 `APS Settings` 配。

当前默认映射包括：

1. `Item.custom_food_grade`
2. `Item.custom_is_first_article`
3. `Item.color`
4. `Item.material`
5. `Item.safety_stock`
6. `Item.max_stock_qty`
7. `Item.min_order_qty`
8. `Workstation.custom_production_risk_category`
9. `Scheduling Item.custom_workstation_risk_category_`
10. `Plant Floor` 上默认仓库字段

如果现场字段不是这些名字，要先在 `APS Settings` 改掉，再跑计划。

### 5.3 机台能力

当前 APS 排程主要依赖 `APS Machine Capability`。

安装或迁移时，系统会尝试从 `Workstation` 自动回填一批机台能力数据，但正式上线前建议 PMC 或工程人员再核一遍这些字段：

1. `workstation`
2. `plant_floor`
3. `machine_tonnage`
4. `risk_category`
5. `hourly_capacity_qty`
6. `daily_capacity_qty`
7. `queue_sequence`
8. `machine_status`
9. `max_run_hours`
10. `is_active`

如果 `hourly_capacity_qty` / `daily_capacity_qty` 没配，APS 会退回用默认产能估算。

### 5.4 模具与物料

当前 APS 会优先从 `Mold` / `Mold Product` 里找产品默认模具，并读取：

1. 模具吨位
2. 输出穴数 / 输出数量
3. cycle time
4. mold status

如果 `Item` 上没有颜色或材料，APS 还会尝试从 `Mold Default Material` 读取默认材料和颜色信息。

---

## 6. 推荐操作顺序

PMC 日常建议按下面顺序操作：

1. 导入新的客户排期并看差异。
2. 重建需求池。
3. 重算净需求。
4. 创建并运行 APS Trial Run。
5. 打开 Run 表单检查排程结果、异常、未排量。
6. 审批 APS Run。
7. 同步到 `Delivery Plan / Work Order Scheduling`。
8. 只释放短期窗口工单。
9. 在 `Release & Exception Center` 跟踪异常和插单影响。

如果你们当天只是客户更新排期，不需要立刻释放工单，也至少要做到前 5 步。

---

## 7. 页面级使用说明

## 7.1 Schedule Import & Diff

页面名称：`Schedule Import & Diff`

用途：

1. 导入客户交期版本。
2. 和当前有效版本做差异比对。
3. 形成正式版本。

### 操作步骤

1. 打开 `Schedule Import & Diff`。
2. 点击右上角 `Preview Import`。
3. 选择 `Customer`。
4. 选择 `Company`。
5. 输入 `Version No`。
6. 上传 Excel 文件，或者直接粘贴 `Rows JSON`。
7. 点击 `Preview`。
8. 系统会先做预检，不会立刻落正式版本。
9. 页面中间会显示 `Pending Preview`，包含行数和差异汇总。
10. 确认无误后，点击右上角 `Import Pending`。

### Excel / 数据支持字段

当前导入逻辑会识别下面这些字段名：

1. `sales_order` / `sales order`
2. `item_code` / `item` / `item code`
3. `customer_part_no` / `customer part no`
4. `schedule_date` / `schedule date`
5. `delivery_date` / `delivery date`
6. `qty` / `quantity`
7. `remark` / `remarks`

### 差异类型说明

系统当前会识别这些差异类型：

1. `Added`
2. `Cancelled`
3. `Advanced`
4. `Delayed`
5. `Increased`
6. `Reduced`
7. `Unchanged`

### 导入后的系统行为

1. 创建一张 `APS Schedule Import Batch`
2. 当前同客户同公司的旧 `Customer Delivery Schedule` 会从 `Active` 变成 `Superseded`
3. 新版本会创建为新的 `Customer Delivery Schedule`
4. 新版本状态为 `Active`
5. 每一行会落到 `Customer Delivery Schedule Item`

### 你应该重点检查什么

1. 版本号是否正确
2. 数量变化是否符合客户最新 FC
3. 提前和延期行是否合理
4. 被取消的行是否会影响已开工单

---

## 7.2 Net Requirement Workbench

页面名称：`Net Requirement Workbench`

用途：

1. 重建 APS 需求池
2. 根据库存和在制重算净需求
3. 在排程前先看“为什么需要生产”

### 操作步骤

1. 打开 `Net Requirement Workbench`
2. 选择 `Company`
3. 如有需要，可筛选 `Item`
4. 先点 `Rebuild Demand Pool`
5. 再点 `Recalculate Net Requirements`
6. 查看表格结果

### 当前会自动纳入的需求来源

当前代码里自动生成的需求来源有 3 类：

1. `Customer Delivery Schedule`
2. `Sales Order Backlog`
3. `Safety Stock`

注意：

`Urgent Order`、`Trial Production`、`Complaint Replenishment` 虽然 APS 内部已经有优先级定义，但当前页面还没有专门录入入口。如果需要，可通过后续自定义单据或 API 补充。

### 当前净需求逻辑

当前系统核心公式是：

`净需求 = 需求量 - 可用库存 - 未完工工单量 + 安全库存缺口 - 超库存抑制`

同时还会考虑：

1. `minimum_batch_qty`
2. `max_stock_qty`
3. `safety_stock`

### 表格字段怎么理解

1. `Demand`：需求量
2. `Stock`：可用库存
3. `Open WO`：已开未完工工单量
4. `Safety Gap`：安全库存缺口
5. `Min Batch`：最小经济批量
6. `Planning Qty`：最终建议排产量
7. `Net Qty`：真实净需求量
8. `Reason`：系统解释文本

### 什么时候要停下来先处理

如果你看到以下情况，建议先别直接跑 APS Run：

1. 某些关键物料 `Net Qty` 异常大
2. 库存明显不准
3. 已开工单量明显不对
4. 安全库存字段未维护导致系统补货过多

---

## 7.3 APS Run Console

页面名称：`APS Run Console`

用途：

1. 发起 Trial Run
2. 查看 run 列表
3. 打开具体 run 表单做审批和下发

### 操作步骤

1. 打开 `APS Run Console`
2. 选择 `Company`
3. 可选选择 `Plant Floor`
4. 点击 `Run Trial`
5. 输入 `Horizon Days`
6. 提交后系统会自动执行：
   - 重建需求池
   - 重算净需求
   - 清空该 run 旧的 schedule result / exception
   - 重新生成本次 run 的排程建议和异常

### Run 列表关键字段

1. `Plan Qty`：本次要计划的总量
2. `Scheduled`：成功安排进机台时段的量
3. `Unscheduled`：没有安排进去的量
4. `Exceptions`：本次 run 生成的异常数量
5. `Status`：当前 run 所处阶段
6. `Approval`：审批状态

### Status 的实际含义

当前 run 的状态大致会经过这些阶段：

1. `Draft`
2. `Planned`
3. `Approved`
4. `Synced`
5. `Partially Released`

---

## 7.4 APS Planning Run 表单

虽然 `APS Run Console` 可以创建 trial，但真正的核心动作建议在 `APS Planning Run` 表单里做。

当前表单按钮有：

1. `Run Planning`
2. `Approve`
3. `Sync Downstream`
4. `Release Window`
5. `Rebuild Exceptions`

### 按钮怎么用

#### 1. Run Planning

适用于：

1. 已有 run，但改了配置后要重算
2. 想在同一个 run 下重排

执行后会重新生成：

1. `APS Schedule Result`
2. `APS Schedule Segment`
3. `APS Exception Log`

#### 2. Approve

适用于：

1. PMC 确认排程建议可接受
2. 准备同步下游

执行后：

1. `APS Planning Run.approval_state` 变成 `Approved`
2. `APS Schedule Result.status` 变成 `Approved`
3. `APS Schedule Segment.segment_status` 变成 `Approved`

#### 3. Sync Downstream

只有 `Approved` 的 run 才能同步。

执行后系统会：

1. 尝试创建一张 `Delivery Plan`
2. 尝试创建一张 `Work Order Scheduling`
3. 给这些执行对象写入 `custom_aps_*` 字段

这一步是“计划结果下发”，不是“正式释放工单”。

#### 4. Release Window

这是短期执行释放，不是全量长期开工单。

你需要输入：

1. `Release Horizon Days`

系统会只释放从今天开始、在这个窗口内的已排程结果。

执行后系统会：

1. 创建 `APS Release Batch`
2. 生成短期 `Work Order`
3. 创建一张释放用的 `Work Order Scheduling`
4. 把相关 `APS Schedule Result` / `APS Schedule Segment` 标记成 `Released`

#### 5. Rebuild Exceptions

如果你修改了机台、规则、BOM 或锁定状态，想刷新异常中心，可以直接点这个按钮。

---

## 7.5 Machine Schedule Gantt

页面名称：`Machine Schedule Gantt`

用途：

1. 按 `APS Planning Run` 查看当前机台排程结果
2. 观察每台机的时段分布和风险等级

### 操作步骤

1. 打开 `Machine Schedule Gantt`
2. 在顶部选择一个 `Planning Run`
3. 点击 `Load Gantt`

### 你能看到什么

1. 按 `Workstation` 分行显示
2. 每个排程段显示 `Item / Qty`
3. 支持不同风险样式
4. 显示窗口开始时间、结束时间、任务数、机台数

### 当前版本限制

这个页面当前是只读看板：

1. 不能拖拽
2. 不能直接在 Gantt 上改顺序
3. 不能直接改机台

如果要调整，当前应先改基础约束或重跑 Run。

---

## 7.6 Release & Exception Center

页面名称：`Release & Exception Center`

用途：

1. 处理同步
2. 处理释放
3. 查看异常
4. 做插单影响分析

### 页面按钮

1. `Sync Approved Run`
2. `Release Window`
3. `Rebuild Exceptions`
4. `Impact Analysis`

### 典型用法

#### 场景 1：审批后下发执行层

1. 在顶部选择一个 `Planning Run`
2. 点击 `Sync Approved Run`

结果：

1. 会下发到 `Delivery Plan`
2. 会下发到 `Work Order Scheduling`
3. 但不会直接把全部长期量一次性开光

#### 场景 2：只释放未来 3 天

1. 选择 run
2. 点击 `Release Window`
3. 输入 `Release Horizon Days`
4. 确认释放

结果：

1. 只处理近端窗口
2. 为窗口内排程段生成 `Work Order`
3. 生成释放批次 `APS Release Batch`

#### 场景 3：客户插单前先看影响

1. 点击 `Impact Analysis`
2. 输入 `Company`
3. 输入 `Plant Floor`
4. 输入 `Item`
5. 输入 `Qty`
6. 输入 `Required Date`
7. 可选输入 `Customer`
8. 点 `Analyze`

页面会返回：

1. `Scheduled Qty`
2. `Unscheduled Qty`
3. `Changeover Minutes`
4. `Impacted Customers`
5. 被挤占的 `impacted_segments`

这一步非常适合 PMC 在接插单时先做影响判断。

---

## 8. APS 实际排程规则

这部分是“系统现在实际怎么选机、怎么判风险”，不是理想蓝图。

### 8.1 候选机台选择

当前 APS 会按下面逻辑过滤机台：

1. 必须来自 `APS Machine Capability`
2. `is_active = 1`
3. 机台状态不能是：
   - `Unavailable`
   - `Fault`
   - `Maintenance`
   - `Disabled`
4. 如果模具有吨位要求，机台吨位不能低于模具吨位
5. 如果 `APS Mould-Machine Rule` 设了最小/最大吨位，要满足规则

### 8.2 模具选择

当前会优先从 `Mold Product` 中找该产品的首选模具。

如果找到模具，会带入：

1. `machine_tonnage`
2. `cycle_time_seconds`
3. `output_qty`
4. `mould_reference`

### 8.3 FDA 风险门禁

如果产品被识别为 FDA / food grade 要求，而机台风险类别是 `Non FDA`，当前 APS 会直接判为阻断，不会默默排进去。

这是当前实现里最重要的硬门禁之一。

### 8.4 换色 / 换料 / 首件确认

当前 APS 会给以下动作加 setup / penalty：

1. 颜色切换
2. 材料切换
3. 首件确认
4. 模具切换

具体行为：

1. 有 `APS Color Transition Rule` 时，会取规则里的 `setup_minutes`
2. 材料变化时，额外加 15 分钟
3. 首件标识时，额外加 `default_first_article_minutes`
4. 模具变化时，额外加 30 分钟

### 8.5 锁定段

当前 APS 会尊重已经锁定的排程段。

锁定逻辑依赖：

1. `APS Schedule Segment.is_locked = 1`
2. `segment_status` 属于：
   - `Approved`
   - `Synced`
   - `Released`
   - `Partially Released`

这些段会先占住机台时间，新的 run 会绕开它们。

### 8.6 排程结果风险级别

当前常见风险状态有：

1. `Normal`
2. `Attention`
3. `Critical`
4. `Blocked`

一般含义：

1. `Normal`：排进去了，且风险较低
2. `Attention`：能排进去，但可能晚于需求日
3. `Critical`：排程严重吃紧，或只能部分安排
4. `Blocked`：根本没有合格机台或被硬门禁挡住

---

## 9. 同步与释放后会发生什么

### 9.1 Sync Downstream

审批通过后点 `Sync Downstream`，系统会尽量做两件事：

1. 创建 `Delivery Plan`
2. 创建 `Work Order Scheduling`

注意：

`Delivery Plan` 是按本次 run 的已排程结果汇总出来的。

`Work Order Scheduling` 当前是把已有 open `Work Order` 尽量挂到 APS 的时段上，不是直接修改所有在制工单。

### 9.2 Release Window

释放窗口时，系统才会真正去生成短期执行工单。

当前生成的 `Work Order` 会写入这些 APS 字段：

1. `custom_aps_run`
2. `custom_aps_source`
3. `custom_aps_required_delivery_date`
4. `custom_aps_is_urgent`
5. `custom_aps_release_status`
6. `custom_aps_locked_for_reschedule`
7. `custom_aps_schedule_reference`

`Work Order Scheduling` 会写：

1. `custom_aps_run`
2. `custom_aps_freeze_state`
3. `custom_aps_approval_state`

`Delivery Plan` 会写：

1. `custom_aps_version`
2. `custom_aps_source`

这些字段都是 APS 自己管理的隔离字段。

---

## 10. 关键单据之间的关系

日常理解时，可以按这条链来看：

1. `Customer Delivery Schedule`
2. `APS Demand Pool`
3. `APS Net Requirement`
4. `APS Planning Run`
5. `APS Schedule Result`
6. `APS Schedule Segment`
7. `APS Exception Log`
8. `APS Release Batch`
9. `Delivery Plan / Work Order Scheduling / Work Order`

简单理解：

1. 排期版本是输入
2. 需求池是收口
3. 净需求是“该不该做”
4. Planning Run 是“这次怎么算”
5. Schedule Result 是“算出来的单项结果”
6. Schedule Segment 是“落在哪台机、哪个时间段”
7. Exception Log 是“哪里有风险”
8. Release Batch 是“这次释放了哪些短期执行量”

---

## 11. 常见问题与处理建议

## 11.1 Preview 可以，Import 后没有净需求

先检查：

1. `Customer Delivery Schedule` 是否真的变成 `Active`
2. `Customer Delivery Schedule Item.balance_qty` 是否大于 0
3. 是否执行了 `Rebuild Demand Pool`
4. 是否执行了 `Recalculate Net Requirements`

## 11.2 Net Requirement 是 0，但明明客户有需求

常见原因：

1. 可用库存过大
2. 已开未完工工单量过大
3. 销售订单 backlog 已被有效排期覆盖
4. 需求日期不在当前筛选条件里

## 11.3 Run 完成了，但没有任何排程段

常见原因：

1. 没有 `APS Machine Capability`
2. 机台都被判为不可用
3. 模具吨位与机台不匹配
4. FDA 冲突
5. 关键 Item 没有可排条件

优先检查：

1. `APS Machine Capability`
2. `APS Mould-Machine Rule`
3. `Mold` / `Mold Product`
4. `APS Exception Log`

## 11.4 可以跑出结果，但无法释放 Work Order

最常见的原因是没有 BOM。

当前 release 时，如果找不到：

1. `Item.default_bom`
2. 或默认有效 BOM

系统不会生成工单，并会在异常里写 `Missing BOM`。

## 11.5 FDA 产品被排不进去

如果产品字段被识别为 FDA，而 `Workstation` 风险字段是 `Non FDA`，当前就是硬阻断。

处理方式：

1. 调整机台风险类别
2. 调整字段映射
3. 换到 FDA 合格机台

## 11.6 插单分析显示能排，但会挤掉别的段

这是正常行为。当前 `Impact Analysis` 的意义就是提前告诉你：

1. 会撞到哪些段
2. 影响哪些客户
3. 增加多少换模换色时间

所以这一步适合拿给 PMC / Sales / Management 做判断，而不是直接执行。

---

## 12. 建议的 PMC 日常操作节奏

### 12.1 每天早上

1. 导入最新客户排期版本
2. 重建需求池
3. 重算净需求
4. 跑一次 Trial Run
5. 看异常和未排量

### 12.2 计划确认后

1. 打开 `APS Planning Run`
2. 审批 `Approve`
3. 同步 `Sync Downstream`
4. 只释放未来 1 到 3 天

### 12.3 有插单时

1. 先做 `Impact Analysis`
2. 看被影响机台段
3. 看被影响客户
4. 再决定是否重跑

### 12.4 每天下午

1. 检查 `Release & Exception Center`
2. 看还有哪些 blocking exception
3. 补 BOM、补机台能力、补颜色切换规则

---

## 13. 当前版本的使用边界

为了避免现场误用，下面这些边界要特别记住：

1. 当前 APS 是“建议 + 审批 + 下发”，不是全自动黑盒。
2. 当前 Gantt 是只读板，不是拖拽排程器。
3. 当前自动需求来源以 `客户排期 + SO backlog + safety stock` 为主。
4. 当前释放逻辑坚持“短期窗口释放”，不是长期一次性全部预开。
5. 当前异常中心很重要，看到 `Critical` / `Blocking` 不建议直接跳过。
6. 当前如果基础主数据没维护好，APS 会给结果，但质量会明显下降。

---

## 14. 建议先给业务培训的顺序

如果你要给 PMC / Sales / Production 做培训，建议按下面顺序讲：

1. `Schedule Import & Diff`
2. `Net Requirement Workbench`
3. `APS Run Console`
4. `APS Planning Run`
5. `Machine Schedule Gantt`
6. `Release & Exception Center`

这样业务最容易理解“排期 -> 净需求 -> run -> 审批 -> 下发 -> 释放”的闭环。

---

## 15. 对现场最重要的一句话

当前 APS 的正确使用方式，不是“直接让系统全自动排完”，而是：

先把客户排期版本化，再把净需求算准，再用 Trial Run 快速看风险，最后只释放短期确认执行量。
