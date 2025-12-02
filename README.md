# 🤖 Customer Support Agent

AI-powered customer support bot với **Hybrid Search** (Qdrant + Exact Filters) cho travel & car rental services.

## ✨ Features

- 🚗 **Car Rental Agent**: Search, book, update, cancel car rentals
- 🏨 **Hotel Agent**: Hotel booking management
- 🎫 **Excursion Agent**: Tour & activity booking
- 🔍 **Hybrid Search**: Kết hợp semantic search (Qdrant) với exact filters
- 🌐 **Multi-agent Architecture**: LangGraph-based orchestration
- 💬 **Natural Language Understanding**: Powered by Google Gemini 2.0

## 🚀 Quick Start

### 1. Installation

```bash
# Clone repository
git clone <your-repo-url>
cd customer-support-agent

# Install dependencies
pip install -r requirements.txt
```

**Note**: Lần đầu chạy sẽ download embedding model (~400MB) nếu bật Qdrant.

### 2. Configuration

Tạo file `.env`:

```env
# JSONBIN.io API (Data storage)
JSONBIN_BIN_ID=your_bin_id
JSONBIN_API_KEY=your_api_key

# Google Gemini API
GOOGLE_API_KEY=your_google_api_key

# Hybrid Search (Optional)
USE_QDRANT=true  # true = semantic search, false = exact search
```

### 3. Test Hybrid Search

```bash
# Quick test
python test_hybrid_search.py

# Test trong notebook
jupyter notebook src/notebooks/car_agent.ipynb
```

## 🏗️ Architecture

```
User Query
    ↓
[Primary Agent] (Router)
    ↓
┌─────────────┬──────────────┬────────────────┐
│ Car Agent   │ Hotel Agent  │ Excursion Agent│
└─────────────┴──────────────┴────────────────┘
    ↓
[Hybrid Search Engine]
    ├── Qdrant (Semantic)
    └── Exact Filters
    ↓
[JSONBIN.io Cloud Storage]
```

## 🔍 Hybrid Search

### Kiến trúc

- **Semantic Search (Qdrant)**: Tìm theo nghĩa, typo-tolerant
- **Exact Filters**: Filter chính xác (price, rating, capacity)
- **Fallback**: Auto-fallback về exact search nếu Qdrant fail

### Use Cases

| Query Type | Qdrant | Exact | Winner |
|------------|--------|-------|--------|
| "Xe ở Thủ đô" | ✅ Tìm được "Hà Nội" | ❌ | Qdrant |
| "Ha Noi economy" (typo) | ✅ | ⚠️ | Qdrant |
| "rating > 8.5" | ✅ | ✅ | Tie |
| "sedan cao cấp" | ✅ Semantic | ❌ | Qdrant |

📖 **Chi tiết**: [docs/HYBRID_SEARCH.md](docs/HYBRID_SEARCH.md)

## 📁 Project Structure

```
customer-support-agent/
├── src/
│   ├── agents/
│   │   ├── car/          # Car rental agent
│   │   ├── hotel/        # Hotel agent
│   │   └── excursion/    # Excursion agent
│   ├── utils/
│   │   ├── api_client.py # 🔥 Hybrid search engine
│   │   ├── db.py         # Database utilities
│   │   └── utils.py      # Helper functions
│   └── notebooks/        # Test notebooks
├── docs/
│   └── HYBRID_SEARCH.md  # Hybrid search documentation
├── requirements.txt      # Dependencies
└── test_hybrid_search.py # Quick test script
```

## 🧪 Testing

### Run notebook tests
```bash
cd src/notebooks
jupyter notebook car_agent.ipynb
```

### Run standalone tests
```bash
python test_hybrid_search.py
```

### Example test cases
```python
# Test 1: Semantic understanding
"Tôi muốn xe ở Thủ đô, giá rẻ" → Finds "Hà Nội", "Economy"

# Test 2: Typo tolerance  
"Ha Noi economy rating tren 8" → Finds "Hà Nội", rating > 8

# Test 3: Fuzzy matching
"sedan sang trọng" → Finds "Mercedes", "BMW", "Luxury"
```

## 🔧 Configuration

### Enable/Disable Qdrant

```env
# .env
USE_QDRANT=true   # Enable semantic search
USE_QDRANT=false  # Use exact search only (faster, less RAM)
```

### Performance Comparison

| Mode | Speed | Accuracy | RAM | Best For |
|------|-------|----------|-----|----------|
| Qdrant ON | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ~500MB | Production |
| Qdrant OFF | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ~50MB | Development/Demo |

## 📊 Data Storage

Sử dụng **JSONBIN.io** làm cloud storage:
- ✅ No local database setup
- ✅ Demo-friendly (works anywhere with internet)
- ✅ Auto-sync across devices
- ✅ In-memory caching cho performance

## 🐛 Troubleshooting

### Issue: Model download quá lâu
```bash
# Pre-download model
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"
```

### Issue: RAM hết
```env
# Tắt Qdrant
USE_QDRANT=false
```

### Issue: API limit (JSONBIN)
- Free tier: 100 requests/minute
- Upgrade hoặc dùng local caching

## 🚀 Deployment

### Demo (Current)
- In-memory Qdrant
- JSONBIN.io cloud storage

### Production (Recommended)
- Qdrant Cloud: https://cloud.qdrant.io
- PostgreSQL hoặc MongoDB
- Docker container

## 📚 Tech Stack

- **LLM**: Google Gemini 2.0 Flash
- **Framework**: LangChain + LangGraph
- **Vector DB**: Qdrant
- **Embedding**: Sentence Transformers (multilingual)
- **Storage**: JSONBIN.io
- **Language**: Python 3.12+

## 🤝 Contributing

1. Fork repo
2. Create feature branch
3. Commit changes
4. Push và create PR

## 📄 License

MIT License

## 👥 Team

Customer Support Bot Team

---

Made with ❤️ and ☕ by the team