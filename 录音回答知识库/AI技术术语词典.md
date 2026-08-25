# AI技术术语词典

本文件既是面试知识库资料，也是实时语音的可编辑术语表。编辑“常见别名或错词”即可增加保守纠错规则；多个别名使用英文分号分隔。

| 标准术语 | 英文全称 | 常见别名或错词 | 准确定义 | 面试口述 |
|---|---|---|---|---|
| MCP | Model Context Protocol | mcp; MCB; 模型上下文协议 | 一种开放标准，用统一方式让AI应用连接外部数据源、工具和工作流。MCP客户端连接MCP服务器，服务器可暴露资源、提示词和工具。 | MCP可以理解为AI应用连接外部能力的标准接口，重点是统一协议和可复用集成，不是某个具体模型。 |
| Skill | Skill | ski; SKI; skills | 在Agent系统中，通常指封装了特定任务知识、操作流程和工具使用方式的可复用能力模块；具体边界取决于所使用的平台。 | Skill是给Agent复用的一组专业能力说明和执行流程，让它在特定任务上更稳定。 |
| Agent Workflow | Agent Workflow | agentworkflow; agent workflow | 为完成目标而编排的多步骤流程，通常包含状态、判断、工具调用、重试、人工确认和结果验证。 | Agent Workflow不是一句提示词，而是把任务拆成可执行、可观察、可恢复的步骤。 |
| RAG | Retrieval-Augmented Generation | rag; 检索增强生成 | 在生成回答前检索外部知识，并把相关证据提供给模型，以提高时效性和可追溯性、降低幻觉。 | RAG先找资料再回答，模型负责组织语言，但事实应由检索证据支撑。 |
| Function Calling | Function Calling | functioncalling; 函数调用 | 模型按照预定义结构选择函数并生成参数，由应用执行函数，再把结果返回模型或用户。 | Function Calling让模型表达“要调用什么以及参数是什么”，真正执行仍由应用负责。 |
| Tool Calling | Tool Calling | toolcalling; 工具调用 | 模型选择并调用外部工具的机制，工具可以是函数、API、搜索、数据库或业务动作。 | Tool Calling比Function Calling范围更广，核心是让模型安全地使用外部能力。 |
| AI Agent | Artificial Intelligence Agent | aiagent; 智能体 | 能围绕目标感知上下文、规划或选择动作、调用工具并根据结果继续执行的软件系统。 | Agent的关键不是会聊天，而是能围绕目标调用工具、维护状态并验证结果。 |
| LLM | Large Language Model | llm; 大语言模型 | 基于大规模数据训练、能够理解和生成自然语言及代码的模型。 | LLM是语言推理和生成引擎，Agent则在它外面增加工具、状态和执行流程。 |
| AIGC | AI-Generated Content | aigc; 生成式人工智能内容 | 使用生成式AI创建文本、图像、音频、视频或代码等内容。 | AIGC强调内容生成，Agent更强调围绕目标采取行动。 |
| Dify | Dify | dify | 面向生成式AI应用开发的开源平台，提供工作流、知识库、模型接入、Agent和应用发布能力。 | Dify适合快速搭建和运营LLM应用，但复杂业务仍需关注权限、数据和工程集成。 |
| LangChain | LangChain | langchain | 用于构建大模型应用的开发框架，提供模型、提示词、检索、工具和Agent等组件及编排能力。 | LangChain提供应用组件和集成生态，适合代码化构建LLM工作流。 |
| AutoGen | AutoGen | autogen | 面向多Agent应用和对话式协作流程的开源框架，可组织多个Agent、工具与人工参与。 | AutoGen更偏多Agent协作编排，需要额外设计角色边界、终止条件和验证机制。 |
| AIoT | Artificial Intelligence of Things | aiot; 人工智能物联网 | AI与物联网结合，通过设备感知、连接、边缘或云端分析形成智能决策和控制闭环。 | AIoT不是简单给设备加模型，而是感知、连接、分析、决策和执行的完整闭环。 |
| 多模态 | Multimodal AI | multimodal; 多模态AI | 能联合处理或生成文本、图像、音频、视频和传感器数据等多种信息形式的AI能力。 | 多模态的价值在于跨信息形式理解任务，而不是把多个模型简单堆在一起。 |
