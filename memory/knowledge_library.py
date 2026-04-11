# knowledge_library.py — Finansal Terimler Kütüphanesi
#
# Her terim şu alanları içerir:
#   id         : benzersiz key
#   term       : Türkçe terim adı
#   eng        : İngilizce karşılığı
#   category   : kategori
#   emoji      : görsel ikon
#   definition : ne anlama gelir (sade dil)
#   formula    : nasıl hesaplanır (varsa)
#   how_to_read: iyi/kötü nasıl yorumlanır
#   portfolio  : portföy kararında nasıl kullanılır
#   example    : gerçek hayat örneği
#   related    : ilişkili terimler (id listesi)
#   level      : "başlangıç" | "orta" | "ileri"

CATEGORIES = {
    "temel":    {"label": "Temel Metrikler",    "emoji": "📊"},
    "makro":    {"label": "Makro Göstergeler",  "emoji": "🌍"},
    "teknik":   {"label": "Teknik Analiz",      "emoji": "📈"},
    "portfoy":  {"label": "Portföy Yönetimi",   "emoji": "💼"},
    "degerlem": {"label": "Değerleme",          "emoji": "🎯"},
    "piyasa":   {"label": "Piyasa Yapısı",      "emoji": "🏛"},
}

TERMS = [

    # ══════════════════════════════════════════════════════════════════════
    # TEMEL METRİKLER
    # ══════════════════════════════════════════════════════════════════════

    {
        "id": "pe_ratio",
        "term": "F/K Oranı (P/E)",
        "eng": "Price-to-Earnings Ratio",
        "category": "temel",
        "emoji": "💰",
        "level": "başlangıç",
        "definition": (
            "Bir hissenin fiyatının, şirketin hisse başına kazancına oranıdır. "
            "Yatırımcıların 1 dolarlık kâr için kaç dolar ödemeye razı olduğunu gösterir. "
            "Piyasanın o şirkete biçtiği 'değerleme' etiketidir."
        ),
        "formula": "F/K = Hisse Fiyatı ÷ Hisse Başına Kâr (EPS)",
        "how_to_read": (
            "• Düşük F/K (< 15): Ucuz görünür — ama neden ucuz olduğunu sorgula. Şirket sorunlu olabilir.\n"
            "• Orta F/K (15–25): Makul — büyüme beklentisi ile uyumlu.\n"
            "• Yüksek F/K (> 30): Pahalı — ama büyüme hisseleri (NVDA, TSLA gibi) yüksek F/K taşır çünkü "
            "piyasa gelecekteki kazancı fiyatlıyor.\n"
            "• Sektörle kıyasla: Finans sektöründe 12 normal, teknolojide 35 normal olabilir."
        ),
        "portfolio": (
            "Bir hisseyi almadan önce sektör ortalamasıyla kıyasla. "
            "F/K 50 olan bir teknoloji hissesi sektör ortalaması 40 ise 'biraz pahalı' ama "
            "F/K 50 olan bir banka hissesi sektör ortalaması 12 ise 'çok pahalı' demektir. "
            "Risk analizinde yüksek F/K → yüksek değerleme riski anlamına gelir."
        ),
        "example": (
            "Apple (AAPL): F/K ≈ 28 → Piyasa her 1$ kazanç için 28$ ödüyor.\n"
            "Exxon (XOM): F/K ≈ 12 → Enerji sektörü geleneksel olarak düşük F/K taşır.\n"
            "Nvidia (NVDA): F/K ≈ 40–60 → AI büyüme beklentisi fiyatlanıyor."
        ),
        "related": ["eps", "forward_pe", "peg", "pb_ratio"],
    },

    {
        "id": "eps",
        "term": "Hisse Başına Kâr (EPS)",
        "eng": "Earnings Per Share",
        "category": "temel",
        "emoji": "💵",
        "level": "başlangıç",
        "definition": (
            "Şirketin net kârının toplam hisse sayısına bölünmesiyle elde edilir. "
            "Her bir hisseye düşen kâr miktarıdır. "
            "Şirketin karlılığını hisse bazında ölçer."
        ),
        "formula": "EPS = Net Kâr ÷ Toplam Hisse Sayısı",
        "how_to_read": (
            "• Pozitif ve büyüyen EPS: Şirket para kazanıyor ve büyüyor — olumlu.\n"
            "• Negatif EPS: Şirket zarar ediyor — büyüme aşamasındaki şirketlerde normal olabilir (Amazon ilk yıllarda).\n"
            "• EPS sürprizi: Analist beklentisini aşan EPS → hisse genellikle sıçrar.\n"
            "• EPS'i yıllar içinde takip et: Sürekli büyüyen EPS sağlıklı şirket işareti."
        ),
        "portfolio": (
            "Kazanç açıklama döneminde (earnings season) EPS beklentileri kritik. "
            "Portföyündeki şirketin beklentiyi karşılayıp karşılamadığına bak. "
            "Beklenti üzeri EPS → genellikle fiyat yükselişi. "
            "Beklenti altı EPS → genellikle sert düşüş ('earnings miss')."
        ),
        "example": (
            "Apple 2023'te yıllık EPS: ~$6.13\n"
            "Yani Apple her hisse için 6.13$ kazandı.\n"
            "Eğer hisse fiyatı $185 ise F/K = 185 ÷ 6.13 = 30.2"
        ),
        "related": ["pe_ratio", "forward_pe", "net_margin"],
    },

    {
        "id": "forward_pe",
        "term": "İlerideki F/K (Forward P/E)",
        "eng": "Forward Price-to-Earnings",
        "category": "temel",
        "emoji": "🔮",
        "level": "orta",
        "definition": (
            "Şimdiki F/K geçmiş kazancı kullanırken, Forward F/K önümüzdeki 12 ayın "
            "beklenen kazancını kullanır. Piyasanın geleceğe ne kadar ödediğini gösterir."
        ),
        "formula": "Forward F/K = Hisse Fiyatı ÷ Beklenen EPS (sonraki 12 ay)",
        "how_to_read": (
            "• Forward F/K < Mevcut F/K: Analistler büyüme bekliyor — olumlu.\n"
            "• Forward F/K > Mevcut F/K: Kazanç düşmesi bekleniyor — dikkat.\n"
            "• S&P 500 tarihsel Forward F/K ortalaması: ~17-18.\n"
            "• Forward F/K çok düşükse: Ya hisse ucuz ya da beklentiler gerçekçi değil."
        ),
        "portfolio": (
            "Büyüme hisselerini değerlendirirken mevcut F/K çok yüksek görünebilir. "
            "Forward F/K gerçek resmi gösterir. "
            "NVDA'nın mevcut F/K 60 ama Forward F/K 35 ise piyasa hızlı kazanç artışı bekliyor."
        ),
        "example": (
            "Microsoft (MSFT): Mevcut F/K 35, Forward F/K 28\n"
            "→ Analistler %25 kazanç artışı bekliyor.\n"
            "Bu büyüme gerçekleşirse 35 görünen F/K aslında 28'e düşecek."
        ),
        "related": ["pe_ratio", "eps", "peg"],
    },

    {
        "id": "roe",
        "term": "Özsermaye Kârlılığı (ROE)",
        "eng": "Return on Equity",
        "category": "temel",
        "emoji": "🏦",
        "level": "orta",
        "definition": (
            "Şirketin hissedarların parasıyla ne kadar kâr ürettiğini gösterir. "
            "Yönetimin sermayeyi ne kadar verimli kullandığının ölçüsüdür. "
            "Yüksek ROE → şirket her yatırılan liradan fazla kazanıyor."
        ),
        "formula": "ROE = Net Kâr ÷ Özsermaye × 100",
        "how_to_read": (
            "• ROE > %20: Mükemmel — Warren Buffett'ın aradığı eşik bu.\n"
            "• ROE 10–20%: İyi — sektöre bağlı.\n"
            "• ROE < %10: Zayıf — sermaye verimsiz kullanılıyor.\n"
            "• Uyarı: Yüksek borç da ROE'yi şişirebilir. D/E ile birlikte değerlendir."
        ),
        "portfolio": (
            "Uzun vadeli yatırımda ROE en önemli metriklerden biri. "
            "Sürekli %20+ ROE koruyan şirketler rekabet avantajı olan şirketlerdir. "
            "Apple, Microsoft, Visa gibi şirketler bunu yıllar boyunca sürdürüyor."
        ),
        "example": (
            "Apple ROE: ~%150 (yüksek çünkü hisse geri alımları özsermayeyi küçülttü)\n"
            "Microsoft ROE: ~%35\n"
            "Exxon ROE: ~%18\n"
            "Genel imalat şirketi ROE: ~%12"
        ),
        "related": ["roa", "de_ratio", "net_margin", "fcf"],
    },

    {
        "id": "de_ratio",
        "term": "Borç/Özsermaye (D/E)",
        "eng": "Debt-to-Equity Ratio",
        "category": "temel",
        "emoji": "⚖️",
        "level": "başlangıç",
        "definition": (
            "Şirketin borçlarının özsermayesine oranıdır. "
            "Şirketin ne kadar borçla finanse edildiğini gösterir. "
            "Yüksek D/E → şirket borçla büyüyor, faiz riski yüksek."
        ),
        "formula": "D/E = Toplam Borç ÷ Özsermaye",
        "how_to_read": (
            "• D/E < 0.5: Çok az borç — muhafazakâr, güvenli.\n"
            "• D/E 0.5–1.5: Normal — sektöre göre değişir.\n"
            "• D/E > 2: Yüksek borç — faiz artışlarında tehlikeli.\n"
            "• Uyarı: Bankalar ve finans şirketleri doğası gereği yüksek D/E taşır — onları farklı değerlendir.\n"
            "• Faiz ortamı önemli: Faizler yükselirken yüksek D/E çok tehlikeli."
        ),
        "portfolio": (
            "Makro sekmesinde faiz yüksek görünüyorsa (10Y > %4.5), "
            "portföyündeki yüksek D/E'li hisseleri gözden geçir. "
            "Bu şirketlerin borç maliyeti artar, kârları düşer. "
            "Resesyon ortamında yüksek borçlu şirketler ilk iflas edenler olur."
        ),
        "example": (
            "Apple D/E: ~1.8 (yüksek görünür ama çok nakit var, net borç düşük)\n"
            "Tesla D/E: ~0.8\n"
            "AT&T D/E: ~1.5 (telekomda normal)\n"
            "Havayolu şirketleri D/E: 3–5 (çok borçlu sektör)"
        ),
        "related": ["roe", "fcf", "net_margin"],
    },

    {
        "id": "gross_margin",
        "term": "Brüt Kâr Marjı",
        "eng": "Gross Margin",
        "category": "temel",
        "emoji": "📐",
        "level": "başlangıç",
        "definition": (
            "Satışlardan üretim maliyeti düşüldükten sonra kalan yüzdedir. "
            "Şirketin ürünleri üzerinde ne kadar fiyatlama gücü olduğunu gösterir. "
            "Yüksek brüt marj → rekabet avantajı işareti."
        ),
        "formula": "Brüt Marj = (Gelir − Satılan Malın Maliyeti) ÷ Gelir × 100",
        "how_to_read": (
            "• Yazılım şirketleri: %70–90 (kod bir kez yazılır, sonsuz satılır)\n"
            "• Teknoloji donanımı: %35–50\n"
            "• Perakende: %25–40\n"
            "• Süpermarket: %20–25\n"
            "• Otomasyon/imalat: %15–30\n"
            "Sektörü dışında değerlendirme — süpermarket için %40 mucizevi, yazılım için %40 kötü."
        ),
        "portfolio": (
            "Brüt marjın düşmesi enflasyon veya rekabet baskısının işareti. "
            "Portföyündeki şirketin marjı çeyrekten çeyreğe düşüyorsa dikkat et. "
            "Yüksek ve stabil marj → güçlü marka, fiyatlama gücü."
        ),
        "example": (
            "Apple: %43 (donanım için olağanüstü)\n"
            "Microsoft: %69\n"
            "Nvidia: %74 (AI chip premium)\n"
            "Walmart: %24\n"
            "Amazon (retail): ~%6"
        ),
        "related": ["net_margin", "fcf", "revenue_growth"],
    },

    {
        "id": "fcf",
        "term": "Serbest Nakit Akışı (FCF)",
        "eng": "Free Cash Flow",
        "category": "temel",
        "emoji": "💸",
        "level": "orta",
        "definition": (
            "Şirketin tüm masraflarını ve yatırımlarını ödedikten sonra elinde kalan nakittir. "
            "'Gerçek kâr' olarak da bilinir çünkü muhasebe hilelerine karşı dayanıklıdır. "
            "Bu nakit temettü, hisse geri alımı veya büyüme yatırımı için kullanılır."
        ),
        "formula": "FCF = Operasyonel Nakit Akışı − Sermaye Harcamaları (CapEx)",
        "how_to_read": (
            "• Pozitif ve büyüyen FCF: Şirket gerçekten para kazanıyor — çok olumlu.\n"
            "• Negatif FCF: Büyüme yatırımı yapıyor olabilir (Amazon, Tesla ilk dönemler gibi) — bağlamı değerlendir.\n"
            "• FCF/Gelir oranı > %15: Çok verimli iş modeli.\n"
            "• Warren Buffett FCF'i en önemli metrik olarak görür."
        ),
        "portfolio": (
            "Kazanç açıklamalarında EPS'e değil FCF'e bak. "
            "EPS muhasebe oyunlarıyla şişirilebilir ama FCF banka hesabındaki gerçek paradır. "
            "Yüksek FCF'li şirketler hem kötü dönemlerde hayatta kalır hem de büyüme fırsatlarını değerlendirebilir."
        ),
        "example": (
            "Apple yıllık FCF: ~$100 milyar (dünyada rekor)\n"
            "Microsoft FCF: ~$60 milyar\n"
            "Tesla FCF: ~$4 milyar (hâlâ büyüme yatırımı fazla)\n"
            "FCF negatif şirket: SpaceX henüz halka açık değil ama büyük CapEx yatırımı var"
        ),
        "related": ["net_margin", "roe", "de_ratio"],
    },

    {
        "id": "revenue_growth",
        "term": "Gelir Büyümesi",
        "eng": "Revenue Growth",
        "category": "temel",
        "emoji": "📈",
        "level": "başlangıç",
        "definition": (
            "Şirketin bir önceki döneme göre satışlarının ne kadar arttığını gösterir. "
            "Büyüme hisseleri için en kritik metriklerden biridir. "
            "Şirketin pazarını genişletip genişletmediğini ölçer."
        ),
        "formula": "Gelir Büyümesi = (Bu Dönem Gelir − Geçen Dönem Gelir) ÷ Geçen Dönem Gelir × 100",
        "how_to_read": (
            "• > %20: Hızlı büyüme — teknoloji hisselerinde beklenir.\n"
            "• %10–20: Sağlıklı büyüme.\n"
            "• %5–10: Yavaş büyüme — olgun şirket.\n"
            "• < %5 veya negatif: Durgun/küçülen şirket — dikkat.\n"
            "• Büyüme mi, kârlılık mı? İkisi aynı anda olmak zorunda değil — Amazon yıllarca büyüdü ama az kâr etti."
        ),
        "portfolio": (
            "Rocket 🚀 kategorisindeki hisseler için büyüme en önemli metriktir. "
            "Shield 🛡️ hisseler için büyüme daha az kritik, istikrar önemli. "
            "Büyüme yavaşlayan bir teknoloji hissesi sert değer kaybedebilir."
        ),
        "example": (
            "Nvidia 2023: +%122 (AI patlaması)\n"
            "Microsoft: +%13\n"
            "Apple: +%2 (olgun pazar)\n"
            "Meta 2022: −%1 (kötü yıl), 2023: +%16 (toparlandı)"
        ),
        "related": ["eps", "gross_margin", "fcf"],
    },

    {
        "id": "beta",
        "term": "Beta",
        "eng": "Beta",
        "category": "temel",
        "emoji": "⚡",
        "level": "başlangıç",
        "definition": (
            "Bir hissenin piyasaya göre ne kadar oynak olduğunu ölçer. "
            "Beta = 1 ise hisse piyasayla aynı hareket eder. "
            "Bu değer dashboarddaki Rocket/Balanced/Shield kategori sisteminin temelidir."
        ),
        "formula": "Beta, hissenin S&P 500 ile tarihsel korelasyonuna göre hesaplanır",
        "how_to_read": (
            "• Beta > 1.5: Piyasadan çok daha oynak — piyasa %10 düşerse bu hisse %15 düşebilir.\n"
            "• Beta 0.8–1.2: Piyasaya yakın hareket — dengeli.\n"
            "• Beta < 0.5: Piyasadan bağımsız, savunmacı — kamu şirketleri, altın madencileri.\n"
            "• Beta < 0: Piyasayla ters hareket — altın, bazı bond ETF'leri."
        ),
        "portfolio": (
            "VIX yüksekken (korku ortamı) düşük beta hisseleri tercih et. "
            "Bull market döneminde yüksek beta hisseleri daha çok kazandırır. "
            "Portföyünün ortalama betası 1'in üzerindeyse risk yüksek demektir. "
            "Dashboard'daki kategori sistemi bu mantıkla çalışır: Rocket (yüksek beta) vs Shield (düşük beta)."
        ),
        "example": (
            "Nvidia Beta: ~1.7 (piyasadan %70 daha oynak)\n"
            "Apple Beta: ~1.2\n"
            "Johnson & Johnson Beta: ~0.5 (savunmacı)\n"
            "Altın ETF (GLD) Beta: ~0.0 (piyasayla ilgisiz)"
        ),
        "related": ["pe_ratio", "vix", "sharpe"],
    },

    {
        "id": "dividend_yield",
        "term": "Temettü Verimi",
        "eng": "Dividend Yield",
        "category": "temel",
        "emoji": "🎁",
        "level": "başlangıç",
        "definition": (
            "Şirketin hisse fiyatına oranla ne kadar temettü ödediğini gösterir. "
            "Hisseyi tutmanın 'faiz getirisi' gibi düşünebilirsin. "
            "Yüksek temettü genellikle olgun, istikrarlı şirketlerin özelliğidir."
        ),
        "formula": "Temettü Verimi = Yıllık Temettü ÷ Hisse Fiyatı × 100",
        "how_to_read": (
            "• %0: Büyüme hisseleri temettü ödemez (NVDA, TSLA, AMZN) — kârı büyümeye yatırıyor.\n"
            "• %1–2: Düşük — teknoloji şirketleri için normal.\n"
            "• %3–5: Sağlıklı temettü — dengeli portföy için ideal.\n"
            "• > %6: Yüksek görünür ama dikkat — fiyat düşmüş olabilir (temettü kesinti riski)."
        ),
        "portfolio": (
            "Shield 🛡️ kategorisindeki hisseler genellikle temettü öder. "
            "Enflasyona karşı koruma: temettü artıran şirketler (Dividend Aristocrats) enflasyonu geçebilir. "
            "Temettü yatırımı: Her ay temettü alarak portföy geliri oluşturabilirsin."
        ),
        "example": (
            "Coca-Cola (KO): ~%3.1 temettü\n"
            "Johnson & Johnson: ~%3.0\n"
            "Apple: ~%0.5 (az ama çok büyük rakam)\n"
            "AT&T: ~%7 (yüksek ama borç sorunları var)"
        ),
        "related": ["fcf", "pe_ratio", "beta"],
    },

    {
        "id": "mkt_cap",
        "term": "Piyasa Değeri",
        "eng": "Market Capitalization",
        "category": "temel",
        "emoji": "🏢",
        "level": "başlangıç",
        "definition": (
            "Şirketin borsadaki toplam değeridir. "
            "Tüm hisselerin fiyatla çarpımıdır. "
            "Şirketin 'büyüklüğünü' ölçer ve risk profilini belirler."
        ),
        "formula": "Piyasa Değeri = Hisse Fiyatı × Toplam Hisse Sayısı",
        "how_to_read": (
            "• Mega Cap (> $200B): Apple, Microsoft, Nvidia — çok istikrarlı, yavaş büyür.\n"
            "• Large Cap ($10–200B): Köklü şirketler — dengeli risk/getiri.\n"
            "• Mid Cap ($2–10B): Büyüme potansiyeli var, riski orta.\n"
            "• Small Cap (< $2B): Yüksek risk, yüksek büyüme potansiyeli.\n"
            "• Micro Cap (< $300M): Spekülatif — çok dikkatli ol."
        ),
        "portfolio": (
            "Dashboard'daki kategori sistemi piyasa değerine göre çalışır: "
            "küçük şirketler = Rocket 🚀 (yüksek risk/getiri), "
            "büyük şirketler = Shield 🛡️ (düşük risk/istikrar). "
            "Çeşitlendirilmiş portföy farklı büyüklüklerdeki şirketleri içermelidir."
        ),
        "example": (
            "Apple: ~$3 trilyon (dünya rekoru)\n"
            "Nvidia: ~$2 trilyon\n"
            "Tesla: ~$800 milyar\n"
            "Palantir: ~$50 milyar (mid-cap)\n"
            "IonQ: ~$2 milyar (small-cap, kuantum)"
        ),
        "related": ["beta", "pe_ratio", "revenue_growth"],
    },

    # ══════════════════════════════════════════════════════════════════════
    # MAKRO GÖSTERGELER
    # ══════════════════════════════════════════════════════════════════════

    {
        "id": "vix",
        "term": "VIX — Korku Endeksi",
        "eng": "CBOE Volatility Index",
        "category": "makro",
        "emoji": "😨",
        "level": "başlangıç",
        "definition": (
            "VIX, S&P 500 opsiyonlarından hesaplanan ve piyasanın önümüzdeki 30 gün için "
            "beklediği oynaklığı ölçer. 'Korku endeksi' olarak da bilinir. "
            "Yüksek VIX = piyasada panik, düşük VIX = rahatlık."
        ),
        "formula": "S&P 500 opsiyon fiyatlarından türetilen istatistiksel hesaplama",
        "how_to_read": (
            "• VIX < 15: Çok sakin — piyasa rahat, risk iştahı yüksek.\n"
            "• VIX 15–20: Normal — her gün bu bandda hareket eder.\n"
            "• VIX 20–30: Endişeli — belirsizlik arttı, dikkatli ol.\n"
            "• VIX > 30: Panik — büyük satış dalgası, kriz işareti.\n"
            "• VIX > 40: Ekstrem panik — 2008 krizi, COVID çöküşü gibi. "
            "Bu seviyelerde tarihsel olarak alım fırsatları doğar."
        ),
        "portfolio": (
            "VIX yükseliyorsa spekülatif pozisyon açma. "
            "VIX > 30'da portföyündeki yüksek beta hisseler en çok zarar görür. "
            "VIX çok yüksekken (40+) aşamalı alım fırsatı olabilir — panik satışları genellikle aşırıya kaçar. "
            "Dashboard makro sekmesinde VIX'i her gün kontrol et."
        ),
        "example": (
            "COVID Mart 2020: VIX = 85 (rekor!) → Sonraki 1 yılda S&P %80 yükseldi.\n"
            "2008 Krizi: VIX = 80\n"
            "Normal günler: VIX = 12–18\n"
            "Seçim dönemleri: VIX = 20–25"
        ),
        "related": ["fear_greed", "beta", "yield_curve", "spx"],
    },

    {
        "id": "yield_curve",
        "term": "Getiri Eğrisi",
        "eng": "Yield Curve",
        "category": "makro",
        "emoji": "📉",
        "level": "orta",
        "definition": (
            "Farklı vadeli ABD devlet tahvillerinin faiz oranlarını gösteren grafiktir. "
            "Normalde uzun vadeli tahviller (10Y) daha yüksek faiz taşır. "
            "Bu eğri 'ters döndüğünde' (kısa vade > uzun vade) tarihsel olarak resesyon habercisi olmuştur."
        ),
        "formula": "Yield Curve Spread = 10 Yıllık Tahvil − 2 Yıllık (veya 3 Aylık) Tahvil",
        "how_to_read": (
            "• Pozitif spread (normal): Uzun vade > kısa vade → ekonomi sağlıklı büyüyor.\n"
            "• Düz eğri (0'a yakın): Belirsizlik arttı — dikkat.\n"
            "• Negatif spread (ters eğri): Kısa vade > uzun vade → resesyon riski!\n"
            "  Son 50 yılda her resesyon öncesi yield curve ters döndü.\n"
            "• Gecikme: Ters döndükten sonra ortalama 12–18 ay içinde resesyon geldi."
        ),
        "portfolio": (
            "Yield curve ters döndüğünde: savunmacı hisselere geç (kamu, sağlık, tüketim). "
            "Bankalar için çok önemli: banka kısa vadeden borç alıp uzun vadede borç verir — "
            "ters eğri banka kârlarını sıkıştırır. "
            "Portföyünde banka ağırlığı varsa yield curve'e dikkat et."
        ),
        "example": (
            "2022–2023: Yield curve derin ters döndü → piyasa resesyon fiyatladı.\n"
            "10Y: %4.5, 2Y: %4.8 → Spread: −%0.3 (ters)\n"
            "2019 öncesi normal: 10Y %2.5, 2Y %2.0 → Spread: +%0.5"
        ),
        "related": ["fed_rate", "tnx", "vix", "dxy"],
    },

    {
        "id": "fed_rate",
        "term": "Fed Faiz Oranı",
        "eng": "Federal Funds Rate",
        "category": "makro",
        "emoji": "🏛",
        "level": "başlangıç",
        "definition": (
            "Amerikan Merkez Bankası (Fed) tarafından belirlenen temel faiz oranıdır. "
            "Tüm ekonomiyi etkiler: mortgage faizleri, kredi maliyetleri, şirket borçlanması. "
            "Hisse piyasaları için en kritik makro değişkenlerden biridir."
        ),
        "formula": "Fed tarafından her 6–8 haftada bir FOMC toplantılarında belirlenir",
        "how_to_read": (
            "• Faiz artışı: Borçlanma pahalılaşır → şirket kârları düşer → hisse değerlemeleri düşer.\n"
            "• Faiz indirimi: Borçlanma ucuzlar → hisse değerlemeleri yükselir.\n"
            "• Yüksek faiz ortamı: Growth/tech hisseleri zarar görür, value hisseler görece dayanır.\n"
            "• Düşük faiz ortamı: 'TINA' (There Is No Alternative) — hisseler cazip görünür."
        ),
        "portfolio": (
            "Makro sekmesinde Fed faizini sürekli takip et. "
            "Faiz artarken yüksek F/K'lı büyüme hisselerini azalt, temettü hisselerine ağırlık ver. "
            "Faiz inerken büyüme hisselerine gir — genellikle en hızlı onlar toparlar."
        ),
        "example": (
            "2020–2021: Fed faizi %0–0.25 → Hisse piyasası rekora koştu.\n"
            "2022–2023: Fed faizi %5.25'e çıktı → Büyüme hisseleri sert düştü.\n"
            "2024: İlk faiz indirimleri → Piyasa sevinçle karşıladı."
        ),
        "related": ["yield_curve", "tnx", "dxy", "vix"],
    },

    {
        "id": "dxy",
        "term": "DXY — Dolar Endeksi",
        "eng": "US Dollar Index",
        "category": "makro",
        "emoji": "💱",
        "level": "orta",
        "definition": (
            "ABD dolarının Euro, Japon Yeni, İngiliz Sterlini başta olmak üzere "
            "6 büyük para birimine karşı değerini ölçer. "
            "Güçlü dolar küresel ekonomiyi etkiler."
        ),
        "formula": "Euro (%57.6), Yen (%13.6), Sterlin (%11.9), Kanada Doları, İsviçre Frangı, İsveç Kronası ağırlıklı sepet",
        "how_to_read": (
            "• DXY > 105: Çok güçlü dolar → uluslararası şirketler zarar görür.\n"
            "• DXY 95–105: Normal bölge.\n"
            "• DXY < 95: Zayıf dolar → emtia fiyatları yükselir, gelişmekte olan piyasalar rahatlar.\n"
            "• Dolar güçlenince: Altın, petrol, bakır genellikle düşer (ters korelasyon)."
        ),
        "portfolio": (
            "Apple, Microsoft gibi global geliri olan şirketler güçlü dolardan zarar görür "
            "(yurt dışı geliri dolara çevrilince azalır). "
            "Türk/Azerbaycanlı yatırımcı olarak sen zaten dolar bazlı yatırım yapıyorsun — "
            "DXY yerel para biriminle ilişkin için kritik."
        ),
        "example": (
            "2022: DXY = 114 (20 yılın zirvesi) → S&P 500 %20 düştü.\n"
            "2023: DXY = 100'e geriledi → Piyasalar toparlandı.\n"
            "Kural: Dolar zayıfladığında gelişmekte olan piyasalara para akar."
        ),
        "related": ["fed_rate", "gold", "yield_curve"],
    },

    {
        "id": "gold",
        "term": "Altın (XAU/USD)",
        "eng": "Gold",
        "category": "makro",
        "emoji": "🥇",
        "level": "başlangıç",
        "definition": (
            "Altın tarihsel olarak 'güvenli liman' varlığıdır. "
            "Belirsizlik ve korku dönemlerinde yatırımcılar altına kaçar. "
            "Enflasyona karşı uzun vadeli koruma sağlar."
        ),
        "formula": "Spot fiyat: Ons başına dolar (XAU/USD)",
        "how_to_read": (
            "• Altın yükseliyorsa: Risk-off ortam, belirsizlik arttı.\n"
            "• Altın düşüyorsa: Risk-on ortam, yatırımcılar hisselere yöneldi.\n"
            "• Altın + Hisseler birlikte yükseliyorsa: Enflasyon beklentisi var.\n"
            "• Güçlü dolar + Altın yükselişi: Çok güçlü risk-off sinyali."
        ),
        "portfolio": (
            "Portföy sigortası gibi düşün. Hisseler düşerken altın genellikle yükselir. "
            "Toplam portföyün %5–10'u altın veya altın ETF'i (GLD, IAU) olabilir. "
            "Ama dikkat: Altın kâr etmez, sadece koruma sağlar."
        ),
        "example": (
            "2020 COVID krizi: Hisseler %35 düştü, altın %25 yükseldi.\n"
            "2023: Fed faiz artışlarına rağmen altın $2000+ tuttu — jeopolitik belirsizlik.\n"
            "Tarihsel: Altın 50 yılda ~%8/yıl getiri → enflasyonu geçti ama S&P 500'ü geçemedi."
        ),
        "related": ["vix", "dxy", "fed_rate"],
    },

    {
        "id": "copper",
        "term": "Bakır (Dr. Copper)",
        "eng": "Copper",
        "category": "makro",
        "emoji": "🔧",
        "level": "ileri",
        "definition": (
            "'Dr. Copper' lakabı piyasada yaygındır çünkü bakır inşaat, elektronik, ulaşım "
            "gibi tüm sektörlerde kullanılır ve küresel ekonomik aktiviteyle çok güçlü korelasyon taşır. "
            "Bakır fiyatı düşüyorsa ekonomi yavaşlıyor demektir."
        ),
        "formula": "Spot fiyat: Libre başına dolar (HG=F)",
        "how_to_read": (
            "• Bakır yükseliyorsa: Küresel büyüme hızlanıyor — risk-on, sanayi hisseleri iyi.\n"
            "• Bakır düşüyorsa: Büyüme yavaşlıyor — dikkat.\n"
            "• Bakır + Altın ayrışırsa: İki sinyal çelişiyor — belirsizlik var.\n"
            "• Çin talebi çok önemli: Dünya bakır talebinin %50'si Çin'den gelir."
        ),
        "portfolio": (
            "Bakır fiyatı düşerken sanayi, inşaat, madencilik hisselerine dikkat et. "
            "Bakır yükselişi: Freeport-McMoRan (FCX) gibi bakır madencileri, "
            "elektrikli araç üreticileri (bakır EV'de yoğun kullanılır) pozitif etkilenir."
        ),
        "example": (
            "2021: Bakır $4.7/libre (rekor) → Ekonomik toparlanma beklentisi\n"
            "2022: $3.2'ye düştü → Resesyon korkusu\n"
            "2024: $4+ → Enerji dönüşümü talebi (EV, solar)"
        ),
        "related": ["dxy", "yield_curve", "revenue_growth"],
    },

    # ══════════════════════════════════════════════════════════════════════
    # TEKNİK ANALİZ
    # ══════════════════════════════════════════════════════════════════════

    {
        "id": "rsi",
        "term": "RSI — Göreceli Güç Endeksi",
        "eng": "Relative Strength Index",
        "category": "teknik",
        "emoji": "💪",
        "level": "başlangıç",
        "definition": (
            "Bir hissenin belirli bir dönemdeki kazanç ve kayıplarını karşılaştırarak "
            "aşırı alım veya aşırı satım durumunu ölçer. "
            "0–100 arasında değer alır. TradingView grafiğinde alt panelde görebilirsin."
        ),
        "formula": "RSI = 100 − (100 ÷ (1 + Ortalama Kazanç / Ortalama Kayıp)) [14 günlük]",
        "how_to_read": (
            "• RSI > 70: Aşırı alım — hisse çok hızlı yükseldi, düzeltme gelebilir.\n"
            "• RSI 50–70: Güçlü momentum — trend yukarı.\n"
            "• RSI 30–50: Zayıf momentum — trend aşağı.\n"
            "• RSI < 30: Aşırı satım — hisse çok hızlı düştü, geri dönüş gelebilir.\n"
            "• Uyarı: Aşırı alım/satım uzun süre devam edebilir — tek başına karar verme."
        ),
        "portfolio": (
            "Alım kararında: RSI < 30 olan ve temel analizi güçlü hisseler alım fırsatı olabilir. "
            "Satış kararında: RSI > 70 olan ve F/K çok yüksek hisseleri gözden geçir. "
            "TradingView grafiğinde RSI'ı aç — dashboard'da zaten aktif."
        ),
        "example": (
            "NVDA Mart 2023: RSI = 28 → Aşırı satım → Sonraki 6 ayda %200 yükseldi.\n"
            "NVDA Temmuz 2023: RSI = 78 → Aşırı alım → Kısa süreli düzeltme geldi.\n"
            "Genel kural: RSI divergence (fiyat yükselirken RSI düşüyorsa) güçlü uyarı sinyali."
        ),
        "related": ["macd", "bollinger", "breakout_52h"],
    },

    {
        "id": "macd",
        "term": "MACD",
        "eng": "Moving Average Convergence Divergence",
        "category": "teknik",
        "emoji": "🔀",
        "level": "orta",
        "definition": (
            "İki hareketli ortalama arasındaki farkı ölçerek momentum ve trend değişimini tespit eder. "
            "12 günlük ve 26 günlük üstel hareketli ortalamanın farkından oluşur. "
            "TradingView grafiğinde alt panelde histogramla gösterilir."
        ),
        "formula": "MACD Çizgisi = 12 günlük EMA − 26 günlük EMA | Sinyal = 9 günlük EMA(MACD)",
        "how_to_read": (
            "• MACD çizgisi sinyal çizgisini yukarı kesiyorsa: Alım sinyali (bullish crossover).\n"
            "• MACD çizgisi sinyal çizgisini aşağı kesiyorsa: Satım sinyali (bearish crossover).\n"
            "• Histogram sıfırın üzerinde ve büyüyorsa: Güçlü yükseliş momentumu.\n"
            "• Histogram sıfırın altında ve küçülüyorsa: Düşüş zayıflıyor, toparlanma yakın."
        ),
        "portfolio": (
            "RSI ile birlikte kullan. İkisi de aynı sinyali veriyorsa güven artar. "
            "Büyük pozisyon açmadan önce MACD'nin teyidini bekle. "
            "Dashboard'daki TradingView grafiğinde MACD zaten aktif."
        ),
        "example": (
            "Kural: Fiyat düşerken MACD histogram yükseliyorsa → güçlü alım sinyali (bullish divergence).\n"
            "Temmuz 2023 S&P 500: MACD golden cross → Yükseliş trendi teyit edildi."
        ),
        "related": ["rsi", "ma50_200", "bollinger"],
    },

    {
        "id": "ma50_200",
        "term": "50/200 Günlük Hareketli Ortalama",
        "eng": "50/200 Day Moving Average",
        "category": "teknik",
        "emoji": "〰️",
        "level": "başlangıç",
        "definition": (
            "Son 50 veya 200 günün kapanış fiyatlarının ortalamasıdır. "
            "Kısa vadeli trend (50 gün) ve uzun vadeli trend (200 gün) için kullanılır. "
            "Destek ve direnç noktası görevi görür."
        ),
        "formula": "MA(n) = Son n günün kapanış fiyatlarının aritmetik ortalaması",
        "how_to_read": (
            "• Fiyat 200 MA üzerinde: Uzun vadeli boğa trendi.\n"
            "• Fiyat 200 MA altında: Uzun vadeli ayı trendi.\n"
            "• Golden Cross (50 MA, 200 MA'yı yukarı kesiyor): Güçlü alım sinyali.\n"
            "• Death Cross (50 MA, 200 MA'yı aşağı kesiyor): Güçlü satım sinyali.\n"
            "• 200 MA destek olarak çalışır: Fiyat 200 MA'ya gelip bounce yapıyor mu?"
        ),
        "portfolio": (
            "Hisse almadan önce fiyatın 200 MA üzerinde olmasını tercih et. "
            "Death Cross görünce pozisyonunu gözden geçir. "
            "Golden Cross'tan sonra girmek geç ama daha güvenli."
        ),
        "example": (
            "S&P 500 Ekim 2022: Death Cross → Düşüş trendi teyit.\n"
            "S&P 500 Şubat 2023: Golden Cross → Yükseliş başladı.\n"
            "200 MA seviyeleri kurumsal yatırımcılar tarafından çok yakından izlenir."
        ),
        "related": ["macd", "rsi", "breakout_52h"],
    },

    {
        "id": "breakout_52h",
        "term": "52 Haftalık Yüksek Kırılımı",
        "eng": "52-Week High Breakout",
        "category": "teknik",
        "emoji": "🚀",
        "level": "başlangıç",
        "definition": (
            "Bir hissenin son 52 haftanın en yüksek fiyatını geçmesidir. "
            "Bu seviye güçlü bir direnç noktasıdır — kırılınca momentum hızlanır. "
            "Dashboard'daki 52H alarm sistemi tam olarak bunu takip eder."
        ),
        "formula": "Mevcut Fiyat ≥ Son 52 Haftanın Maksimum Kapanış Fiyatı",
        "how_to_read": (
            "• 52H kırılımı: Genellikle güçlü alım sinyali — piyasa o hisseyi onaylıyor.\n"
            "• Hacimle desteklenirse: Çok daha güçlü sinyal (normal hacmin 2x+ üzeri).\n"
            "• Hacimsiz kırılım: Sahte kırılım olabilir, dikkat.\n"
            "• %90–99 bölge: Zirveye yaklaşıyor — izle ama henüz girmemiş."
        ),
        "portfolio": (
            "Dashboard'daki Takip sekmesi ve portföy tablosundaki 52H Pos. sütunu bunu gösterir. "
            "🔥 = zirve kırıldı, ⚡ = %0.5 yakında. "
            "Portföyde bu hisseler kısa vadede momentum kazanabilir. "
            "Sabah radarı bu kırılımları otomatik Telegram'a bildirir."
        ),
        "example": (
            "Nvidia Mayıs 2023: 52H kırılımı + 3x hacim → Sonraki 3 ayda %80 yükseldi.\n"
            "Kural: Yeni 52H yapan hisseler listedeki en güçlü hisselerdir."
        ),
        "related": ["rsi", "ma50_200", "beta"],
    },

    # ══════════════════════════════════════════════════════════════════════
    # PORTFÖY YÖNETİMİ
    # ══════════════════════════════════════════════════════════════════════

    {
        "id": "correlation",
        "term": "Korelasyon",
        "eng": "Correlation",
        "category": "portfoy",
        "emoji": "🔗",
        "level": "orta",
        "definition": (
            "İki varlığın birlikte nasıl hareket ettiğini ölçer. "
            "-1 ile +1 arasında değer alır. "
            "+1 = her zaman birlikte hareket, -1 = her zaman zıt hareket, 0 = ilgisiz."
        ),
        "formula": "Korelasyon katsayısı (Pearson): −1 ile +1 arasında",
        "how_to_read": (
            "• +0.8 ile +1.0: Çok yüksek pozitif korelasyon — birlikte düşer/yükselir.\n"
            "• +0.3 ile +0.7: Orta korelasyon — ilişkili ama bağımsız hareketler var.\n"
            "• 0 ile +0.3: Düşük korelasyon — görece bağımsız.\n"
            "• Negatif: Biri düşerken diğeri yükselir — portföy koruması sağlar."
        ),
        "portfolio": (
            "NVDA ve AMD aynı anda düşer (yüksek korelasyon — ikisi de chip). "
            "İdeal portföy: Düşük korelasyonlu hisseler bir arada. "
            "Dashboard portföy risk analizi tam olarak bunu yapar: "
            "hangi hisselerin birlikte düşeceğini söyler."
        ),
        "example": (
            "Yüksek korelasyon: NVDA + AMD (r = 0.85)\n"
            "Orta korelasyon: AAPL + XOM (r = 0.40)\n"
            "Düşük/negatif: Hisseler + Altın (r = −0.20)\n"
            "Portföy hatası: 5 farklı chip hissesi al — ama hepsi aynı düşer."
        ),
        "related": ["beta", "sharpe", "diversification"],
    },

    {
        "id": "diversification",
        "term": "Çeşitlendirme",
        "eng": "Diversification",
        "category": "portfoy",
        "emoji": "🌈",
        "level": "başlangıç",
        "definition": (
            "Riski azaltmak için farklı varlıklara, sektörlere ve coğrafyalara yatırım yapmaktır. "
            "'Tüm yumurtaları aynı sepete koyma' prensibidir. "
            "Ama aşırı çeşitlendirme getiriyi de düşürür — denge önemli."
        ),
        "formula": "Matematiksel kural değil, strateji kararı",
        "how_to_read": (
            "• 1 hisse: Maksimum risk, maksimum potansiyel getiri.\n"
            "• 5–10 hisse: İyi çeşitlendirme — bireysel yatırımcı için ideal.\n"
            "• 20–30 hisse: Çok iyi çeşitlendirme — profesyonel portföy.\n"
            "• 50+ hisse: Endeks gibi — yönetmesi zor, endeksten iyi performans zor.\n"
            "• Sektörel çeşitlendirme: Aynı sektörden 3 hisse = tek hisse gibi."
        ),
        "portfolio": (
            "Dashboard portföy risk analizi sektör ağırlıklarını hesaplayarak "
            "aşırı yoğunlaşmayı gösterir. "
            "Örnek: Portföyünün %60'ı teknoloji ise ve bir kriz gelirse "
            "tüm portföy birlikte düşer — çeşitlendirme yok demektir."
        ),
        "example": (
            "İdeal çeşitlendirme: Teknoloji %30, Sağlık %20, Finans %15, "
            "Enerji %15, Tüketim %10, Diğer %10\n"
            "Zayıf çeşitlendirme: NVDA %30, AAPL %25, MSFT %20, AMD %15, TSLA %10\n"
            "→ Hepsi teknoloji, birlikte düşer."
        ),
        "related": ["correlation", "beta", "sharpe"],
    },

    {
        "id": "sharpe",
        "term": "Sharpe Oranı",
        "eng": "Sharpe Ratio",
        "category": "portfoy",
        "emoji": "⚖️",
        "level": "ileri",
        "definition": (
            "Alınan risk başına kazanılan getiriyi ölçer. "
            "'Ne kadar risk alarak ne kadar kazandın?' sorusunun cevabıdır. "
            "İki portföyü karşılaştırırken getiri değil Sharpe oranına bak."
        ),
        "formula": "Sharpe = (Portföy Getirisi − Risksiz Faiz) ÷ Portföy Volatilitesi",
        "how_to_read": (
            "• Sharpe < 0: Risksiz faizden bile az kazanıyorsun — portföy başarısız.\n"
            "• Sharpe 0–1: Orta — kabul edilebilir.\n"
            "• Sharpe 1–2: İyi — profesyonel portföy bu bölgededir.\n"
            "• Sharpe > 2: Mükemmel — Warren Buffett 30 yıllık Sharpe'ı ~0.8."
        ),
        "portfolio": (
            "Yüksek getiri her zaman iyi değil — nasıl bir riskle elde edildiği önemli. "
            "%50 kazanan ama çok oynak portföy vs %20 kazanan ama istikrarlı portföy: "
            "Sharpe ikinci portföyü tercih edebilir."
        ),
        "example": (
            "S&P 500 tarihsel Sharpe: ~0.4–0.5\n"
            "İyi hedge fund hedefi: Sharpe > 1\n"
            "Madoff dolandırıcılığını şüpheli yapan şey: İddia ettiği Sharpe 2.5+ idi — imkânsız."
        ),
        "related": ["correlation", "diversification", "beta"],
    },

    {
        "id": "drawdown",
        "term": "Düşüş (Drawdown)",
        "eng": "Maximum Drawdown",
        "category": "portfoy",
        "emoji": "📉",
        "level": "orta",
        "definition": (
            "Portföyün veya hissenin zirveden en derin dip noktasına kadar yaşadığı "
            "maksimum değer kaybının yüzdesidir. "
            "Psikolojik dayanıklılık için önemlidir: Bu kaybı göğüsleyebilir misin?"
        ),
        "formula": "Max Drawdown = (Zirve Değer − Dip Değer) ÷ Zirve Değer × 100",
        "how_to_read": (
            "• %10: Normal piyasa gürültüsü — görmezden gel.\n"
            "• %20: Ayı piyasası eşiği — ciddi düşüş.\n"
            "• %30–40: Kriz düzeyi — 2022 Nasdaq bu kadardı.\n"
            "• %50+: Şiddetli kriz — 2008, COVID anlık düşüş.\n"
            "• Bireysel hisse %80 düşebilir — şirket iflasından değil bile."
        ),
        "portfolio": (
            "Yatırım yaparken kendine sor: Bu hisse/portföy %40 düşse ne yaparım? "
            "Panikleyip satarsan büyük zarar gerçekleşir. "
            "Drawdown'ı bilmek disiplinli kalmaya yardımcı olur."
        ),
        "example": (
            "S&P 500 2022 yılı max drawdown: −%25\n"
            "Nasdaq 2022: −%33\n"
            "Bitcoin 2022: −%75\n"
            "Bir hisse (ZOOM 2020–2022): −%90"
        ),
        "related": ["beta", "sharpe", "vix"],
    },

    # ══════════════════════════════════════════════════════════════════════
    # DEĞERLEME
    # ══════════════════════════════════════════════════════════════════════

    {
        "id": "peg",
        "term": "PEG Oranı",
        "eng": "Price/Earnings to Growth",
        "category": "degerlem",
        "emoji": "🎯",
        "level": "orta",
        "definition": (
            "F/K oranını büyüme hızıyla kıyaslayan geliştirilmiş değerleme metriğidir. "
            "F/K'nın büyüme beklentisi olmadan anlamsız olduğunu düzelten formüldür. "
            "Peter Lynch tarafından popülerleştirildi."
        ),
        "formula": "PEG = F/K Oranı ÷ Yıllık EPS Büyüme Oranı (%)",
        "how_to_read": (
            "• PEG < 1: Büyümesine göre ucuz — potansiyel alım fırsatı.\n"
            "• PEG = 1: Adil değerlenmiş.\n"
            "• PEG > 2: Büyümesine göre pahalı.\n"
            "• PEG negatif: EPS küçülüyor — dikkat.\n"
            "• Kural: F/K 40 ama %50 büyüyorsa PEG = 0.8 → Aslında ucuz!"
        ),
        "portfolio": (
            "Büyüme hisselerini değerlendirirken F/K yerine PEG kullan. "
            "NVDA F/K 60 pahalı görünür ama %70 büyüyorsa PEG = 0.85 → Makul."
        ),
        "example": (
            "Şirket A: F/K = 20, EPS büyüme = %10 → PEG = 2.0 (pahalı)\n"
            "Şirket B: F/K = 40, EPS büyüme = %50 → PEG = 0.8 (ucuz!)\n"
            "Hangisi daha iyi? Şirket B — büyümesine göre daha ucuz."
        ),
        "related": ["pe_ratio", "forward_pe", "revenue_growth"],
    },

    {
        "id": "margin_of_safety",
        "term": "Güvenlik Marjı",
        "eng": "Margin of Safety",
        "category": "degerlem",
        "emoji": "🛡",
        "level": "orta",
        "definition": (
            "Bir hissenin gerçek (içsel) değeri ile piyasa fiyatı arasındaki farktır. "
            "Benjamin Graham ve Warren Buffett'ın temel ilkesi: "
            "'1 dolarlık değere 0.70 dolar öde — 0.30 dolar güvenlik marjın var.'"
        ),
        "formula": "Güvenlik Marjı = (İçsel Değer − Piyasa Fiyatı) ÷ İçsel Değer × 100",
        "how_to_read": (
            "• %30+ güvenlik marjı: Güçlü alım fırsatı (değer yatırımı)\n"
            "• %10–30: Makul fırsat\n"
            "• %0: Adil değerlenmiş\n"
            "• Negatif: Piyasa fiyatı içsel değerin üzerinde — pahalı.\n"
            "• Sorun: İçsel değeri hesaplamak özneldir — DCF varsayımlarına bağlı."
        ),
        "portfolio": (
            "Değer yatırımcısı gibi düşün: Her alımda güvenlik marjını sorgula. "
            "Büyüme hisselerinde bu kavram daha az uygulanır çünkü "
            "gelecekteki büyümeyi fiyatlamak zordur."
        ),
        "example": (
            "Coca-Cola içsel değer hesabı: $65\n"
            "Piyasa fiyatı: $50\n"
            "Güvenlik marjı: %23 → Makul alım fırsatı\n\n"
            "Buffett kuralı: Yanlış olsam bile para kaybetmeyeyim."
        ),
        "related": ["pe_ratio", "peg", "fcf"],
    },

    # ══════════════════════════════════════════════════════════════════════
    # PİYASA YAPISI
    # ══════════════════════════════════════════════════════════════════════

    {
        "id": "bull_bear",
        "term": "Boğa / Ayı Piyasası",
        "eng": "Bull / Bear Market",
        "category": "piyasa",
        "emoji": "🐂🐻",
        "level": "başlangıç",
        "definition": (
            "Boğa piyasası (Bull Market): Piyasanın genel olarak %20+ yükseldiği, "
            "iyimserliğin hâkim olduğu dönem.\n"
            "Ayı piyasası (Bear Market): Piyasanın en yüksek noktasından %20+ düştüğü, "
            "kötümserliğin hâkim olduğu dönem."
        ),
        "formula": "Bear: Zirve'den %20+ düşüş | Bull: Dip'ten %20+ yükseliş",
        "how_to_read": (
            "• Bull piyasası: Risk al, büyüme ve teknoloji ağırlığını artır.\n"
            "• Bear piyasası: Savunmaya çekil, nakit tut, temettü hisseleri öne çıkar.\n"
            "• Correction (düzeltme): %10–20 düşüş — bear değil, normal.\n"
            "• Bear piyasası ortalama 9 ay sürer, bull piyasası ortalama 2.7 yıl."
        ),
        "portfolio": (
            "Makro sekmesindeki Piyasa Rejimi bu kavramın pratik uygulamasıdır. "
            "'Risk Al' = bull ortam, 'Riskten Kaç' = bear ortam. "
            "Bear piyasasında panikleyip satma — tarihsel olarak yanlış karar."
        ),
        "example": (
            "En uzun bull piyasası: 2009–2020 (11 yıl)\n"
            "2022 bear piyasası: S&P 500 −%25, Nasdaq −%33\n"
            "COVID bear (2020): Sadece 33 gün — en kısa bear piyasası"
        ),
        "related": ["vix", "yield_curve", "spx"],
    },

    {
        "id": "sector_rotation",
        "term": "Sektör Rotasyonu",
        "eng": "Sector Rotation",
        "category": "piyasa",
        "emoji": "🔄",
        "level": "ileri",
        "definition": (
            "Ekonomik döngünün farklı aşamalarında yatırımcıların bir sektörden diğerine "
            "geçiş yapmasıdır. Her ekonomik dönem farklı sektörleri öne çıkarır."
        ),
        "formula": "Ekonomik döngü: Genişleme → Zirve → Daralma → Dip → Toparlanma",
        "how_to_read": (
            "• Genişleme döneminde öne çıkanlar: Teknoloji, Tüketici Takdiri, Sanayi.\n"
            "• Zirve döneminde: Enerji, Hammadde.\n"
            "• Daralma döneminde: Sağlık, Kamu Hizmetleri, Temel Tüketim.\n"
            "• Dip döneminde: Finans, Teknoloji (ilk toparlayanlar).\n"
            "Kurumsal yatırımcılar milyarlarca doları bu rotasyona göre hareket ettirir."
        ),
        "portfolio": (
            "Dashboard'daki sektör sekmesi bu rotasyondan faydalanmak için var. "
            "Makro göstergeler bir daralma dönemini işaret ediyorsa "
            "portföyünü savunmacı sektörlere (Sağlık, Kamu) kaydır."
        ),
        "example": (
            "2022: Fed faiz artırdı → Enerji +%65, Teknoloji −%33\n"
            "2023: Faiz zirvesi yakın beklentisi → Teknoloji geri döndü\n"
            "Kural: 'Haber çıkınca sat' — rotasyon haberi gelmeden başlar."
        ),
        "related": ["bull_bear", "fed_rate", "yield_curve"],
    },

    {
        "id": "liquidity",
        "term": "Likidite",
        "eng": "Liquidity",
        "category": "piyasa",
        "emoji": "💧",
        "level": "orta",
        "definition": (
            "Bir varlığın fiyatını çok etkilemeden ne kadar hızlı alınıp satılabileceğidir. "
            "Yüksek likidite = kolayca al/sat. Düşük likidite = zorlu çıkış."
        ),
        "formula": "Likidite = Ortalama Günlük Hacim × Hisse Fiyatı",
        "how_to_read": (
            "• Günlük hacim > $1 milyar: Çok likit — Apple, Microsoft gibi.\n"
            "• Günlük hacim $100M–$1B: İyi likidite.\n"
            "• Günlük hacim < $10M: Düşük likidite — dikkat, çıkış zor olabilir.\n"
            "• Kriz dönemlerinde likidite kurur — kimse almak istemez."
        ),
        "portfolio": (
            "Küçük şirket hisselerinde likidite riski var. "
            "Büyük pozisyon almak istiyorsan hacme bak. "
            "Likidite riski: Çıkmak istediğinde alıcı bulamazsan fiyat çöker."
        ),
        "example": (
            "Apple günlük hacim: ~$5 milyar → Çok likit\n"
            "Small-cap hisse günlük hacim: $500K → Az likit\n"
            "Kriz 2008: En likit varlıklar bile anlık likit kalmadı"
        ),
        "related": ["mkt_cap", "beta", "drawdown"],
    },
]


def get_all_terms() -> list[dict]:
    return TERMS


def get_terms_by_category(category: str) -> list[dict]:
    return [t for t in TERMS if t["category"] == category]


def search_terms(query: str) -> list[dict]:
    q = query.lower().strip()
    if not q:
        return TERMS
    results = []
    for t in TERMS:
        searchable = (
            t["term"].lower() + " " +
            t["eng"].lower() + " " +
            t["definition"].lower() + " " +
            t.get("id", "")
        )
        if q in searchable:
            results.append(t)
    return results


def get_term_by_id(term_id: str) -> dict | None:
    for t in TERMS:
        if t["id"] == term_id:
            return t
    return None
