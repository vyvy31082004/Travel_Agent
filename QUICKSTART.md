# ⚡ Quick Start Guide - Hybrid Search

## 🎯 Goal
Get hybrid search running in **5 minutes**.

---

## ✅ Prerequisites

- Python 3.12+
- Internet connection (for first run)
- ~1GB free RAM

---

## 📝 Step-by-Step

### 1️⃣ Install Dependencies (1 min)

```bash
pip install -r requirements.txt
```

### 2️⃣ Configure Environment (30 seconds)

Create/update `.env` file:

```env
# Your existing credentials
JSONBIN_BIN_ID=your_bin_id_here
JSONBIN_API_KEY=your_api_key_here
GOOGLE_API_KEY=your_google_api_key_here

# NEW: Enable hybrid search
USE_QDRANT=true
```

### 3️⃣ Test It! (2 minutes)

#### Option A: Quick Test Script
```bash
python test_hybrid_search.py
```

You should see:
```
🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀
  HYBRID SEARCH TEST SUITE
  Mode: ✨ QDRANT SEMANTIC SEARCH
🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀

✅ Indexed 10 car rentals to Qdrant
✅ Indexed 50 car details to Qdrant
...
```

#### Option B: Notebook Demo
```bash
jupyter notebook src/notebooks/car_agent.ipynb
```

Run Cell 13 to see semantic search in action.

---

## 🧪 Try These Queries

### Test 1: Semantic Understanding
```python
Query: "Tôi muốn xe ở Thủ đô, giá rẻ"
Expected: Tìm được xe ở "Hà Nội" với tier "Economy"
```

### Test 2: Typo Tolerance
```python
Query: "Ha Noi economy"  # Không dấu
Expected: Vẫn tìm được "Hà Nội"
```

### Test 3: Fuzzy Matching
```python
Query: "sedan cao cấp"
Expected: Tìm được Mercedes, BMW, Luxury cars
```

---

## 🔄 Toggle Modes

### Enable Semantic Search (Recommended)
```env
USE_QDRANT=true
```
✅ Best accuracy, typo-tolerant
⚠️ Needs 500MB RAM, first run downloads model (~3 mins)

### Disable (Exact Search Only)
```env
USE_QDRANT=false
```
✅ Fast, lightweight (50MB RAM)
❌ No typo tolerance, exact match only

---

## 🐛 Troubleshooting

### Issue: Download too slow
```bash
# Pre-download model
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"
```

### Issue: Out of memory
```env
# Disable Qdrant
USE_QDRANT=false
```

### Issue: "No module named qdrant_client"
```bash
pip install --upgrade -r requirements.txt
```

---

## ✅ Verification

Run this to verify everything works:

```python
# test_quick.py
from src.utils.api_client import search_car_rentals_from_api, USE_QDRANT

print(f"Qdrant enabled: {USE_QDRANT}")

results = search_car_rentals_from_api(
    location="Hà Nội",
    price_tier="Economy"
)

print(f"Found {len(results)} results")
for r in results[:3]:
    print(f"  - {r['name']} | {r['location']} | {r['rating']}")
```

Expected output:
```
Qdrant enabled: True
✅ Indexed 10 car rentals to Qdrant
🔍 Qdrant semantic search: Found 3 results
Found 3 results
  - Hanoi Drive Car Rental | Hà Nội | 8.5
  - VN Car Rental | Hà Nội | 8.7
  ...
```

---

## 🚀 Next Steps

1. ✅ **Demo với team**: Chạy notebook và show semantic search
2. ✅ **Test với real queries**: Thử các câu hỏi mơ hồ
3. ✅ **Monitor performance**: Check console logs
4. ✅ **Collect feedback**: Từ users/stakeholders

---

## 📚 Learn More

- **Architecture**: See `docs/HYBRID_SEARCH.md`
- **API Reference**: See `src/utils/api_client.py`
- **Full Implementation**: See `IMPLEMENTATION_SUMMARY.md`

---

## 💡 Tips

### For Best Results
- ✅ Use natural language queries
- ✅ Mix exact filters (price_tier) với semantic (location)
- ✅ Check console logs để hiểu search flow

### For Demo
- ✅ Pre-download model trước khi demo
- ✅ Prepare queries showing semantic capabilities
- ✅ Show fallback mechanism (set `USE_QDRANT=false`)

---

## ❓ FAQ

**Q: Có chậm không?**
A: First run ~3 mins (download model), sau đó ~100ms/query

**Q: Cần internet không?**
A: Chỉ lần đầu (download model + fetch data). Sau đó offline OK.

**Q: Demo cho khách được không?**
A: Được! Chạy trên laptop nào cũng OK (có internet lần đầu)

**Q: Production ready?**
A: Có, nhưng nên dùng Qdrant Cloud thay vì in-memory

---

**Ready?** Run `python test_hybrid_search.py` now! 🚀

