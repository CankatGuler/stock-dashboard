# 📡 AI-Destekli Hisse Senedi Analiz ve Karar Dashboard'u

Quantitative Signal Engine · Fundamental Screener · Claude AI Risk Mapping

---

## 🗂 Klasör Yapısı

```
stock_dashboard/
├── app.py              # Ana Streamlit dashboard
├── data_fetcher.py     # FMP API entegrasyonu (profil, gelir tablosu, nakit akışı)
├── news_fetcher.py     # NewsAPI + RSS fallback + gürültü filtresi
├── claude_analyzer.py  # Anthropic Claude API analiz motoru
├── utils.py            # Sabitler, sektör-ticker eşlemeleri, yardımcı fonksiyonlar
├── requirements.txt    # Python bağımlılıkları
├── .env.example        # API key şablonu (gerçek keyleri buraya yazma!)
└── README.md           # Bu dosya
```

---

## ⚡ Kurulum

### 1. Sanal Ortam Oluştur

```bash
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

### 2. Bağımlılıkları Yükle

```bash
pip install -r requirements.txt
```

### 3. API Anahtarlarını Ayarla

```bash
cp .env.example .env
```

`.env` dosyasını bir metin editörüyle açıp gerçek API anahtarlarını gir:

```env
FMP_API_KEY=your_fmp_api_key_here
NEWS_API_KEY=your_newsapi_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

**API Key'leri Nereden Alınır?**
| Servis | URL | Not |
|--------|-----|-----|
| Financial Modeling Prep (FMP) | https://financialmodelingprep.com/developer/docs | Ücretsiz plan yeterli (250 req/gün) |
| NewsAPI | https://newsapi.org/register | Ücretsiz plan (100 req/gün, developer) |
| Anthropic Claude | https://console.anthropic.com/ | Pay-per-use |

### 4. Dashboard'u Başlat

```bash
streamlit run app.py
```

Tarayıcında `http://localhost:8501` adresini aç.

---

## 🔧 Sistem Mimarisi

```
┌─────────────────────────────────────────────────────────────┐
│  STREAMLIT UI (app.py)                                      │
│  Sol Menü: Sektör, Strateji, Parametre seçimi               │
└───────────────────────┬─────────────────────────────────────┘
                        │ Analizi Başlat
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  ADIM 1 — data_fetcher.py                                   │
│  FMP API → Profil + Gelir Tablosu + Nakit Akışı             │
│  A Tipi (Kalkan): MktCap>10B & FCF>0                        │
│  B Tipi (Roket) : Yüksek Ar-Ge, volatile                    │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  ADIM 2 — news_fetcher.py                                   │
│  NewsAPI (son 7 gün) → RSS fallback                         │
│  Sinyal filtresi: Contract, Patent, Form4, FDA...           │
│  Tier-3 domain engeli: seekingalpha, zerohedge...           │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  ADIM 3 — claude_analyzer.py                                │
│  Claude API → Sistem Prompt (Kanti Analist)                 │
│  Çıktı: JSON { skor, özet, riskler, tavsiye }               │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  DASHBOARD ÇIKTISI (app.py)                                 │
│  • Top 5 KPI kartları (renkli skor rozeti)                  │
│  • Gauge grafikleri                                         │
│  • İkili Risk Haritası (Makro + Şirket)                     │
│  • Filtreli haberler listesi                                │
│  • Özet tablo + CSV indir                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Puanlama Mantığı

| Haber Tipi | A Tipi Etkisi | B Tipi Etkisi |
|------------|--------------|--------------|
| Devlet sözleşmesi / ihale | +++ (75-100) | ++ (60-80) |
| Patent / FDA / FAA onayı | + (50-65) | +++ (75-100) |
| Form 4 / İçeriden alım | ++ (60-75) | +++ (80-100) |
| Merger / Acquisition | ++ | + |
| Makro risk (faiz, jeopol.) | --- | --- |
| Clickbait / Belirsiz haber | -- (0-40) | -- (0-40) |

---

## 📦 Bağımlılıklar

| Paket | Versiyon | Kullanım |
|-------|----------|---------|
| streamlit | 1.35.0 | UI framework |
| anthropic | 0.28.0 | Claude API |
| requests | 2.32.3 | HTTP istemcisi |
| python-dotenv | 1.0.1 | Env yönetimi |
| pandas | 2.2.2 | Veri tablosu |
| plotly | 5.22.0 | Gauge grafikleri |
| feedparser | 6.0.11 | RSS fallback |
| beautifulsoup4 | 4.12.3 | HTML parse |

---

## ⚠️ Yasal Uyarı

Bu araç **yatırım tavsiyesi değildir**. Tüm veriler bilgilendirme amaçlıdır.
Yatırım kararları tamamen kullanıcının sorumluluğundadır.
