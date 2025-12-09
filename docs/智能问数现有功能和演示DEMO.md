智能问数和分析
=========
# 一、单指标查询

## 1.1 单轮
精确时间点+精确指标，直接调用能源平台返回该指标该时间的精确数据。
![image-20251205164601339](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205164601339.png)
## 1.2 多轮

### 1.2.1 缺时间
会询问用户补充时间，时间补充完整后会调用能源平台返回该指标该时间的精确数据。

例如：

![image-20251205164920618](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205164920618.png)

### 1.2.2 指标不精确

会提示用户选择系统返回最近似的前五条备选指标，可以通过直接回复数字选择，或者输入更精确的指标名称进行更优匹配。

例如：

![image-20251205165627405](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205165627405.png)



# 二、多指标查询

## 2.1 单轮

![image-20251205170836418](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205170836418.png)

## 2.2 多轮

### 2.2.1 缺时间

![image-20251205170422579](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205170422579.png)

### 2.2.2 指标不明确

![image-20251205170729532](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205170729532.png)

# 三、对比分析

## 3.1 一步对比

![image-20251205171155644](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205171155644.png)

## 3.2 两步对比

![image-20251205171326173](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205171326173.png)

## 3.3 三步对比

![image-20251205171845896](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205171845896.png)

## 3.4 序列对比

![image-20251205172542344](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205172542344.png)

# 四、趋势分析

## 4.1 单指标

![image-20251205173224531](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205173224531.png)

![image-20251205173248454](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205173248454.png)

## 4.2 多指标

![image-20251205173610987](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251205173610987.png)

![img](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/e2193372-e293-4234-818a-9b0bc13946e6.png)

# 五、指标匹配 

支持指标别名及相对精准的匹配（如1#高炉，1高炉，高炉的区分）

* 完整匹配原则

* 最左匹配原则

  * “高炉工序能耗”、“高炉工序能耗实绩”，一定会匹配到“高炉工序能耗实绩报出值”。

  * “高炉工序能耗计划”，一定会匹配到“高炉工序能耗计划报出值”。
  * “高炉工序能耗累计”，会提供选择项，靠前的是“高炉工序能耗实绩累计值”和“高炉工序能耗计划累计值”。

* 支持多轮备选确认，编号选择或者重新输入

* 用户偏好设置，支持**即时**重选设置。

  ```
    "preferences": {
        "高炉工序能耗累计值": {
          "FORMULAID": "GXNHLT1100.IXRL.SUMVALUE",
          "FORMULANAME": "高炉工序能耗实绩累计值"
        }
      }
  ```

* 灵活的自定义加权

  ```
  {
      "combines": [
          {
              "terms": [
                  "实绩",
                  "报出值"
              ],
              "weight": 0.12
          },
          {
              "terms": [
                  "计划",
                  "报出值"
              ],
              "weight": 0.08
          },
          {
              "terms": [
                  "实绩",
                  "累计值"
              ],
              "weight": 0.03
          },
          {
              "terms": [
                  "计划",
                  "累计值"
              ],
              "weight": 0.02
          }
      ],
      "default_boost": 0.05
  }
  ```

# 六、知识图谱

构建能源工厂建模知识图谱，识别指标关系

支持查询结构检查，并通过多轮会话来补充查询条件

```
{
  "graph": {
    "nodes": [
      {
        "id": 1,
        "indicator_entry": {
          "status": "completed",
          "indicator": "高炉工序能耗实绩报出值",
          "formula": "GXNHLT1100.IXRL",
          "timeString": "2022-03",
          "timeType": "MONTH",
          "slot_status": {
            "formula": "filled",
            "time": "filled"
          },
          "value": "372.53",
          "note": "✅ 高炉工序能耗实绩报出值 在 2022-03 (MONTH) 的查询结果: 372.53",
          "formula_candidates": null
        },
        "intent_info_snapshot": {
          "user_input_list": [
            "2022年3月高炉工序能耗是多少，对比计划偏差多少"
          ],
          "intent_list": [
            "compare"
          ],
          "indicators": [
            {
              "status": "completed",
              "indicator": "高炉工序能耗实绩报出值",
              "formula": "GXNHLT1100.IXRL",
              "timeString": "2022-03",
              "timeType": "MONTH",
              "slot_status": {
                "formula": "filled",
                "time": "filled"
              },
              "value": "372.53",
              "note": "✅ 高炉工序能耗实绩报出值 在 2022-03 (MONTH) 的查询结果: 372.53",
              "formula_candidates": null
            },
            {
              "status": "active",
              "indicator": "高炉工序能耗计划",
              "formula": null,
              "timeString": "2022-03",
              "timeType": "MONTH",
              "slot_status": {
                "formula": "missing",
                "time": "filled"
              },
              "value": null,
              "note": null,
              "formula_candidates": null
            }
          ]
        }
      },
      {
        "id": 2,
        "indicator_entry": {
          "status": "completed",
          "indicator": "高炉工序能耗计划报出值",
          "formula": "GXNHLT1100.IXPL",
          "timeString": "2022-03",
          "timeType": "MONTH",
          "slot_status": {
            "formula": "filled",
            "time": "filled"
          },
          "value": "374.6823",
          "note": "✅ 高炉工序能耗计划报出值 在 2022-03 (MONTH) 的查询结果: 374.6823",
          "formula_candidates": null
        },
        "intent_info_snapshot": {
          "user_input_list": [
            "2022年3月高炉工序能耗是多少，对比计划偏差多少"
          ],
          "intent_list": [
            "compare"
          ],
          "indicators": [
            {
              "status": "completed",
              "indicator": "高炉工序能耗实绩报出值",
              "formula": "GXNHLT1100.IXRL",
              "timeString": "2022-03",
              "timeType": "MONTH",
              "slot_status": {
                "formula": "filled",
                "time": "filled"
              },
              "value": "372.53",
              "note": "✅ 高炉工序能耗实绩报出值 在 2022-03 (MONTH) 的查询结果: 372.53",
              "formula_candidates": null
            },
            {
              "status": "completed",
              "indicator": "高炉工序能耗计划报出值",
              "formula": "GXNHLT1100.IXPL",
              "timeString": "2022-03",
              "timeType": "MONTH",
              "slot_status": {
                "formula": "filled",
                "time": "filled"
              },
              "value": "374.6823",
              "note": "✅ 高炉工序能耗计划报出值 在 2022-03 (MONTH) 的查询结果: 374.6823",
              "formula_candidates": null
            }
          ]
        }
      }
    ],
    "relations": [
      {
        "type": "compare",
        "source": 1,
        "target": 2,
        "meta": {
          "via": "pipeline.compare",
          "user_input": [
            "2022年3月高炉工序能耗是多少，对比计划偏差多少"
          ],
          "result": "2022年3月，高炉工序能耗实绩报出值低于高炉工序能耗计划报出值，相差2.1523。"
        }
      }
    ],
    "_next_id": 3
  },
  "meta": {
    "current_intent_info": {},
    "history": [
      {
        "ask": "2022年3月高炉工序能耗是多少，对比计划偏差多少",
        "reply": "2022年3月，高炉工序能耗实绩报出值低于高炉工序能耗计划报出值，相差2.1523。"
      }
    ]
  }
}
```

# 七、后续工作

客户现场演示还需要两项依赖项完成。

## 7.1 对话前端选择

* 原生openwebui不满足条件

  * **系统提示词被二次加工 / 补全**
  * **工具响应被 LLM 再解释、再改写**
  * **返回 JSON 后仍被模型继续加工**

  ### 1. **指示模型自动处理工具调用结果的 pipeline（Tool Output Post-Processing）**

  它会认为：

  > 工具结果只是“参考信息”，模型需要用自然语言回答。

  因此它会“帮你改写返回内容”。

  ### 2. **自动 JSON 格式化层（auto JSON schema correction）**

  当你让模型输出 JSON，它会检查并“自动修复结构”，包括：

  - 补全字段
  - 改写文本
  - 添加自然语言解释

  ### 3. **系统 Prompt 在 0.6.41 中分段处理**

  以前系统提示词可以完整接管，现在被切割进 structured prompts middle layer，导致模型没有将你的规则“整体”理解成 hard constraints。

* 延续前序工作，在openwebui**0.6.0**基础版本下实现以下两种功能。

  * 原样转发用户问话到智能问数服务。
  
    > 经测试现有提示词已经满足原样传入用户输入的需求。
  
  * 原样markdown渲染智能问数服务返回内容。
  
    > 经测试在提示词中添加示例指导llm处理某些类型的返回，部分满足需求，但是想要彻底解决需要去掉这问题，可能需要仅用禁用理解增强，或者禁用后置处理的功能。
  
* 总结起来，后期工作需要在这三个项目上配合完成。

  1. openwebui0.6.0已经私有化过的前端。

  2. openwebui0.6.0的backend。

  3. 智能问数api，后续需升级为**能源智能体**。

     ![image-20251209135051373](%E6%99%BA%E8%83%BD%E9%97%AE%E6%95%B0%E7%8E%B0%E6%9C%89%E5%8A%9F%E8%83%BD%E5%92%8C%E6%BC%94%E7%A4%BADEMO.assets/image-20251209135051373.png)

## 7.2 现场大模型接入方式

* 当前示例内部是使用ollama方式调用llm。
* 现场是满血版deepseek，接入方式据说是dify调用方式
  * api服务中dify调用大模型demo，现场测试，llm_client扩展
  * openwebui如果使用dify接入大模型

## 7.3 各系统需优化内容

### 1. 能源系统

* 能源系统问数接口需加入**单位**字段，现阶段只有**数值**。

### 2.小智助手前端

* 本地开发环境。
* 对话框中openwebui图标需更换。
* 自动注册openwebui用户。
* 因使用“智能问数”，会导致所有输入原样传入，原先的上传文档再分析会失效。调整提示词不知道是否满足要求。
* 仿照openwebui前端，所有功能完善。

### 3. openwebui后端

* 依现场条件，需考虑dify方式加入模型。
* 本地开发环境。
* 延续性开发，选择性加入新版功能。

### 4. 能源智能体(现：智能问数)

* 领域化项目目录重构，让架构更合理已读，以便后续支持其它领域扩展。
* 依现场条件，增加dify模式调用llm。
* 因使用“智能问数”，会导致所有输入原样传入，自己内部的记忆会清空。比如，先问“马斯克是谁”，再追问“他最出名的公司是哪个”，智能问数会反问“他具体指谁”，需要在智能问数服务中把普通对话也加入history记忆链。
* 多意图识别。
* 知识库，同openwebui对接。
* mcp化。
* agent化。



