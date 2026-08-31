## 1. Core memory pipeline
- [x] 1.1 Add domain action enums and task router helper
- [x] 1.2 Add SQL `fetch_active_domain_memories`
- [x] 1.3 Add applicability judge (LLM + mock)
- [x] 1.4 Add `make_domain_memory_recall_node`

## 2. Graph wiring
- [x] 2.1 Wire `memory_recall_{domain}` in sub-agent graphs
- [x] 2.2 Remove domain recall from primary graph; scoped delegation state
- [x] 2.3 Update domain_runtime prompt injection

## 3. Tests & eval
- [x] 3.1 Unit tests for applicability and recall nodes
- [x] 3.2 Applicability eval fixture and CLI path
